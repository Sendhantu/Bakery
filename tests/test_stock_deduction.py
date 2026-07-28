from decimal import Decimal

import pytest

from models import StockMovement
from services.inventory_service import InventoryService, ValidationError


def test_order_raw_material_deduction_updates_stock_and_records_movements(
    db_session,
    raw_material_factory,
    product_factory,
    order_factory,
):
    flour = raw_material_factory(name="Deduction Flour", stock=Decimal("10"))
    sugar = raw_material_factory(name="Deduction Sugar", stock=Decimal("5"))
    product, variant = product_factory(
        name="Deduction Cake",
        recipe=[(flour, Decimal("1.25")), (sugar, Decimal("0.50"))],
    )
    order = order_factory(
        product=product,
        variant=variant,
        quantity=2,
        total=Decimal("240"),
    )
    item = order.items.first()

    changed_ids = InventoryService().deduct_order_raw_materials([item], order)
    db_session.flush()

    assert changed_ids == [flour.id, sugar.id]
    assert flour.stock == Decimal("7.50")
    assert sugar.stock == Decimal("4.00")

    movements = (
        StockMovement.query.filter_by(reference_order_id=order.id)
        .order_by(StockMovement.raw_material_id.asc())
        .all()
    )
    assert [movement.reason for movement in movements] == [
        "order_deduction",
        "order_deduction",
    ]
    assert [movement.change_amount for movement in movements] == [
        Decimal("-2.50"),
        Decimal("-1.00"),
    ]
    assert [movement.stock_after for movement in movements] == [
        Decimal("7.50"),
        Decimal("4.00"),
    ]


def test_order_raw_material_deduction_blocks_insufficient_stock_without_changes(
    db_session,
    raw_material_factory,
    product_factory,
    order_factory,
):
    flour = raw_material_factory(name="Limited Flour", stock=Decimal("1"))
    product, variant = product_factory(
        name="Oversized Cake",
        recipe=[(flour, Decimal("0.75"))],
    )
    order = order_factory(
        product=product,
        variant=variant,
        quantity=2,
        total=Decimal("200"),
    )
    item = order.items.first()

    with pytest.raises(ValidationError, match="Insufficient stock: Limited Flour"):
        InventoryService().deduct_order_raw_materials([item], order)

    db_session.rollback()
    assert flour.stock == Decimal("1.00")
    assert StockMovement.query.filter_by(reference_order_id=order.id).count() == 0
