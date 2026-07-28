from decimal import Decimal

from sqlalchemy import text

from models import FinancialTransaction, db
from services.finance_service import FinanceService


def test_financial_transaction_sensitive_fields_are_encrypted_at_rest(db_session):
    service = FinanceService()
    service.ensure_default_categories()
    category = service.get_category("other_expense")
    assert category is not None

    txn = FinancialTransaction(
        transaction_type="expense",
        category_id=category.id,
        amount=Decimal("1234.56"),
        tax_amount=Decimal("78.90"),
        description="Plain rent note",
        counterparty="Sensitive Vendor",
        tds_withheld=Decimal("12.34"),
    )
    db_session.add(txn)
    db_session.commit()

    loaded = db.session.get(FinancialTransaction, txn.id)
    assert loaded.amount == Decimal("1234.56")
    assert loaded.tax_amount == Decimal("78.90")
    assert loaded.description == "Plain rent note"
    assert loaded.counterparty == "Sensitive Vendor"
    assert loaded.tds_withheld == Decimal("12.34")

    raw = db.session.execute(
        text(
            """
            SELECT amount, tax_amount, description, counterparty, tds_withheld
            FROM financial_transactions
            WHERE id = :transaction_id
            """
        ),
        {"transaction_id": txn.id},
    ).one()

    raw_blob = b"".join(bytes(value or b"") for value in raw)
    assert b"1234.56" not in raw_blob
    assert b"78.90" not in raw_blob
    assert b"Plain rent note" not in raw_blob
    assert b"Sensitive Vendor" not in raw_blob
    assert b"12.34" not in raw_blob
