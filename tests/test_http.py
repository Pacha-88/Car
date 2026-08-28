"""The shared browser-like HTTP client every source uses.

Why this is worth testing: a header set that contradicts itself is worse
than no header set at all - it's the exact signal bot-management systems
look for. These lock down the internal consistency that made the
difference between Kleinanzeigen returning 403 and 200 (measured
2026-08-28).
"""

from __future__ import annotations

import re

from car_tracker.sources.http import BROWSER_HEADERS, USER_AGENT, build_client


def test_client_sends_the_full_browser_header_set():
    with build_client() as client:
        for header in ("User-Agent", "Accept", "Accept-Language", "sec-ch-ua", "Sec-Fetch-Mode"):
            assert header in client.headers, f"{header} missing - an incomplete set is itself a bot signal"


def test_chrome_version_agrees_between_user_agent_and_client_hints():
    """A real browser never disagrees with itself about its own version."""
    ua_version = re.search(r"Chrome/(\d+)\.", USER_AGENT).group(1)
    assert f'"Google Chrome";v="{ua_version}"' in BROWSER_HEADERS["sec-ch-ua"]
    assert f'"Chromium";v="{ua_version}"' in BROWSER_HEADERS["sec-ch-ua"]


def test_accept_language_override_replaces_rather_than_appends():
    with build_client(accept_language="hu-HU,hu;q=0.9") as client:
        assert client.headers["Accept-Language"] == "hu-HU,hu;q=0.9"


def test_override_does_not_mutate_the_shared_default():
    build_client(accept_language="de-DE,de;q=0.9")
    assert BROWSER_HEADERS["Accept-Language"].startswith("en-US")


def test_client_follows_redirects():
    """Every source hits canonical URLs that redirect (www, trailing slash);
    without this each one silently gets a 301 body instead of listings."""
    with build_client() as client:
        assert client.follow_redirects is True
