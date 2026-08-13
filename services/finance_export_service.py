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
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
        except ModuleNotFoundError:
            return self._simple_pdf_without_reportlab(title, lines)

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

    def _simple_pdf_without_reportlab(self, title: str, lines: List[str]) -> bytes:
        def escape(text):
            return str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

        text_lines = [escape(title[:90])] + [escape(line[:110]) for line in lines]
        stream_lines = ["BT", "/F1 14 Tf", "50 790 Td", f"({text_lines[0]}) Tj"]
        stream_lines.extend(["/F1 10 Tf", "0 -24 Td"])
        for line in text_lines[1:]:
            stream_lines.append(f"({line}) Tj")
            stream_lines.append("0 -14 Td")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("utf-8")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        ]
        pdf = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for index, obj in enumerate(objects, start=1):
            offsets.append(len(pdf))
            pdf.extend(f"{index} 0 obj\n".encode("ascii"))
            pdf.extend(obj)
            pdf.extend(b"\nendobj\n")
        xref = len(pdf)
        pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        pdf.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        pdf.extend(
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
        )
        return bytes(pdf)

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
            f"GST payable by bakery: INR {_format_decimal(payload['gst_collected'])}",
            f"GST paid by e-commerce operators: INR {_format_decimal(payload['ecommerce_operator_gst'])}",
            f"Supplier GST recorded: INR {_format_decimal(payload['input_gst_recorded'])}",
            f"Blocked input GST: INR {_format_decimal(payload['non_creditable_input_gst'])}",
            f"E-commerce TCS to claim: INR {_format_decimal(payload['ecommerce_tcs'])}",
            f"Net GST Liability: INR {_format_decimal(payload['net_gst_liability'])}",
            "",
            "GSTR-1 mapping:",
            (
                "Regular outward supplies: taxable="
                f"{_format_decimal(payload['gstr1_mapping']['regular_outward_supplies']['taxable_value'])} "
                f"gst={_format_decimal(payload['gstr1_mapping']['regular_outward_supplies']['gst'])}"
            ),
            (
                "GSTR-1 Table 14 / Section 9(5): taxable="
                f"{_format_decimal(payload['gstr1_mapping']['ecommerce_operator_9_5']['taxable_value'])} "
                f"gst={_format_decimal(payload['gstr1_mapping']['ecommerce_operator_9_5']['gst'])}"
            ),
            "",
            "Order-wise rows:",
        ]
        for row in payload.get("rows", []):
            lines.append(
                f"{row['order_date']} {row['invoice_number']} {row['order_source']} "
                f"taxable={_format_decimal(row['base_taxable_value'])} "
                f"cgst={_format_decimal(row['cgst_amount'])} "
                f"sgst={_format_decimal(row['sgst_amount'])} "
                f"liability={row['tax_liability_flag']}"
            )
        lines.extend(
            [
                "",
                "Figures are calculated from recorded orders and transactions only.",
            ]
        )
        return self.simple_pdf("GST Summary", lines)
