from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any, Dict, Iterable, List


def _format_decimal(value) -> str:
    return f"{Decimal(str(value or 0)):.2f}"


class FinanceExportService:
    def transactions_csv(self, transactions: Iterable) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "Date",
                "Type",
                "Category",
                "Amount",
                "Tax Amount",
                "TDS Withheld",
                "Store",
                "Counterparty",
                "Description",
                "Order ID",
                "Stock Movement ID",
                "Auto Generated",
            ]
        )
        for txn in transactions:
            writer.writerow(
                [
                    txn.created_at.strftime("%Y-%m-%d %H:%M") if txn.created_at else "",
                    txn.transaction_type,
                    txn.category.label if txn.category else "",
                    _format_decimal(txn.amount),
                    _format_decimal(txn.tax_amount),
                    _format_decimal(txn.tds_withheld),
                    txn.store_location or "",
                    txn.counterparty or "",
                    txn.description or "",
                    txn.reference_order_id or "",
                    txn.reference_stock_movement_id or "",
                    "yes" if txn.is_auto_generated else "no",
                ]
            )
        return buffer.getvalue().encode("utf-8")

    def rows_csv(self, headers: List[str], rows: List[List[Any]]) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue().encode("utf-8")

    def simple_pdf(self, title: str, lines: List[str]) -> bytes:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        y = height - 50
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(50, y, title[:90])
        y -= 28
        pdf.setFont("Helvetica", 10)
        for line in lines:
            if y < 60:
                pdf.showPage()
                y = height - 50
                pdf.setFont("Helvetica", 10)
            pdf.drawString(50, y, str(line)[:110])
            y -= 14
        pdf.showPage()
        pdf.save()
        buffer.seek(0)
        return buffer.getvalue()

    def profit_and_loss_pdf(self, payload: Dict[str, Any]) -> bytes:
        lines = [
            f"Period: {payload['start'].date()} to {payload['end'].date()}",
            f"Income: INR {_format_decimal(payload['income'])}",
            f"Expenses: INR {_format_decimal(payload['expenses'])}",
            f"Net Profit: INR {_format_decimal(payload['net_profit'])}",
            "",
            "Review all figures with your accountant before filing.",
        ]
        return self.simple_pdf("Profit & Loss Summary", lines)

    def product_ledger_pdf(self, rows: List[Dict[str, Any]], start, end) -> bytes:
        lines = [f"Period: {start.date()} to {end.date()}", ""]
        for row in rows:
            lines.append(
                f"{row['product_name']}: units={row['units_sold']} revenue={_format_decimal(row['revenue'])} "
                f"cogs={_format_decimal(row['cogs'])} gross={_format_decimal(row['gross_profit'])}"
            )
        return self.simple_pdf("Product Ledger", lines)

    def gst_summary_pdf(self, payload: Dict[str, Any]) -> bytes:
        lines = [
            f"Period: {payload['start'].date()} to {payload['end'].date()}",
            f"GST Collected (output tax): INR {_format_decimal(payload['gst_collected'])}",
            f"GST Paid (input credit): INR {_format_decimal(payload['gst_paid'])}",
            f"Net GST Liability: INR {_format_decimal(payload['net_gst_liability'])}",
            "",
            "Figures are calculated from recorded transactions only.",
        ]
        return self.simple_pdf("GST Summary", lines)
