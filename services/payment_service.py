from models import Coupon


class PaymentService:
    def validate_coupon(self, code, subtotal):
        coupon_code = (code or "").strip().upper()
        coupon = Coupon.query.filter_by(code=coupon_code).first()
        if not coupon or not coupon.is_valid():
            return {"valid": False, "message": "Invalid or expired coupon."}

        subtotal_value = float(subtotal or 0)
        if subtotal_value < float(coupon.min_order_value):
            return {
                "valid": False,
                "message": f"Minimum order ₹{coupon.min_order_value} required.",
            }

        if coupon.discount_type == "percentage":
            discount = round(subtotal_value * float(coupon.discount_value) / 100, 2)
        else:
            discount = float(coupon.discount_value)

        return {
            "valid": True,
            "discount": discount,
            "message": f"Coupon applied! You save ₹{discount:.0f}",
        }
