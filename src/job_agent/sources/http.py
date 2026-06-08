"""Production HTTP transport (stdlib urllib + certifi for a reliable trust store).

stdlib ``urllib`` validates TLS against OpenSSL's default CA paths, which are often
missing/empty (e.g. python.org Python on macOS → ``CERTIFICATE_VERIFY_FAILED:
unable to get local issuer certificate``). We verify against the ``certifi`` bundle
instead, so HTTPS works on any machine without disabling verification. The network
only happens when these functions are actually called — tests inject fixtures.
"""

from __future__ import annotations

import ssl
from collections.abc import Mapping

_ssl_context: ssl.SSLContext | None = None


def _context() -> ssl.SSLContext:
    """A verifying SSL context backed by certifi's CA bundle (falls back to default)."""
    global _ssl_context
    if _ssl_context is None:
        try:
            import certifi

            _ssl_context = ssl.create_default_context(cafile=certifi.where())
        except Exception:  # noqa: BLE001 - certifi absent → use the system default
            _ssl_context = ssl.create_default_context()
    return _ssl_context


class SourceHTTPError(Exception):
    """Non-2xx response from a source. ``status`` lets the UI switch deterministically."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"source HTTP {status}: {body[:200]}")


def urllib_http(url: str, headers: Mapping[str, str] | None = None) -> str:
    """GET ``url`` and return the body text. Raises ``SourceHTTPError`` on non-2xx."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=12, context=_context()) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise SourceHTTPError(exc.code, body) from exc


def urllib_post(url: str, body: dict, headers: Mapping[str, str] | None = None) -> str:
    """POST a JSON body and return the response text. Raises ``SourceHTTPError`` on non-2xx."""
    import json
    import urllib.error
    import urllib.request

    hdrs = {"Content-Type": "application/json", "Accept": "application/json", **dict(headers or {})}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=12, context=_context()) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        msg = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise SourceHTTPError(exc.code, msg) from exc
