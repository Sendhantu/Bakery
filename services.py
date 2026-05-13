from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import selectinload

from models import (
    db,
    Category,
    Coupon,
    Delivery,
    DeliveryAgent,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    RawMaterial,
    Review,
    User,
    Wishlist,
)


def paginate_query(query, page, per_page):
    return query.paginate(page=page, per_page=per_page, error_out=False)


def page_args(default_per_page=12, max_per_page=50):
    from flask import request

    page = request.args.get('page', 1, type=int) or 1
    per_page = request.args.get('per_page', default_per_page, type=int) or default_per_page
    return max(1, page), max(1, min(per_page, max_per_page))


def enrich_products(products):
    product_ids = [product.id for product in products]
    if not product_ids:
        return products

    review_rows = db.session.query(
        Review.product_id,
        func.count(Review.id),
        func.coalesce(func.avg(Review.rating), 0),
    ).filter(
        Review.product_id.in_(product_ids)
    ).group_by(Review.product_id).all()
    review_stats = {
        product_id: {
            'count': int(count or 0),
            'avg': round(float(avg or 0), 1),
        }
        for product_id, count, avg in review_rows
    }

    variant_rows = db.session.query(
        ProductVariant.product_id,
        func.min(ProductVariant.id),
        func.coalesce(func.sum(ProductVariant.stock), 0),
    ).filter(
        ProductVariant.product_id.in_(product_ids)
    ).group_by(ProductVariant.product_id).all()
    variant_stats = {
        product_id: {
            'default_variant_id': variant_id,
            'total_stock': int(total_stock or 0),
        }
        for product_id, variant_id, total_stock in variant_rows
    }

    for product in products:
        review_info = review_stats.get(product.id, {'count': 0, 'avg': 0})
        variant_info = variant_stats.get(product.id, {'default_variant_id': None, 'total_stock': 0})
        product._review_count_cache = review_info['count']
        product._avg_rating_cache = review_info['avg']
        product._default_variant_id_cache = variant_info['default_variant_id']
        product._total_stock_cache = variant_info['total_stock']

    return products


def enrich_orders(orders):
    order_ids = [order.id for order in orders]
    if not order_ids:
        return orders

    item_count_rows = db.session.query(
        OrderItem.order_id,
        func.count(OrderItem.id),
    ).filter(
        OrderItem.order_id.in_(order_ids)
    ).group_by(OrderItem.order_id).all()
    item_counts = {order_id: int(item_count or 0) for order_id, item_count in item_count_rows}

    preview_rows = db.session.query(
        OrderItem.order_id,
        OrderItem.product_name,
        OrderItem.quantity,
    ).filter(
        OrderItem.order_id.in_(order_ids)
    ).order_by(OrderItem.order_id.asc(), OrderItem.id.asc()).all()
    previews = defaultdict(list)
    for order_id, product_name, quantity in preview_rows:
        if len(previews[order_id]) >= 3:
            continue
        previews[order_id].append({
            'product_name': product_name,
            'quantity': quantity,
        })

    for order in orders:
        order.item_count = item_counts.get(order.id, 0)
        order.preview_items = previews.get(order.id, [])
        order.preview_remaining = max(0, order.item_count - len(order.preview_items))

    return orders


def get_customer_orders_page(user_id, page, per_page):
    pagination = Order.query.filter_by(user_id=user_id)\
        .order_by(Order.placed_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    enrich_orders(pagination.items)
    return pagination


def get_customer_products_page(filters, page, per_page):
    q = filters.get('q')
    cat_id = filters.get('category')
    eggless = filters.get('eggless')
    min_price = filters.get('min_price')
    max_price = filters.get('max_price')
    occasion = filters.get('occasion')
    sort = filters.get('sort') or 'featured'

    # Try Meilisearch if query is present
    if q:
        import meilisearch
        import os
        from flask import current_app
        try:
            client = meilisearch.Client(
                os.environ.get('MEILI_HOST', 'http://127.0.0.1:7700'),
                os.environ.get('MEILI_MASTER_KEY', 'masterKey123')
            )
            index = client.index('products')
            
            filter_arr = ['is_active = true']
            if cat_id: filter_arr.append(f'category_id = {cat_id}')
            if min_price: filter_arr.append(f'price >= {min_price}')
            if max_price: filter_arr.append(f'price <= {max_price}')
            
            results = index.search(q, {
                'filter': filter_arr,
                'offset': (page - 1) * per_page,
                'limit': per_page
            })
            
            p_ids = [hit['id'] for hit in results['hits']]
            if p_ids:
                # Maintain Meilisearch score ordering
                query = Product.query.options(selectinload(Product.category)).filter(Product.id.in_(p_ids))
                items = query.all()
                items.sort(key=lambda x: p_ids.index(x.id))
                enrich_products(items)
                
                # Mock pagination object for the template
                class MockPagination:
                    def __init__(self, items, total):
                        self.items = items
                        self.total = total
                        self.page = page
                        self.pages = (total + per_page - 1) // per_page
                        self.has_prev = page > 1
                        self.has_next = page < self.pages
                        self.prev_num = page - 1
                        self.next_num = page + 1
                        self.iter_pages = lambda: range(1, self.pages + 1)
                
                return MockPagination(items, results['estimatedTotalHits'])
        except Exception as e:
            # Fallback to DB if Meilisearch fails or is not running
            pass

    # Fallback SQL Query
    query = Product.query.options(selectinload(Product.category)).filter_by(is_active=True)
    if q:
        query = query.filter(Product.name.ilike(f'%{q}%'))
    if cat_id:
        query = query.filter_by(category_id=cat_id)
    if eggless == 1:
        query = query.filter_by(is_eggless=True)
    elif eggless == 0:
        query = query.filter_by(is_eggless=False)
    if occasion:
        query = query.filter(Product.occasion_tags.ilike(f'%{occasion}%'))
    if min_price:
        query = query.filter(Product.base_price >= min_price)
    if max_price:
        query = query.filter(Product.base_price <= max_price)

    if sort == 'price_asc':
        query = query.order_by(Product.base_price.asc(), Product.created_at.desc())
    elif sort == 'price_desc':
        query = query.order_by(Product.base_price.desc(), Product.created_at.desc())
    elif sort == 'newest':
        query = query.order_by(Product.created_at.desc())
    elif sort == 'rating':
        query = query.outerjoin(Review, Review.product_id == Product.id)\
            .group_by(Product.id)\
            .order_by(func.coalesce(func.avg(Review.rating), 0).desc(), Product.created_at.desc())
    else:
        query = query.order_by(Product.is_featured.desc(), Product.created_at.desc())

    pagination = query\
        .paginate(page=page, per_page=per_page, error_out=False)
    enrich_products(pagination.items)
    return pagination


def get_customer_wishlist_page(user_id, page, per_page):
    pagination = Wishlist.query.options(
        selectinload(Wishlist.product).selectinload(Product.category)
    ).filter_by(user_id=user_id)\
        .order_by(Wishlist.added_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    enrich_products([item.product for item in pagination.items if item.product])
    return pagination


def get_admin_products_page(search, page, per_page):
    query = Product.query.options(selectinload(Product.category))
    if search:
        query = query.filter(Product.name.ilike(f'%{search}%'))
    pagination = query.order_by(Product.is_active.desc(), Product.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    enrich_products(pagination.items)
    return pagination


def get_admin_orders_page(status, scope, search, page, per_page):
    query = Order.query.options(selectinload(Order.customer))
    if status:
        query = query.filter_by(status=status)
    if search:
        like = f'%{search}%'
        query = query.join(Order.customer).filter(
            (Order.order_number.ilike(like)) |
            (User.name.ilike(like)) |
            (User.email.ilike(like)) |
            (Order.phone.ilike(like))
        )
    if scope:
        today = func.date(Order.placed_at)
        if scope == 'today':
            from datetime import datetime
            query = query.filter(today == datetime.utcnow().date())
        elif scope == 'pending':
            query = query.filter(Order.status.in_(['PLACED', 'PREPARING']))

    pagination = query.order_by(Order.placed_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    enrich_orders(pagination.items)
    return pagination


def get_admin_customers_page(search, page, per_page):
    query = User.query.filter_by(role='customer')
    if search:
        like = f'%{search}%'
        query = query.filter((User.name.ilike(like)) | (User.email.ilike(like)))

    pagination = query.order_by(User.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    user_ids = [user.id for user in pagination.items]
    order_counts = {}
    if user_ids:
        order_rows = db.session.query(
            Order.user_id,
            func.count(Order.id),
        ).filter(Order.user_id.in_(user_ids)).group_by(Order.user_id).all()
        order_counts = {user_id: int(count or 0) for user_id, count in order_rows}

    for user in pagination.items:
        user.order_count = order_counts.get(user.id, 0)

    return pagination


def get_admin_raw_materials_page(search, page, per_page):
    query = RawMaterial.query
    if search:
        query = query.filter(RawMaterial.name.ilike(f'%{search}%'))
    return query.order_by(RawMaterial.is_active.desc(), RawMaterial.name.asc())\
        .paginate(page=page, per_page=per_page, error_out=False)


def get_admin_coupons_page(search, page, per_page):
    query = Coupon.query
    if search:
        query = query.filter(Coupon.code.ilike(f'%{search}%'))
    pagination = query.order_by(Coupon.id.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    for coupon in pagination.items:
        coupon.is_currently_valid = coupon.is_valid()
    return pagination


def get_admin_agents():
    agents = DeliveryAgent.query.order_by(DeliveryAgent.name.asc()).all()
    agent_ids = [agent.id for agent in agents]
    delivery_counts = {}
    if agent_ids:
        delivery_rows = db.session.query(
            Delivery.agent_id,
            func.count(Delivery.id),
        ).filter(Delivery.agent_id.in_(agent_ids)).group_by(Delivery.agent_id).all()
        delivery_counts = {agent_id: int(count or 0) for agent_id, count in delivery_rows}

    for agent in agents:
        agent.delivery_count = delivery_counts.get(agent.id, 0)
    return agents


def get_category_summaries():
    categories = Category.query.order_by(Category.name.asc()).all()
    category_ids = [category.id for category in categories]
    product_counts = {}
    if category_ids:
        rows = db.session.query(
            Product.category_id,
            func.count(Product.id),
        ).filter(Product.category_id.in_(category_ids)).group_by(Product.category_id).all()
        product_counts = {category_id: int(count or 0) for category_id, count in rows}

    for category in categories:
        category.product_count = product_counts.get(category.id, 0)
    return categories


def build_category_revenue_rows(category_revenue):
    normalized_rows = [
        {
            'name': name,
            'revenue': int(revenue or 0),
        }
        for name, revenue in category_revenue
    ]
    max_revenue = max((row['revenue'] for row in normalized_rows), default=1)
    for row in normalized_rows:
        row['width_pct'] = round((row['revenue'] / max_revenue) * 100, 1) if max_revenue else 0
    return normalized_rows
