"""The client's IP address, shared by the brute-force lockout (django-axes), the rate limits
(users/throttling.py, movies/throttling.py), allauth's rate limits and the security log.

On Render a request goes client -> Cloudflare -> Render's proxy -> Django, so REMOTE_ADDR is the
proxy, the same for every user. X-Forwarded-For can't be used either: Render only appends to it,
so its first entry is whatever the client sent. Cloudflare sets CF-Connecting-IP itself, so that
header (settings.CLIENT_IP_HEADER) is the client. Without it (local dev, or if Render stops using
Cloudflare) this falls back to REMOTE_ADDR: limits then become per proxy, i.e. stricter, never
bypassable by a spoofed header.
"""

import ipaddress

from django.conf import settings
from django.http import HttpRequest


def _meta_key(header: str) -> str:
    return "HTTP_" + header.upper().replace("-", "_")


def client_ip(request: HttpRequest) -> str | None:
    meta = getattr(request, "META", {})
    header = getattr(settings, "CLIENT_IP_HEADER", "")
    if header:
        value = (meta.get(_meta_key(header)) or "").strip()
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            pass  # missing or not an IP: ignore it
    return meta.get("REMOTE_ADDR") or None
