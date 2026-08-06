from decimal import Decimal

from models import CashbackWalletEntry, LoyaltyLedger, ReferralReward, User, db
from models.loyalty import calculate_loyalty_redemption


class LoyaltyService:
    def award_order_points(self, order):
        """Award paid delivered order points once per order."""
        if order is None or not order.user_id:
            return 0
        if (order.status or "").upper() != "DELIVERED":
            return 0
        if (order.payment_status or "").upper() != "PAID":
            return 0
        existing = LoyaltyLedger.query.filter_by(
            user_id=order.user_id,
            order_id=order.id,
            reason="order_earned",
        ).first()
        if existing:
            return 0
        return LoyaltyLedger.earn(order.user_id, order.id, order.total or 0)

    def redeem_for_order(self, user_id, order_id, points_requested, subtotal):
        user = db.session.get(User, user_id)
        if user is None:
            raise ValueError("User not found.")
        from bootstrap import get_container

        error = get_container().customer_risk_service.loyalty_error(user)
        if error:
            raise ValueError(error)
        result = calculate_loyalty_redemption(
            points_requested,
            subtotal,
            user.loyalty_points,
        )
        points_applied = int(result["points_applied"] or 0)
        if points_applied <= 0:
            raise ValueError("Those loyalty points cannot be applied to this order.")
        if user.loyalty_points < points_applied:
            raise ValueError("Not enough loyalty points.")
        discount = Decimal(str(result["discount"]))
        LoyaltyLedger.redeem(user_id, order_id, points_applied)
        return {"points_applied": points_applied, "discount": discount}

    def adjust_points(self, user_id, points, reason="manual_adjustment"):
        user = db.session.get(User, user_id)
        if user is None:
            raise ValueError("User not found.")
        points = int(points or 0)
        if points == 0:
            raise ValueError("Point adjustment cannot be zero.")
        if user.loyalty_points + points < 0:
            raise ValueError("Adjustment would make loyalty points negative.")
        return LoyaltyLedger.admin_adjust(
            user_id, points, reason or "manual_adjustment"
        )

    def grant_referral_reward(self, referrer_id, referred_user_id, points=100):
        existing = ReferralReward.query.filter_by(
            referrer_user_id=referrer_id, referred_user_id=referred_user_id
        ).first()
        if existing:
            return existing
        reward = ReferralReward(
            referrer_user_id=referrer_id,
            referred_user_id=referred_user_id,
            reward_points=points,
            status="credited",
        )
        db.session.add(reward)
        db.session.add(
            LoyaltyLedger(
                user_id=referrer_id,
                points=points,
                reason="referral_reward",
            )
        )
        return reward

    def add_cashback(self, user_id, amount, order_id=None, reason="cashback"):
        entry = CashbackWalletEntry(
            user_id=user_id,
            order_id=order_id,
            amount=amount,
            entry_type="credit",
            reason=reason,
        )
        db.session.add(entry)
        return entry

    def process_birthday_rewards(self, now=None):
        now = now or utcnow()
        rewarded = []
        users = User.query.filter(
            User.is_active.is_(True),
            User.role == "customer",
            User.birthday.isnot(None),
        ).all()
        for user in users:
            if not user.birthday:
                continue
            if user.birthday.month != now.month or user.birthday.day != now.day:
                continue
            key = f"birthday:{user.id}:{now.year}"
            if LoyaltyLedger.query.filter(
                LoyaltyLedger.user_id == user.id,
                LoyaltyLedger.reason == key,
            ).first():
                continue
            db.session.add(LoyaltyLedger(user_id=user.id, points=50, reason=key))
            rewarded.append(user.id)
        if rewarded:
            db.session.commit()
        return rewarded
