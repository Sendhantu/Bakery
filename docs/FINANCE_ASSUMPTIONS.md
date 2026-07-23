# Finance Module — Assumptions & Review Checklist

This document lists every ambiguous or assumed behavior in the SweetCrumbs finance module.
**Do not use exported figures for GST/ITR filing without accountant review.**

---

## 1. Tax-inclusive vs tax-exclusive pricing — **AMBIGUOUS / ASSUMED**

**Finding:** Checkout sets `order.total = subtotal - discounts + delivery_charge` with **no GST line added**.
`InvoiceService.calculate_gst_breakdown()` treats the taxable base as **exclusive** and adds GST on top, but prints `order.total` as the grand total — an inconsistency in the existing codebase.

**Assumption made:** Customer shelf prices are treated as **tax-inclusive** for finance auto-recording.
When an order is paid, output GST is **extracted** from the inclusive amount using:

```
GST = inclusive_amount - (inclusive_amount / (1 + rate/100))
```

The rate comes from `order.gst_rate`, else the active `TaxRate` for `applies_to=sales`, else **5% default seed**.

**Action required:** Confirm with your accountant whether prices are inclusive or exclusive, then align checkout, invoices, and finance extraction logic.

---

## 2. Multi-store structure — **PARTIAL**

**Finding:** `Branch` model and `branch_id` FKs exist, but checkout assigns `DEFAULT_BRANCH_ID` only.
Analytics does not filter by branch.

**Assumption made:**
- `FinancialTransaction.store_location` stores branch name (or `STORE_DETAILS.name` fallback).
- Store ledger groups by `store_location` on recorded transactions.
- Auto sale transactions use `order.branch_id`.

**Action required:** If you operate multiple stores with separate GST registrations, configure branches and ensure orders are tagged correctly at checkout.

---

## 3. TDS / vendor payments — **LIMITED DATA**

**Finding:** No dedicated vendor payment or accounts-payable module exists. `Supplier` is metadata only.

**Assumption made:**
- TDS is captured only when admin manually enters `tds_withheld` on expense transactions.
- TDS summary is a **placeholder aggregation** of those manual entries.
- No automatic TDS calculation by section/rate.

**Action required:** Implement vendor payment workflows or integrate with accounting software if TDS compliance is required.

---

## 4. Auto income on payment — **ASSUMED TRIGGER**

**Assumption made:** A sale income row is created when `Payment.transition_to("PAID")` succeeds (idempotent per order).
This covers POS, COD collection, and offline sync — **not** a separate “order delivered” event.

**Action required:** Confirm whether revenue should be recognized on payment, delivery, or invoice date for your books.

---

## 5. COGS calculation — **ESTIMATE ONLY**

**Assumption made:**
- Product COGS = Σ (`ProductMaterial.quantity_required` × `RawMaterial.cost_per_unit`) × units sold.
- Uses **current** `cost_per_unit`, not historical purchase cost at time of sale.
- Revenue uses Phase 2 analytics (`DELIVERED` + `PAID` orders, `OrderItem.subtotal`).

**Action required:** For accurate margins, maintain historical cost snapshots or tie COGS to actual purchase expenses.

---

## 6. Stock restock → expense — **SEMI-AUTOMATIC**

**Assumption made:**
- Admin raw-material stock **increases** now create `StockMovement` with reason `manual_restock`.
- Admin is redirected to a one-click expense form with suggested amount = `change_qty × cost_per_unit`.
- Purchase price can differ; admin must confirm/edit before logging.

**Note:** Product variant stock updates still do **not** create stock movements (unchanged from Phase 3 scope).

---

## 7. Encryption — **SETUP REQUIRED**

Sensitive fields encrypted at rest (Fernet): `amount`, `tax_amount`, `description`, `counterparty`, `tds_withheld`.

### Environment variable

```bash
# Generate a key (run once, store securely):
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Set in production:
export FINANCIAL_DATA_ENCRYPTION_KEY="<paste-key-here>"
```

### Development fallback

If `ALLOW_DEV_FINANCIAL_KEY_DERIVATION=true` (default in development) and no key is set, a key is derived from `SECRET_KEY`.
**Disable this in production** (`ALLOW_DEV_FINANCIAL_KEY_DERIVATION=false`) and set an explicit key.

### Key rotation

Fernet keys are not rotated automatically. Rotating requires a re-encryption migration script (not included).
Plan rotation with downtime or a dual-key decrypt/re-encrypt procedure.

---

## 8. Access control — **STRICTER THAN GENERAL ADMIN**

Finance routes use `@finance_required`: **`admin` and `super_admin` only**.

Other admin portal roles (`branch_manager`, `cashier`, `kitchen_staff`) cannot access finance even though they can access other admin pages.

**Note:** `User.permissions` JSON exists but is not enforced — no finance-specific permission tier beyond role name.

---

## 9. Tax rates — **ADMIN MUST CONFIGURE**

Default seed: `gst_default_5` at 5% for `applies_to=sales`.

GST rates vary by HSN/product category and change over time. The module does **not** auto-update statutory rates.

---

## 10. No auto-filing

This module **does not** submit data to GSTN, income tax portals, or any government API.
`TaxRecord` rows are local snapshots for review/export only.

---

## 11. Export formats

- **CSV:** All ledger views and transaction lists.
- **PDF:** P&L, product ledger, GST summary via existing **reportlab** dependency (no new PDF library added).

Excel (`.xlsx`) is not included — CSV can be opened in Excel.

---

## 12. Decimal precision

All currency model fields use `Numeric` / `Decimal`. Encrypted amounts are stored as encrypted decimal strings.

---

## Quick setup checklist

1. [ ] Set `FINANCIAL_DATA_ENCRYPTION_KEY` in production
2. [ ] Set `ALLOW_DEV_FINANCIAL_KEY_DERIVATION=false` in production
3. [ ] Run migration: `flask db upgrade`
4. [ ] Review/configure tax rates at `/admin/finance/tax-rates`
5. [ ] Confirm tax-inclusive vs exclusive pricing with accountant
6. [ ] Verify a test paid order creates a sales transaction in `/admin/finance`
7. [ ] Review COGS and GST figures against manual books before any filing
