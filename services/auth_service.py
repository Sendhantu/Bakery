from datetime import datetime

from models import LoginHistory, db
from repositories import UserRepository
from utils.security import admin_2fa_provision, get_login_lockout_window


class AuthService:
    def __init__(self, user_repository=None):
        self.user_repository = user_repository or UserRepository()

    def get_user_by_email(self, email):
        return self.user_repository.get_by_email(email)

    def record_login(self, user, request, status="success"):
        user_agent = request.headers.get("User-Agent", "")[:200]
        ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)
        db.session.add(
            LoginHistory(
                user_id=user.id,
                ip_address=ip_address,
                device=user_agent,
                status=status,
            )
        )

    def get_recent_failed_attempts(self, user, config):
        window_start = datetime.utcnow() - get_login_lockout_window(config)
        last_success = self.user_repository.last_success(user.id, window_start)
        failures = self.user_repository.recent_failures(user.id, window_start)
        if last_success:
            failures = failures.filter(LoginHistory.login_time > last_success.login_time)
        return failures

    def is_user_locked_out(self, user, config):
        try:
            max_attempts = int(config.get("LOGIN_MAX_ATTEMPTS", 5))
        except (TypeError, ValueError):
            max_attempts = 5
        if max_attempts <= 0:
            return False, 0

        failures = self.get_recent_failed_attempts(user, config)
        last_failed = failures.order_by(LoginHistory.login_time.desc()).first()
        failure_count = failures.count()
        if failure_count < max_attempts or last_failed is None:
            return False, 0

        unlock_at = last_failed.login_time + get_login_lockout_window(config)
        if unlock_at <= datetime.utcnow():
            return False, 0

        remaining_seconds = int((unlock_at - datetime.utcnow()).total_seconds())
        remaining_minutes = max(1, (remaining_seconds + 59) // 60)
        return True, remaining_minutes

    def admin_2fa_hooks(self, config):
        return admin_2fa_provision(config)
