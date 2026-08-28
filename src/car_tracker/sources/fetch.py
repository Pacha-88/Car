"""Fetching for sites that inspect *how* you connect, not just what you send.

Két of this project's sources (Tesla.com behind Akamai, Használtautó.hu
behind Cloudflare) reject plain Python HTTP clients even from an ordinary
home connection, while a browser on that same connection is served
normally. Headers alone don't explain it — sources/http.py sends a
complete, self-consistent browser header set and still gets 403 from both.

What actually differs is the TLS handshake. Python's `ssl` module produces
a distinctive fingerprint (JA3/JA4), and these systems score it. Measured
2026-08-28 against Használtautó.hu, varying nothing but the TLS profile:

    plain httpx (Python ssl)      403, "Sorry, you have been blocked"
    curl_cffi impersonate=safari  403, "Just a moment..." (JS challenge)
    curl_cffi impersonate=chrome  (untestable from that sandbox - its
                                   egress proxy resets modern TLS profiles)

A browser-like handshake demotes a hard WAF block to a solvable challenge,
which is exactly the signature of fingerprint-based scoring rather than
IP-based banning.

So this module escalates only as far as it must:

  1. `curl_cffi` impersonating a current Chrome — real Chrome TLS, no
     browser to install. Enough whenever the site's verdict turns on the
     handshake alone.
  2. A real headless Chromium via Playwright — same handshake plus a real
     JS engine, so a challenge page gets solved rather than returned.
     Optional dependency (`car-tracker[browser]`): step 1 is a few MB,
     a browser is a few hundred.

Both are ordinary requests at ordinary volume; the escalation is about
being *recognised* as a normal browser, which this project is, not about
issuing more traffic than a person would.
"""

from __future__ import annotations

import re

# One current Chrome build. curl_cffi ships matching TLS profiles; keep
# this in step with sources/http.py's USER_AGENT so the handshake and the
# headers describe the same browser.
IMPERSONATE_PROFILE = "chrome"

# Cloudflare's interstitial ("Just a moment...", "Checking your browser")
# and its hard block, plus Akamai's. A challenge means step 1 got close
# and step 2 should finish the job; a block usually means it didn't.
_CHALLENGE_MARKERS = ("just a moment", "checking your browser", "cf-challenge", "challenge-platform")
_BLOCK_MARKERS = ("you have been blocked", "access denied", "attention required")


class FetchError(RuntimeError):
    """A page could not be retrieved by any available strategy."""


def looks_unusable(status_code: int, body: str) -> bool:
    """True when a response is a bot wall rather than the page we asked for."""
    if status_code >= 400:
        return True
    lowered = body[:4000].lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS + _BLOCK_MARKERS)


def describe(status_code: int, body: str) -> str:
    """Short, honest label for what came back - used in error messages."""
    lowered = body[:4000].lower()
    if any(m in lowered for m in _CHALLENGE_MARKERS):
        return f"HTTP {status_code}, JS challenge page"
    if any(m in lowered for m in _BLOCK_MARKERS):
        return f"HTTP {status_code}, hard block page"
    return f"HTTP {status_code}, {len(body)} bytes"


def _fetch_with_impersonation(url: str, *, accept_language: str, timeout: float) -> tuple[int, str] | None:
    """Step 1. None when curl_cffi isn't installed or the transport failed."""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None
    try:
        response = cffi_requests.get(
            url,
            impersonate=IMPERSONATE_PROFILE,
            headers={"Accept-Language": accept_language},
            timeout=timeout,
        )
    except Exception:
        # A TLS/transport failure here is not fatal: step 2 may still work.
        return None
    return response.status_code, response.text


def _fetch_with_browser(url: str, *, accept_language: str, timeout: float) -> tuple[int, str]:
    """Step 2. Raises FetchError with an actionable message if unavailable."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise FetchError(
            f"{url} needs a real browser, which isn't installed. Install the browser extra:\n"
            '  uv tool install --from "car-tracker[browser] @ git+https://github.com/Pacha-88/Car" car-tracker\n'
            "  playwright install chromium"
        ) from exc

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            # Playwright is installed but its browser binary isn't - the
            # normal state right after `pip install playwright`. Its own
            # error is a wall of stack trace; this runs on the owner's
            # laptop, so say the one command that fixes it.
            raise FetchError(
                f"{url} needs a real browser. Playwright is installed but its browser isn't:\n"
                "  playwright install chromium\n"
                f"(original error: {str(exc).splitlines()[0]})"
            ) from exc
        try:
            context = browser.new_context(locale=accept_language.split(",")[0])
            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            status = response.status if response else 0
            body = page.content()
            if looks_unusable(status, body):
                # A challenge resolves itself a beat after load; give it one.
                page.wait_for_timeout(6000)
                body = page.content()
                status = 200 if not looks_unusable(200, body) else status
            return status, body
        finally:
            browser.close()


def fetch_html(url: str, *, accept_language: str = "en-US,en;q=0.9", timeout: float = 30.0) -> str:
    """Return `url`'s HTML, escalating only as far as the site requires."""
    attempt = _fetch_with_impersonation(url, accept_language=accept_language, timeout=timeout)
    if attempt is not None:
        status, body = attempt
        if not looks_unusable(status, body):
            return body
        first_failure = describe(status, body)
    else:
        first_failure = "curl_cffi unavailable"

    status, body = _fetch_with_browser(url, accept_language=accept_language, timeout=timeout)
    if looks_unusable(status, body):
        raise FetchError(f"{url}: blocked at both stages (impersonation: {first_failure}; browser: {describe(status, body)})")
    return body


def fetch_json(url: str, *, accept_language: str = "en-US,en;q=0.9", timeout: float = 30.0) -> str:
    """Same escalation for a JSON endpoint (Tesla's inventory API).

    Returns the raw body; callers parse it. A browser navigating straight
    to a JSON URL renders it inside a <pre>, so that wrapper is stripped.
    """
    body = fetch_html(url, accept_language=accept_language, timeout=timeout)
    stripped = body.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    match = re.search(r"<pre[^>]*>(.*?)</pre>", body, re.S)
    if match:
        return re.sub(r"<[^>]+>", "", match.group(1))
    return body
