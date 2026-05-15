from models import LoginHistory, User


class UserRepository:
    def get_by_email(self, email):
        return User.query.filter_by(email=(email or "").strip().lower()).first()

    def recent_failures(self, user_id, window_start):
        return LoginHistory.query.filter(
            LoginHistory.user_id == user_id,
            LoginHistory.login_time >= window_start,
            LoginHistory.status.in_(["failed", "inactive"]),
        )

    def last_success(self, user_id, window_start):
        return (
            LoginHistory.query.filter_by(user_id=user_id, status="success")
            .filter(LoginHistory.login_time >= window_start)
            .order_by(LoginHistory.login_time.desc())
            .first()
        )

    def active_admins(self):
        return User.query.filter_by(role="admin", is_active=True).all()
