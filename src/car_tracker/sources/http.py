"""Shared HTTP client setup for every source.

All four sources originally sent `User-Agent: Mozilla/5.0` and nothing
else. That's not a real browser's fingerprint — no `Accept-Language`, no
`Sec-Fetch-*`, no client hints — and sites running bot management treat
the mismatch as a signal. It's also just impolite: a site operator looking
at their logs can't tell what's hitting them or why.

Measured difference (2026-08-28, from this project's dev sandbox):
Kleinanzeigen returned 403 with the bare header and 200 with the set
below. Használtautó.hu and Tesla.com stayed 403 either way — those block
deeper than headers (TLS/IP fingerprinting), see `browser.py`.

`Sec-Fetch-Site: none` is what a browser sends for a URL typed into the
address bar, which is what these fetches are: a single top-level document
request, not a resource pulled in by another page.
"""

from __future__ import annotations

import httpx

# One recent, real Chrome-on-Windows build. Keep the version in the UA and
# in `sec-ch-ua` in sync — a browser never disagrees with itself, and the
# mismatch is exactly what fingerprinting looks for.
_CHROME_VERSION = "141"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/{_CHROME_VERSION}.0.0.0 Safari/537.36"
)

BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8,hu;q=0.7",
    "sec-ch-ua": f'"Chromium";v="{_CHROME_VERSION}", "Not?A_Brand";v="24", "Google Chrome";v="{_CHROME_VERSION}"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

DEFAULT_TIMEOUT_SECONDS = 25.0


def build_client(*, accept_language: str | None = None) -> httpx.Client:
    """An httpx client that presents itself consistently as one browser.

    `accept_language` lets a country-specific source ask for its market's
    language first (Használtautó.hu is a Hungarian site; a browser opening
    it would usually say so), without each source restating the whole
    header set.
    """
    headers = dict(BROWSER_HEADERS)
    if accept_language:
        headers["Accept-Language"] = accept_language
    return httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS, headers=headers, follow_redirects=True)
