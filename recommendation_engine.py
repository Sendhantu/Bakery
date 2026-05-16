"""
Recommendation engine — works with or without ML packages.
On Render (no numpy/faiss/sentence-transformers), falls back to
trending-score + rules-based ranking which works well for a bakery.
"""
import os
import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import selectinload

from models import Order, OrderItem, Product, db

# ── optional heavy deps ──────────────────────────────────────────────────────
try:
    import numpy as np
    _NUMPY = True
except ImportError:
    np = None
    _NUMPY = False

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

try:
    import faiss
except ImportError:
    faiss = None

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None
# ─────────────────────────────────────────────────────────────────────────────

EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
LLM_MODEL_PATH = os.environ.get('LLM_MODEL_PATH', '')


def _normalize_vector(values: List[float]) -> List[float]:
    if not values:
        return []
    if _NUMPY:
        array = np.array(values, dtype=float)
        low = float(array.min())
        high = float(array.max())
    else:
        low = min(values)
        high = max(values)
    if high <= low:
        return [1.0 if v > 0 else 0.0 for v in values]
    return [(v - low) / (high - low) for v in values]


def _parse_budget(query: str) -> Optional[float]:
    query = query.replace('₹', ' ').replace('rs', ' ').replace('rupee', ' ')
    matches = re.findall(r'\b(?:under|below|less than|up to|max)\s*([0-9]+)', query)
    if matches:
        return float(matches[0])
    matches = re.findall(r'([0-9]+)\s*(?:rs|rupees|rupee|₹)', query)
    if matches:
        return float(matches[0])
    return None


def _find_keyword(query: str, options: List[str]) -> Optional[str]:
    for option in options:
        if option.lower() in query:
            return option
    return None


def _safe_text(value: Optional[str]) -> str:
    if not value:
        return ''
    return value.strip().lower()


class RecommendationEngine:
    def __init__(self):
        self.embedding_model = None
        self.llm = None
        self.products: List[Product] = []
        self.product_ids: List[int] = []
        self.product_index: Dict[int, int] = {}
        self.product_embeddings = None  # np.ndarray when numpy available
        self.index = None
        self.trending_scores: Dict[int, float] = {}
        self.order_counts: Dict[int, int] = {}

    def _build_text(self, product: Product) -> str:
        parts = [product.name, getattr(product.category, 'name', None),
                 product.occasion_tags, product.description, product.ingredients]
        return ' '.join([p.strip() for p in parts if p]).lower()

    def _ensure_embedding_model(self):
        if self.embedding_model is not None:
            return
        if SentenceTransformer is None:
            raise RuntimeError('sentence-transformers not available')
        self.embedding_model = SentenceTransformer(EMBEDDING_MODEL)

    def _ensure_faiss(self):
        if faiss is None:
            raise RuntimeError('faiss-cpu not available')

    def _ensure_llm(self):
        if self.llm is not None:
            return
        if not Llama or not LLM_MODEL_PATH:
            return
        self.llm = Llama(model_path=LLM_MODEL_PATH)

    def _ml_available(self) -> bool:
        return _NUMPY and SentenceTransformer is not None and faiss is not None

    def build(self, rebuild: bool = False):
        # Always load products and trending scores (no ML needed)
        if self.products and not rebuild:
            return

        products = Product.query.options(
            selectinload(Product.category)
        ).filter_by(is_active=True).all()
        self.products = products
        self.product_ids = [p.id for p in products]
        self.product_index = {p.id: idx for idx, p in enumerate(products)}

        if not products:
            self.trending_scores = {}
            self.order_counts = {}
            self.index = None
            self.product_embeddings = None
            return

        ordered_data = db.session.query(
            OrderItem.product_id,
            func.count(OrderItem.id),
        ).join(Order, Order.id == OrderItem.order_id).filter(
            Order.status == 'DELIVERED'
        ).group_by(OrderItem.product_id).all()

        self.order_counts = {pid: int(cnt) for pid, cnt in ordered_data}
        raw_scores = [
            self.order_counts.get(p.id, 0) + (3 if p.is_featured else 0)
            for p in products
        ]
        normalized = _normalize_vector(raw_scores)
        self.trending_scores = {p.id: normalized[idx] for idx, p in enumerate(products)}

        # Build ML index only if all packages available
        if self._ml_available() and (self.index is None or rebuild):
            try:
                self._ensure_embedding_model()
                product_texts = [self._build_text(p) for p in products]
                embeddings = self.embedding_model.encode(
                    product_texts,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                    normalize_embeddings=True,
                )
                if embeddings.ndim == 1:
                    embeddings = embeddings.reshape(1, -1)
                embeddings = embeddings.astype('float32')
                self.product_embeddings = embeddings
                self.index = faiss.IndexFlatIP(embeddings.shape[1])
                self.index.add(embeddings)
            except Exception:
                self.index = None
                self.product_embeddings = None

    def search_similar(self, query: str, k: int = 12) -> List[Tuple[int, float]]:
        if not query or self.index is None:
            return []
        try:
            self._ensure_embedding_model()
            vector = self.embedding_model.encode(
                [query], convert_to_numpy=True, normalize_embeddings=True
            ).astype('float32')
            k = min(k, int(self.index.ntotal))
            distances, indices = self.index.search(vector, k)
            results = []
            for score, idx in zip(distances[0].tolist(), indices[0].tolist()):
                if idx < 0:
                    continue
                results.append((self.product_ids[idx], float(score)))
            return results
        except Exception:
            return []

    def _text_similarity(self, query: str, product: Product) -> float:
        """Simple keyword overlap score — used when faiss/numpy not available."""
        if not query:
            return 0.0
        text = self._build_text(product)
        tokens = set(re.findall(r'\b[a-z0-9]+\b', query.lower()))
        if not tokens:
            return 0.0
        hits = sum(1 for t in tokens if t in text)
        return hits / len(tokens)

    def _user_profile(self, user_id: Optional[int]) -> Dict[str, Dict[str, float]]:
        if not user_id:
            return {'product_counts': {}, 'category_counts': {}, 'tag_counts': {}}
        rows = db.session.query(
            OrderItem.product_id,
            func.count(OrderItem.id),
        ).join(Order, Order.id == OrderItem.order_id).filter(
            Order.user_id == user_id,
            Order.status == 'DELIVERED'
        ).group_by(OrderItem.product_id).all()

        product_counts = {pid: int(cnt) for pid, cnt in rows}
        category_counts: Dict[str, float] = {}
        tag_counts: Dict[str, float] = {}

        for product_id, count in product_counts.items():
            if product_id not in self.product_index:
                continue
            product = self.products[self.product_index[product_id]]
            category = _safe_text(getattr(product.category, 'name', ''))
            if category:
                category_counts[category] = category_counts.get(category, 0.0) + count
            text = self._build_text(product)
            for keyword in re.findall(r'\b[a-z0-9]+\b', text):
                tag_counts[keyword] = tag_counts.get(keyword, 0.0) + min(count, 3)

        return {
            'product_counts': product_counts,
            'category_counts': category_counts,
            'tag_counts': tag_counts,
        }

    def _history_score(self, profile: Dict[str, Dict[str, float]], product: Product) -> float:
        if not profile.get('product_counts') and not profile.get('category_counts'):
            return 0.0
        score = 0.0
        if product.id in profile['product_counts']:
            score += profile['product_counts'][product.id] * 3.0
        category = _safe_text(getattr(product.category, 'name', ''))
        score += profile['category_counts'].get(category, 0.0) * 1.5
        product_text = self._build_text(product)
        for token, weight in profile['tag_counts'].items():
            if token in product_text:
                score += min(weight * 0.1, 2.0)
        return float(score)

    def _parse_query(self, query: str) -> Dict:
        q = query.lower()
        return {
            'budget': _parse_budget(q),
            'sweetness': 'less' if re.search(r'less sweet|not too sweet|light sweet|low sugar', q) else None,
            'eggless': 'eggless' if 'eggless' in q or 'no egg' in q else None,
            'flavor': _find_keyword(q, [
                'chocolate', 'vanilla', 'strawberry', 'coffee', 'berry', 'nut',
                'caramel', 'lemon', 'citrus', 'mango', 'cookies', 'cream',
                'salted', 'butter', 'brownie', 'red velvet'
            ]),
            'occasion': _find_keyword(q, [
                'birthday', 'wedding', 'anniversary', 'baby shower', 'valentine',
                'christmas', 'new year', 'festival', 'party', 'picnic',
                'corporate', 'graduation'
            ]),
            'season': _find_keyword(q, [
                'summer', 'winter', 'spring', 'autumn', 'fall', 'festive', 'seasonal'
            ]),
            'raw_query': q,
        }

    def _rules_score(self, parsed: Dict, product: Product) -> float:
        score = 0.0
        text = self._build_text(product)
        price = float(product.base_price or 0)
        if parsed['budget'] is not None:
            if price <= parsed['budget']:
                score += 1.0
            elif price <= parsed['budget'] * 1.15:
                score += 0.4
            else:
                score -= 0.2
        if parsed['occasion'] and parsed['occasion'] in text:
            score += 1.2
        if parsed['eggless'] and product.is_eggless:
            score += 1.0
        if parsed['flavor'] and parsed['flavor'] in text:
            score += 1.0
        if parsed['sweetness'] == 'less' and any(w in text for w in ('less sweet', 'light', 'low sugar')):
            score += 1.0
        if parsed['season'] and parsed['season'] in text:
            score += 0.8
        return max(0.0, min(score / 4.0, 1.0))

    def _build_message(self, query: str, products: List[Product], is_new_customer: bool) -> str:
        if not products:
            return 'We are still learning your taste. Try browsing our bakery collections for fresh recommendations.'
        primary = products[0]
        secondary = products[1] if len(products) > 1 else None
        upsell = products[2] if len(products) > 2 else None
        lines = [
            f"For your request, {primary.name} is a great choice!"
        ]
        if secondary:
            lines.append(f"You may also enjoy {secondary.name}.")
        if upsell:
            lines.append(f"{upsell.name} makes a perfect complement as well.")
        return ' '.join(lines)

    def _llm_enabled(self) -> bool:
        return Llama is not None and bool(LLM_MODEL_PATH)

    def recommend(self, user_id: Optional[int], query: str, limit: int = 6) -> Tuple[List[Product], str]:
        self.build()
        parsed = self._parse_query(query or '')
        profile = self._user_profile(user_id)
        is_new_customer = not bool(profile['product_counts'])

        # Use ML semantic search if available, else keyword similarity
        if self._ml_available() and self.index is not None:
            semantic_candidates = self.search_similar(query, k=40) if query else []
            semantic_scores = {pid: score for pid, score in semantic_candidates}
            candidate_ids = set(semantic_scores.keys())
        else:
            semantic_scores = {}
            candidate_ids = set()

        if profile['product_counts']:
            candidate_ids.update(profile['product_counts'].keys())

        trending_ids = sorted(
            self.product_ids,
            key=lambda pid: self.trending_scores.get(pid, 0.0),
            reverse=True
        )[:30]
        candidate_ids.update(trending_ids)

        if not candidate_ids:
            candidate_ids = set(self.product_ids)

        scores = []
        for pid in candidate_ids:
            if pid not in self.product_index:
                continue
            product = self.products[self.product_index[pid]]
            content_score = semantic_scores.get(pid) or self._text_similarity(query, product)
            cf_score = self._history_score(profile, product)
            rule_score = self._rules_score(parsed, product)
            trending_score = self.trending_scores.get(pid, 0.0)

            if is_new_customer:
                total = 0.5 * trending_score + 0.3 * content_score + 0.2 * rule_score
            else:
                total = 0.4 * cf_score + 0.3 * content_score + 0.2 * rule_score + 0.1 * trending_score

            if parsed['budget'] and float(product.base_price or 0) > parsed['budget'] * 1.4:
                total *= 0.6
            if query and parsed['flavor'] and parsed['flavor'] not in self._build_text(product):
                total *= 0.92
            if getattr(product, 'total_stock', 1) == 0:
                total *= 0.5

            scores.append((total, product))

        scores.sort(key=lambda x: x[0], reverse=True)
        recommended = [p for _, p in scores][:limit]
        message = self._build_message(query, recommended, is_new_customer)
        return recommended, message


_ENGINE: Optional[RecommendationEngine] = None


def get_recommendation_engine() -> RecommendationEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RecommendationEngine()
    return _ENGINE