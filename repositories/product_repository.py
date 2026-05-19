from difflib import SequenceMatcher

from models import Product, SearchAnalytics, db


class ProductRepository:
    def active_search(self, query_text, limit=5):
        query_text = (query_text or "").strip()
        if not query_text:
            return []
        query = Product.query.filter(Product.is_active.is_(True))
        broad_matches = query.limit(200).all()

        ranked = sorted(
            broad_matches,
            key=lambda product: self._score_product(query_text, product),
            reverse=True,
        )
        results = [product for product in ranked if self._score_product(query_text, product) > 0][:limit]
        if not results:
            results = (
                query.filter(Product.name.ilike(f"%{query_text}%"))
                .limit(limit)
                .all()
            )

        for product in results:
            self._record_search(query_text, product.id)
        db.session.commit()
        return results

    def trending_products(self, limit=5):
        rows = (
            db.session.query(Product, SearchAnalytics.hit_count)
            .join(SearchAnalytics, SearchAnalytics.product_id == Product.id)
            .order_by(SearchAnalytics.hit_count.desc(), SearchAnalytics.last_searched_at.desc())
            .limit(limit)
            .all()
        )
        return [product for product, _count in rows]

    def _score_product(self, query_text, product):
        normalized_query = query_text.lower()
        haystack = " ".join(
            filter(
                None,
                [
                    product.name,
                    product.description,
                    product.occasion_tags,
                    product.category.name if product.category else "",
                ],
            )
        ).lower()
        if not haystack:
            return 0
        exact_bonus = 2.0 if normalized_query in haystack else 0
        fuzzy = SequenceMatcher(None, normalized_query, haystack).ratio()
        token_hits = sum(1 for token in normalized_query.split() if token and token in haystack)
        return exact_bonus + fuzzy + token_hits * 0.25

    def _record_search(self, query_text, product_id):
        entry = SearchAnalytics.query.filter_by(
            query_text=query_text.lower(),
            product_id=product_id,
        ).first()
        if entry is None:
            entry = SearchAnalytics(
                query_text=query_text.lower(),
                product_id=product_id,
            )
            db.session.add(entry)
        entry.hit_count = int(entry.hit_count or 0) + 1
