from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    current_app,
)
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, LoginHistory, SavedAddress, limiter
from datetime import datetime, timedelta
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from utils import (
    save_address_for_customer,
    get_saved_addresses_for_user,
    send_email,
    validate_password,
)
import os
from authlib.integrations.flask_client import OAuth

auth_bp = Blueprint("auth", __name__)
oauth = OAuth()
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID", "placeholder_id"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", "placeholder_secret"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def current_portal_role():
    return current_app.config.get("PORTAL_ROLE", "customer")


def portal_url_for_role(role, path=""):
    role = role if role in {"customer", "admin", "delivery"} else "customer"
    base_url = current_app.config.get(f"{role.upper()}_PORTAL_URL", "").rstrip("/")
    if not path:
        return base_url
    if not base_url:
        return path
    return f"{base_url}{path}"


def role_portal(user):
    if user.role == "admin":
        return "admin"
    if user.role == "delivery":
        return "delivery"
    return "customer"


def portal_dashboard_url(role):
    role = role if role in {"customer", "admin", "delivery"} else "customer"
    endpoint = {
        "customer": "customer.home",
        "admin": "admin.dashboard",
        "delivery": "delivery.dashboard",
    }[role]
    path = url_for(endpoint)
    if current_portal_role() == role:
        return path
    return portal_url_for_role(role, path)


def portal_login_url(role):
    role = role if role in {"customer", "admin", "delivery"} else "customer"
    path = url_for("auth.login")
    if current_portal_role() == role:
        return path
    return portal_url_for_role(role, path)


def role_home(user):
    return portal_dashboard_url(role_portal(user))


def password_reset_serializer():
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt="sweetcrumbs-password-reset"
    )


def build_password_reset_link(token):
    return portal_url_for_role("customer", url_for("auth.reset_password", token=token))


def record_login(user, status="success"):
    ua = request.headers.get("User-Agent", "")[:200]
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    db.session.add(
        LoginHistory(user_id=user.id, ip_address=ip, device=ua, status=status)
    )


def get_login_lockout_window():
    minutes = current_app.config.get("LOGIN_LOCKOUT_MINUTES", 15)
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = 15
    return timedelta(minutes=max(1, minutes))


def get_recent_failed_attempts(user):
    window_start = datetime.utcnow() - get_login_lockout_window()
    last_success = (
        LoginHistory.query.filter_by(user_id=user.id, status="success")
        .filter(LoginHistory.login_time >= window_start)
        .order_by(LoginHistory.login_time.desc())
        .first()
    )

    failures = LoginHistory.query.filter(
        LoginHistory.user_id == user.id,
        LoginHistory.login_time >= window_start,
        LoginHistory.status.in_(["failed", "inactive"]),
    )
    if last_success:
        failures = failures.filter(LoginHistory.login_time > last_success.login_time)
    return failures


def is_user_locked_out(user):
    try:
        max_attempts = int(current_app.config.get("LOGIN_MAX_ATTEMPTS", 5))
    except (TypeError, ValueError):
        max_attempts = 5
    if max_attempts <= 0:
        return False, 0

    failures = get_recent_failed_attempts(user)
    last_failed = failures.order_by(LoginHistory.login_time.desc()).first()
    failure_count = failures.count()
    if failure_count < max_attempts or last_failed is None:
        return False, 0

    unlock_at = last_failed.login_time + get_login_lockout_window()
    if unlock_at <= datetime.utcnow():
        return False, 0

    remaining_seconds = int((unlock_at - datetime.utcnow()).total_seconds())
    remaining_minutes = max(1, (remaining_seconds + 59) // 60)
    return True, remaining_minutes


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(role_home(current_user))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter_by(email=email).first()
        password_ok = user.check_password(password) if user else False

        if user:
            locked_out, remaining_minutes = is_user_locked_out(user)
            if locked_out:
                flash(
                    f"Too many failed login attempts. Please try again in about {remaining_minutes} minute(s).",
                    "danger",
                )
                return render_template("auth/login.html")

        if user and password_ok and user.is_active:
            expected_portal = role_portal(user)
            login_user(user, remember=remember)
            from routes.customer import merge_guest_cart_into_user

            merged_items = (
                merge_guest_cart_into_user(user.id) if user.role == "customer" else 0
            )
            record_login(user, "success")
            db.session.commit()
            if current_portal_role() != expected_portal:
                flash(
                    f"Signed in successfully. Redirecting you to the {expected_portal} portal.",
                    "info",
                )
                return redirect(role_home(user))

            flash(f"Welcome back, {user.name}! 🎂", "success")
            if merged_items:
                flash("Your saved cart is ready for checkout.", "info")
            next_page = request.args.get("next")
            return redirect(next_page or role_home(user))
        else:
            if user:
                failure_status = (
                    "inactive" if password_ok and not user.is_active else "failed"
                )
                record_login(user, failure_status)
                db.session.commit()
                if failure_status == "inactive":
                    current_app.logger.warning(
                        "Inactive account login attempt for %s", user.email
                    )

                locked_out, remaining_minutes = is_user_locked_out(user)
                if locked_out:
                    flash(
                        f"Too many failed login attempts. Please try again in about {remaining_minutes} minute(s).",
                        "danger",
                    )
                    return render_template("auth/login.html")
            flash("Invalid email or password.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/login/google")
def login_google():
    redirect_uri = url_for("auth.authorize_google", _external=True)
    return google.authorize_redirect(redirect_uri)


@auth_bp.route("/authorize/google")
def authorize_google():
    token = google.authorize_access_token()
    user_info = token.get("userinfo")
    if not user_info:
        flash("Failed to fetch user info from Google.", "danger")
        return redirect(url_for("auth.login"))

    email = user_info.get("email")
    google_id = user_info.get("sub")
    name = user_info.get("name")

    user = User.query.filter_by(oauth_id=google_id).first()
    if not user:
        user = User.query.filter_by(email=email).first()
        if user:
            user.oauth_id = google_id
            user.oauth_provider = "google"
        else:
            user = User(
                email=email,
                name=name,
                oauth_id=google_id,
                oauth_provider="google",
                role="customer",
            )
            db.session.add(user)

    db.session.commit()
    login_user(user)
    record_login(user, "success")
    db.session.commit()
    flash(f"Logged in successfully via Google, {user.name}!", "success")
    return redirect(url_for("customer.home"))


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def register():
    if current_user.is_authenticated:
        return redirect(role_home(current_user))

    if current_portal_role() != "customer":
        flash(
            "Customer registration is available only on the storefront portal.", "info"
        )
        return redirect(portal_url_for_role("customer", url_for("auth.register")))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        if len(name) < 2:
            errors.append("Name must be at least 2 characters.")
        if User.query.filter_by(email=email).first():
            errors.append("Email already registered.")
        errors.extend(validate_password(password))
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            user = User(name=name, email=email, phone=phone, role="customer")
            user.set_password(password)
            from app import record_development_credential

            db.session.add(user)
            db.session.flush()
            record_development_credential(
                "customer",
                email,
                password,
                label=f"Customer Account ({name})",
                source="registered",
            )
            login_user(user)
            from routes.customer import merge_guest_cart_into_user

            merged_items = merge_guest_cart_into_user(user.id)
            record_login(user)
            db.session.commit()
            flash("Account created! Welcome to Sweet Crumbs! 🎉", "success")
            if merged_items:
                flash("Your saved cart is ready for checkout.", "info")
            next_page = request.args.get("next")
            return redirect(next_page or role_home(user))

    return render_template("auth/register.html")


@auth_bp.route("/logout")
@login_required
def logout():
    target_portal = current_portal_role()
    logout_user()
    flash(f"You have been logged out of the {target_portal} portal.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(role_home(current_user))

    if current_portal_role() != "customer":
        flash(
            "Customer passwords can be reset from the storefront. Admin and delivery credentials are managed in the operations portal.",
            "info",
        )
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email, role="customer").first()

        if user and user.is_active:
            token = password_reset_serializer().dumps(
                {"user_id": user.id, "email": user.email}
            )
            reset_link = build_password_reset_link(token)
            reset_minutes = int(
                current_app.config.get("PASSWORD_RESET_TOKEN_MINUTES", 30)
            )
            html = f"""
            <div style="font-family:sans-serif;max-width:560px;margin:auto">
              <h2 style="color:#6B3F1A">Reset your SweetCrumbs password</h2>
              <p>Hi {user.name},</p>
              <p>Use the button below to choose a new password. This link expires in {reset_minutes} minutes.</p>
              <p style="margin:24px 0">
                <a href="{reset_link}" style="background:#6B3F1A;color:#fff;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600">Reset Password</a>
              </p>
              <p>If you did not request this, you can safely ignore this email.</p>
            </div>
            """
            send_email(
                user.email,
                "Reset your SweetCrumbs password",
                html,
                text_body=reset_link,
            )
            if (
                current_app.debug or current_app.testing
            ) and not current_app.config.get("MAIL_ENABLED"):
                flash(f"Development reset link: {reset_link}", "info")

        flash(
            "If that account exists, password reset instructions have been sent.",
            "info",
        )
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(role_home(current_user))

    if current_portal_role() != "customer":
        return redirect(
            portal_url_for_role("customer", url_for("auth.reset_password", token=token))
        )

    try:
        max_age = int(current_app.config.get("PASSWORD_RESET_TOKEN_MINUTES", 30)) * 60
        payload = password_reset_serializer().loads(token, max_age=max_age)
    except SignatureExpired:
        flash("That reset link has expired. Please request a new one.", "warning")
        return redirect(url_for("auth.forgot_password"))
    except BadSignature:
        flash("That reset link is invalid. Please request a new one.", "danger")
        return redirect(url_for("auth.forgot_password"))

    user = db.session.get(User, int(payload.get("user_id", 0) or 0))
    if user is None or user.email != payload.get("email") or user.role != "customer":
        flash("That reset link is invalid. Please request a new one.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        errors = validate_password(password)
        if password != confirm_password:
            errors.append("Passwords do not match.")
        if errors:
            for err in errors:
                flash(err, "danger")
            return redirect(url_for("auth.reset_password", token=token))

        user.set_password(password)
        from app import record_development_credential

        record_development_credential(
            "customer",
            user.email,
            password,
            label=f"Customer Account ({user.name})",
            source="password_reset",
        )
        db.session.commit()
        flash("Your password has been updated. Please sign in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        current_user.name = request.form.get("name", current_user.name).strip()
        current_user.phone = request.form.get("phone", current_user.phone).strip()
        new_pw = request.form.get("new_password", "")
        if new_pw:
            if not current_user.check_password(
                request.form.get("current_password", "")
            ):
                flash("Current password is incorrect.", "danger")
                return redirect(url_for("auth.profile"))
            password_errors = validate_password(new_pw)
            if password_errors:
                for err in password_errors:
                    flash(err, "danger")
                return redirect(url_for("auth.profile"))
            current_user.set_password(new_pw)
            from app import record_development_credential

            record_development_credential(
                current_user.role,
                current_user.email,
                new_pw,
                label=f"{current_user.role.title()} Account ({current_user.name})",
                source="profile_update",
            )
        db.session.commit()
        flash("Profile updated!", "success")
    history = (
        LoginHistory.query.filter_by(user_id=current_user.id)
        .order_by(LoginHistory.login_time.desc())
        .limit(10)
        .all()
    )
    saved_addresses = []
    if current_user.role == "customer":
        saved_addresses = get_saved_addresses_for_user(current_user.id)
    return render_template(
        "auth/profile.html", history=history, saved_addresses=saved_addresses
    )


@auth_bp.route("/profile/address/add", methods=["POST"])
@login_required
def add_saved_address():
    if current_user.role != "customer":
        flash("Only customers can store delivery addresses.", "danger")
        return redirect(url_for("auth.profile"))

    payload = {
        "label": request.form.get("label", "").strip() or "Saved Address",
        "address_line1": request.form.get("address_line1", "").strip(),
        "address_line2": request.form.get("address_line2", "").strip(),
        "city": request.form.get("city", "").strip(),
        "pincode": request.form.get("pincode", "").strip(),
        "phone": request.form.get("phone", "").strip(),
    }

    if not all(
        payload[field] for field in ("address_line1", "city", "pincode", "phone")
    ):
        flash("Please complete the address form before saving it.", "danger")
        return redirect(url_for("auth.profile"))

    save_address_for_customer(
        user_id=current_user.id,
        payload=payload,
        make_default=bool(request.form.get("is_default")),
    )
    db.session.commit()
    flash("Address saved successfully.", "success")
    return redirect(url_for("auth.profile"))


@auth_bp.route("/profile/address/<int:address_id>/default", methods=["POST"])
@login_required
def set_default_address(address_id):
    address = SavedAddress.query.filter_by(
        id=address_id, user_id=current_user.id
    ).first_or_404()
    SavedAddress.query.filter_by(user_id=current_user.id, is_default=True).update(
        {"is_default": False}
    )
    address.is_default = True
    db.session.commit()
    flash(f"{address.label} is now your default address.", "success")
    return redirect(url_for("auth.profile"))


@auth_bp.route("/profile/address/<int:address_id>/delete", methods=["POST"])
@login_required
def delete_saved_address(address_id):
    address = SavedAddress.query.filter_by(
        id=address_id, user_id=current_user.id
    ).first_or_404()
    was_default = address.is_default
    db.session.delete(address)
    db.session.flush()

    if was_default:
        next_address = (
            SavedAddress.query.filter_by(user_id=current_user.id)
            .order_by(
                SavedAddress.updated_at.desc(),
                SavedAddress.id.desc(),
            )
            .first()
        )
        if next_address:
            next_address.is_default = True

    db.session.commit()
    flash("Saved address removed.", "info")
    return redirect(url_for("auth.profile"))
