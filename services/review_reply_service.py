from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from models import Review

SERIOUS_KEYWORDS = (
    "food poisoning",
    "poison",
    "allerg",
    "anaphyl",
    "sick",
    "ill",
    "hospital",
    "health",
    "unsafe",
    "hygiene",
    "contamin",
    "foreign object",
    "glass",
    "hair",
    "bug",
    "insect",
    "mold",
    "mould",
    "raw",
    "undercooked",
    "expired",
    "stale",
    "fssai",
    "legal",
    "lawyer",
    "sue",
)


def review_needs_attention(review: Review) -> Dict[str, Any]:
    """Flag low ratings or reviews mentioning health/safety concerns."""
    rating = int(review.rating or 0)
    comment = (review.comment or "").lower()
    matched_keywords = [kw for kw in SERIOUS_KEYWORDS if kw in comment]
    low_rating = rating <= 2
    return {
        "needs_attention": low_rating or bool(matched_keywords),
        "low_rating": low_rating,
        "serious_keywords": matched_keywords,
    }


def _build_reply_prompt(
    review: Review,
    bakery_name: str,
    store_details: Dict[str, str],
    attention: Dict[str, Any],
) -> str:
    product_name = review.product.name if review.product else "our product"
    customer_name = review.author.name if review.author else "the customer"
    comment = (review.comment or "").strip() or "(no written comment)"
    store_name = store_details.get("name") or bakery_name
    phone = store_details.get("phone") or ""

    tone = (
        f"You write on behalf of {bakery_name} ({store_name}), a warm artisan bakery in "
        f"{store_details.get('city', 'our city')}. Be sincere, grateful, and concise."
    )
    if attention["needs_attention"]:
        tone += (
            " This review raises a serious concern. Acknowledge it honestly, apologize where "
            "appropriate, and invite the customer to contact the bakery directly to resolve it. "
            "Do not dismiss, minimize, or argue. Do not claim facts you cannot verify."
        )
    else:
        tone += " Thank the customer warmly and reflect the bakery's caring voice."

    return (
        f"{tone}\n\n"
        f"Product: {product_name}\n"
        f"Customer: {customer_name}\n"
        f"Rating: {review.rating}/5\n"
        f"Review: {comment}\n\n"
        "Write a single public reply (2-4 sentences). Sign off as the bakery team."
        + (f" Mention they can reach us at {phone} if follow-up is needed." if phone else "")
    )


def _extract_llm_text(response: Any) -> str:
    if isinstance(response, dict):
        choices = response.get("choices") or []
        if choices:
            text = choices[0].get("text") or choices[0].get("message", {}).get("content", "")
            return (text or "").strip()
        return (response.get("text") or "").strip()
    return str(response or "").strip()


def _call_local_llm(prompt: str, max_tokens: int = 180) -> Optional[str]:
    try:
        from recommendation_engine import Llama, LLM_MODEL_PATH
    except Exception:
        return None

    if Llama is None or not LLM_MODEL_PATH:
        return None

    try:
        llm = Llama(model_path=LLM_MODEL_PATH)
        response = llm(
            prompt,
            max_tokens=max_tokens,
            temperature=0.4,
            stop=["\n\nCustomer:", "\n\nProduct:", "\n\nReview:"],
        )
        text = _extract_llm_text(response)
        return text or None
    except Exception:
        return None


def generate_review_reply_draft(
    review: Review,
    bakery_name: str,
    store_details: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Generate a suggested admin reply draft. Never persists or posts automatically."""
    store_details = store_details or {}
    attention = review_needs_attention(review)
    prompt = _build_reply_prompt(review, bakery_name, store_details, attention)
    draft = _call_local_llm(prompt)

    if not draft:
        return {
            "ok": False,
            "draft": "",
            "generation_failed": True,
            "llm_available": False,
            "needs_attention": attention["needs_attention"],
            "attention": attention,
            "message": "Generation failed — please write a reply manually.",
        }

    draft = re.sub(r"\s+", " ", draft).strip()
    return {
        "ok": True,
        "draft": draft,
        "generation_failed": False,
        "llm_available": True,
        "needs_attention": attention["needs_attention"],
        "attention": attention,
        "message": "",
    }
