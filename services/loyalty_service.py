import json
from datetime import datetime, timedelta

from models import CashbackWalletEntry, LoyaltyLedger, ReferralReward, User, db


class LoyaltyService:
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
        now = now or datetime.utcnow()
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
            db.session.add(
                LoyaltyLedger(user_id=user.id, points=50, reason=key)
            )
            rewarded.append(user.id)
        if rewarded:
            db.session.commit()
        return rewarded
