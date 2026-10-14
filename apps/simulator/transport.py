"""Loopback-only HTTP sender, bounded timeout, no redirects and no retries."""

import json
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError, URLError
from apps.monitoring.contracts import valid_token


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ReportError(RuntimeError):
    pass


class HttpReporter:
    def __init__(self, server_url, token, *, timeout_s=3):
        try:
            parts = urlsplit(server_url)
            port = parts.port
        except ValueError:
            raise ValueError("INVALID_LOCAL_SERVER") from None
        if (parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost") or
                parts.username is not None or parts.password is not None or parts.query or parts.fragment or
                parts.path not in ("", "/") or port is None or not 1 <= port <= 65535):
            raise ValueError("INVALID_LOCAL_SERVER")
        if not valid_token(token) or type(timeout_s) not in (int, float) or not 0 < timeout_s <= 10:
            raise ValueError("INVALID_REPORT_ACCESS_CONFIG")
        self._url = server_url.rstrip("/")+"/api/ingestion/batches"
        self._token = token
        self._timeout_s = timeout_s
        self._opener = build_opener(ProxyHandler({}), NoRedirect())

    def send(self, batch):
        data = json.dumps(batch, allow_nan=False).encode()
        request = Request(self._url, data=data, method="POST", headers={
            "Content-Type": "application/json", "X-Simulator-Token": self._token})
        try:
            with self._opener.open(request, timeout=self._timeout_s) as response:
                # A bounded response; never expose response bodies or transport exceptions.
                raw = response.read(2049)
                if len(raw) > 2048:
                    raise ReportError("REPORT_RESPONSE_INVALID")
                result = json.loads(raw)
                if result.get("status") not in ("accepted", "duplicate", "out_of_order"):
                    raise ReportError("REPORT_RESPONSE_INVALID")
                return result
        except HTTPError as error:
            code = error.code
            error.close()
            raise ReportError("REPORT_HTTP_"+str(code)) from None
        except (URLError, TimeoutError, OSError):
            raise ReportError("REPORT_TRANSPORT_ERROR") from None
        except (ValueError, TypeError, AttributeError):
            raise ReportError("REPORT_RESPONSE_INVALID") from None

    def close(self):
        # urllib opens one short-lived connection per send; every response closes in send.
        self._token = ""
