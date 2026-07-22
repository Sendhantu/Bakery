from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List

from models import Order, RawMaterial


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _order_sort_key(order: Order):
    item_count = order.items.count() if hasattr(order, "items") else 0
    placed_at = order.placed_at or order.updated_at or order.id
    return (
        placed_at,
        item_count,
        float(order.total or 0),
        order.id,
    )


def _build_order_material_requirements(order: Order) -> Dict[int, Decimal]:
    requirements: Dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in order.items.all():
        product = item.product
        if product is None:
            continue
        for recipe_item in product.recipe_items.all():
            if recipe_item.quantity_required is None:
                continue
            requirements[recipe_item.raw_material_id] += (
                _decimal(recipe_item.quantity_required)
                * Decimal(max(1, int(item.quantity or 0)))
            )
    return dict(requirements)


def _build_material_lookup() -> Dict[int, RawMaterial]:
    return {material.id: material for material in RawMaterial.query.filter_by(is_active=True).all()}


def _fallback_note(order_result: Dict[str, Any]) -> str:
    status = order_result["status"]
    order_id = order_result["order"].id
    if status == "fulfillable_now":
        return f"Order #{order_id} is ready to go now. The available raw material queue covers this order."

    shortages = order_result.get("shortages", [])
    if status == "fulfillable_with_restock":
        parts = [
            f"Order #{order_id} is a good candidate for restock-driven fulfillment."
        ]
        for shortage in shortages:
            parts.append(
                f"{shortage['material_name']} is short by {shortage['shortage_qty']} {shortage['unit']} and sits at or below its reorder level."
            )
        return " ".join(parts)

    parts = [f"Order #{order_id} is blocked for now."]
    for shortage in shortages:
        parts.append(
            f"{shortage['material_name']} is short by {shortage['shortage_qty']} {shortage['unit']}."
        )
    return " ".join(parts)


def generate_smart_triage_report(pending_orders: List[Order]) -> Dict[str, Any]:
    """Return a deterministic, explainable fulfillment triage report for pending orders."""
    ordered_pending = sorted(pending_orders, key=_order_sort_key)
    materials_by_id = _build_material_lookup()
    stock_by_material = {
        material_id: _decimal(material.stock) for material_id, material in materials_by_id.items()
    }
    priority_order = []
    grouped_results = {
        "fulfillable_now": [],
        "fulfillable_with_restock": [],
        "blocked": [],
    }

    for order in ordered_pending:
        requirements = _build_order_material_requirements(order)
        shortage_details = []
        blocked = False
        restock = False

        for material_id, required_qty in requirements.items():
            material = materials_by_id.get(material_id)
            if material is None:
                continue

            available = stock_by_material.get(material_id, Decimal("0"))
            if available >= required_qty:
                stock_by_material[material_id] = available - required_qty
                continue

            shortage_qty = required_qty - available
            shortage_details.append(
                {
                    "material_id": material_id,
                    "material_name": material.name,
                    "unit": material.unit,
                    "shortage_qty": shortage_qty.quantize(Decimal("0.01")),
                    "current_stock": _decimal(material.stock),
                    "reorder_level": _decimal(material.reorder_level),
                }
            )

            if _decimal(material.stock) <= _decimal(material.reorder_level):
                restock = True
            else:
                blocked = True

        if not shortage_details:
            status = "fulfillable_now"
        elif restock and not blocked:
            status = "fulfillable_with_restock"
        else:
            status = "blocked"

        order_result = {
            "order": order,
            "status": status,
            "shortages": shortage_details,
            "required_materials": requirements,
            "item_count": order.items.count() if hasattr(order, "items") else 0,
            "priority_rank": len(priority_order) + 1,
            "note": "",
        }
        order_result["note"] = _fallback_note(order_result)
        grouped_results[status].append(order_result)
        priority_order.append(order.id)

    return {
        "priority_order": priority_order,
        "grouped_results": grouped_results,
        "status_order": ["fulfillable_now", "fulfillable_with_restock", "blocked"],
        "priority_rule": (
            "Priority follows the oldest pending order first, with ties broken by fewer items and then lower total so a large order does not needlessly block several smaller fast-moving orders."
        ),
    }


def summarize_triage_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Return human-readable notes for each triaged order. Falls back to deterministic text when no local LLM is available."""
    summary_by_order: Dict[int, str] = {}
    summary_payload = {"notes": summary_by_order, "llm_available": False}

    try:
        from recommendation_engine import Llama, LLM_MODEL_PATH
    except Exception:
        Llama = None
        LLM_MODEL_PATH = ""

    if Llama is not None and LLM_MODEL_PATH:
        try:
            llm = Llama(model_path=LLM_MODEL_PATH)
            for status, items in report.get("grouped_results", {}).items():
                for order_result in items:
                    order = order_result["order"]
                    prompt = (
                        "You are a bakery operations assistant. Rewrite the deterministic triage result without inventing stock counts. "
                        f"Status: {status}. Order #{order.order_number} (id {order.id}) has item count {order_result['item_count']}. "
                        f"Notes: {order_result['note']}"
                    )
                    llm_response = llm(
                        prompt,
                        max_tokens=120,
                        temperature=0.0,
                        stop=["\n\n"],
                    )
                    text = llm_response.get("choices", [{}])[0].get("text", "") if isinstance(llm_response, dict) else str(llm_response)
                    summary_by_order[order.id] = text.strip() or order_result["note"]
            summary_payload["llm_available"] = True
            summary_payload["notes"] = summary_by_order
            return summary_payload
        except Exception:
            pass

    for status, items in report.get("grouped_results", {}).items():
        for order_result in items:
            order = order_result["order"]
            summary_by_order[order.id] = order_result["note"]

    return summary_payload
