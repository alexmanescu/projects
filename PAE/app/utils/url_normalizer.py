"""URL canonicalization utilities for deduplication."""

import re
from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl


# Exact parameter names to strip (non-utm tracking params)
_STRIP_PARAMS_EXACT: frozenset[str] = frozenset(
    {
        "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source",
        "_ga", "yclid", "igshid", "msclkid", "twclid", "li_fat_id",
    }
)

# Parameter prefixes to strip (catches utm_*, _hsenc, etc.)
_STRIP_PREFIXES: tuple[str, ...] = ("utm_", "_hs", "ck_", "rb_")


def _should_strip_param(key: str) -> bool:
    """Return True if this query parameter carries no canonical meaning."""
    lower = key.lower()
    if lower in _STRIP_PARAMS_EXACT:
        return True
    return any(lower.startswith(prefix) for prefix in _STRIP_PREFIXES)


def normalize_url(url: str) -> str:
    """Return a canonical form of *url* suitable for deduplication.

    Transformations applied (in order):
    1. Strip leading/trailing whitespace
    2. Upgrade scheme to ``https``
    3. Lower-case the hostname
    4. Remove ``www.`` prefix
    5. Remove default ports (80, 443)
    6. Drop trailing slashes on the path (root path stays as ``/``)
    7. Remove all tracking query parameters (utm_*, fbclid, gclid, …)
    8. Sort remaining query parameters for stable comparison
    9. Strip all URL fragments (``#…``)

    Examples::

        normalize_url("https://example.com/article?utm_source=twitter&id=123")
        # → "https://example.com/article?id=123"

        normalize_url("http://www.Reuters.com/business/?fbclid=abc#top")
        # → "https://reuters.com/business"
    """
    url = url.strip()
    parsed = urlparse(url)

    scheme = "https"

    # Hostname: lowercase + strip www.
    netloc = parsed.hostname or ""
    # Remove default ports
    port = parsed.port
    if port and port not in (80, 443):
        netloc = f"{netloc}:{port}"

    # Path: strip trailing slashes, keep root as "/"
    path = parsed.path.rstrip("/") or "/"

    # Query: drop tracking params, sort the rest
    kept = sorted(
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not _should_strip_param(k)
    )
    query = urlencode(kept)

    # Fragment: always removed
    fragment = ""

    return urlunparse((scheme, netloc, path, "", query, fragment))


def urls_are_equivalent(url_a: str, url_b: str) -> bool:
    """Return True when two URLs normalise to the same canonical form."""
    return normalize_url(url_a) == normalize_url(url_b)
