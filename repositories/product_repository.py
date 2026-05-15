from models import Product


class ProductRepository:
    def active_search(self, query_text, limit=5):
        query_text = (query_text or "").strip()
        if not query_text:
            return []
        return (
            Product.query.filter(
                Product.name.ilike(f"%{query_text}%"),
                Product.is_active.is_(True),
            )
            .limit(limit)
            .all()
        )
