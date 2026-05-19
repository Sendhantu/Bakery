from datetime import datetime
from decimal import Decimal

from models import PricingRule, ProductionBatch


class PricingService:
    def resolve_product_price(self, product, variant=None, *, at=None):
        price = Decimal(str((variant.price if variant else product.base_price) or 0))
        now = at or datetime.utcnow()
        applied_rule = None

        rules = (
            PricingRule.query.filter_by(is_active=True)
            .order_by(PricingRule.created_at.desc())
            .all()
        )
        for rule in rules:
            if rule.category_id and product.category_id != rule.category_id:
                continue
            if rule.starts_at and now < rule.starts_at:
                continue
            if rule.ends_at and now > rule.ends_at:
                continue
            if rule.applies_after_hour is not None and now.hour < int(rule.applies_after_hour):
                continue
            if rule.rule_type == "aging_discount" and not self._batch_is_old_enough(
                product.id, rule.max_batch_age_hours
            ):
                continue

            discount = Decimal(str(rule.percent_discount or 0)) / Decimal("100")
            if discount <= 0:
                continue
            applied_rule = rule
            price = (price * (Decimal("1") - discount)).quantize(Decimal("0.01"))
            break

        return {
            "price": price,
            "rule": applied_rule,
            "original_price": Decimal(str((variant.price if variant else product.base_price) or 0)),
        }

    def _batch_is_old_enough(self, product_id, max_batch_age_hours):
        if not max_batch_age_hours:
            return True
        batch = (
            ProductionBatch.query.filter_by(product_id=product_id)
            .order_by(ProductionBatch.produced_at.desc())
            .first()
        )
        if batch is None or batch.produced_at is None:
            return False
        age_hours = (datetime.utcnow() - batch.produced_at).total_seconds() / 3600
        return age_hours >= int(max_batch_age_hours)
