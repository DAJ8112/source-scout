from __future__ import annotations

from posixpath import normpath
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "source",
    "src",
    "ref",
    "referrer",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


def canonicalize_url(url: str, base: str | None = None, *, keep_query: bool = False) -> str:
    absolute = urljoin(base, url) if base else url
    parts = urlsplit(absolute)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host if not port or (scheme == "https" and port == 443) else f"{host}:{port}"
    path = normpath(parts.path or "/")
    if parts.path.endswith("/") and path != "/":
        path += "/"
    query = ""
    if keep_query:
        safe_pairs = [
            (key, value)
            for key, value in parse_qsl(parts.query)
            if key.lower() not in TRACKING_PARAMS
        ]
        query = urlencode(sorted(safe_pairs))
    return urlunsplit((scheme, netloc, path, query, ""))


def traversal_allowed(candidate: str, source_url: str, allowed_paths: list[str]) -> bool:
    target = urlsplit(candidate)
    source = urlsplit(source_url)
    if target.scheme not in {"http", "https"} or target.hostname != source.hostname:
        return False
    path = normpath(target.path or "/")
    return any(
        path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
        for prefix in allowed_paths
    )
