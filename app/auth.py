import hmac
from functools import wraps
from flask import current_app, jsonify, redirect, request, session, url_for


def api_auth_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        expected = current_app.config.get("MEMORY_API_TOKEN", "")
        supplied = request.headers.get("Authorization", "")
        valid = expected and supplied.startswith("Bearer ") and hmac.compare_digest(supplied[7:], expected)
        if not valid:
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapped


def admin_auth_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("memory_admin"):
            return redirect(url_for("admin.login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped

