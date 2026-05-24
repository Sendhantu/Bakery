import os

# ─── Server Socket ──────────────────────────────────────────────
# Render injects $PORT dynamically; fallback to 5000 for local dev
port = os.environ.get("PORT", "5000")
bind = f"0.0.0.0:{port}"

# ─── Worker Processes ───────────────────────────────────────────
# gevent is required for Flask-SocketIO + gevent-websocket
worker_class = "gevent"
workers = 1               # Keep at 1 for free tier (512MB RAM)
worker_connections = 1000
timeout = 120
keepalive = 5

# ─── Logging ────────────────────────────────────────────────────
accesslog = "-"           # stdout
errorlog = "-"            # stderr
loglevel = "info"

# ─── Process Naming ─────────────────────────────────────────────
proc_name = "bakery"

# ─── Security ───────────────────────────────────────────────────
forwarded_allow_ips = "*"  # Trust Render's proxy
secure_scheme_headers = {"X-Forwarded-Proto": "https"}
