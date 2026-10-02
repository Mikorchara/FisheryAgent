"""Loopback Host/Origin checks and session-bound CSRF for credential mutation."""

import ipaddress
import secrets
import hmac
import re

from flask import jsonify, request, session


def install_local_security(app, allowed_hosts: tuple[str, ...]):
    app.secret_key = secrets.token_bytes(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      SESSION_COOKIE_NAME="fishery_local_session")
    allowed = {host.lower() for host in allowed_hosts}

    def failure(code, status=403):
        return jsonify(status="failed", error_code=code), status

    @app.before_request
    def host_gate():
        # Do not trust Forwarded/X-Forwarded-Host and do not install ProxyFix.
        if request.host.lower() not in allowed:
            return failure("HOST_NOT_ALLOWED")

    def origin_gate(*, required: bool):
        try:
            if not ipaddress.ip_address(request.remote_addr or "").is_loopback:
                return failure("LOCAL_ACCESS_REQUIRED")
        except ValueError:
            return failure("LOCAL_ACCESS_REQUIRED")
        origin = request.headers.get("Origin")
        expected = f"{request.scheme}://{request.host}"
        if (required and not origin) or (origin is not None and origin != expected):
            return failure("ORIGIN_NOT_ALLOWED")
        if request.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            return failure("ORIGIN_NOT_ALLOWED")
        return None

    @app.get("/api/credential-session")
    def credential_session():
        rejected = origin_gate(required=False)
        if rejected is not None:
            return rejected
        if "credential_csrf" not in session:
            session["credential_csrf"] = secrets.token_urlsafe(32)
        return jsonify(csrf_token=session["credential_csrf"])

    def mutation_gate():
        rejected = origin_gate(required=True)
        if rejected is not None:
            return rejected
        expected = session.get("credential_csrf")
        supplied = request.headers.get("X-CSRF-Token", "")
        if (not isinstance(expected, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", supplied)
                or not hmac.compare_digest(expected, supplied)):
            return failure("CSRF_INVALID")
        if not request.is_json:
            return failure("INVALID_REQUEST", 400)
        return None

    @app.errorhandler(413)
    def oversized(_exc):
        return failure("REQUEST_TOO_LARGE", 413)

    @app.after_request
    def security_headers(response):
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        # No Access-Control-Allow-Origin header: this UI never enables CORS.
        return response

    return mutation_gate, origin_gate
