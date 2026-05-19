import io
from datetime import datetime
from decimal import Decimal

from models import Order, OrderItem, db


class InvoiceService:
    def __init__(self, storage_service):
        self.storage_service = storage_service

    def calculate_gst_breakdown(self, order):
        taxable = Decimal(str(order.subtotal or 0)) - Decimal(str(order.discount or 0)) - Decimal(
            str(order.loyalty_discount or 0)
        )
        rate = Decimal(str(order.gst_rate or 5))
        gst_amount = (taxable * rate / Decimal("100")).quantize(Decimal("0.01"))
        return {
            "taxable_amount": float(taxable),
            "gst_rate": float(rate),
            "cgst": float((gst_amount / 2).quantize(Decimal("0.01"))),
            "sgst": float((gst_amount / 2).quantize(Decimal("0.01"))),
            "gst_amount": float(gst_amount),
        }

    def generate_pdf_bytes(self, order):
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        items = order.items.all()
        breakdown = self.calculate_gst_breakdown(order)
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        y = height - 50
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(50, y, f"Tax Invoice — {order.order_number}")
        y -= 24
        pdf.setFont("Helvetica", 10)
        pdf.drawString(50, y, f"Date: {order.placed_at.strftime('%d-%m-%Y %H:%M') if order.placed_at else datetime.utcnow()}")
        y -= 16
        pdf.drawString(50, y, f"Customer: {order.customer.name if order.customer else 'Walk-in'}")
        y -= 24
        for item in items:
            line = f"{item.product_name} x{item.quantity} @ {item.unit_price} = {item.subtotal}"
            pdf.drawString(50, y, line[:90])
            y -= 14
        y -= 10
        pdf.drawString(50, y, f"Taxable: INR {breakdown['taxable_amount']:.2f}")
        y -= 14
        pdf.drawString(50, y, f"CGST ({breakdown['gst_rate']/2}%): INR {breakdown['cgst']:.2f}")
        y -= 14
        pdf.drawString(50, y, f"SGST ({breakdown['gst_rate']/2}%): INR {breakdown['sgst']:.2f}")
        y -= 14
        pdf.drawString(50, y, f"Grand Total: INR {float(order.total or 0):.2f}")
        pdf.showPage()
        pdf.save()
        buffer.seek(0)
        return buffer.getvalue()

    def generate_and_store(self, order_id):
        order = db.session.get(Order, order_id)
        if order is None:
            return None
        breakdown = self.calculate_gst_breakdown(order)
        order.gst_amount = breakdown["gst_amount"]
        if not order.invoice_number:
            order.invoice_number = f"INV-{order.order_number}"
        pdf_bytes = self.generate_pdf_bytes(order)
        upload = self.storage_service.upload_bytes(
            pdf_bytes,
            public_id=f"invoices/{order.invoice_number}",
            resource_type="raw",
            format_ext="pdf",
        )
        order.invoice_url = upload.get("url")
        db.session.commit()
        return order.invoice_url
