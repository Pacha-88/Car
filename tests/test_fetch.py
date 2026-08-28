"""The escalation ladder in sources/fetch.py.

The network behaviour it exists for can't be exercised from CI (that's the
whole point of the module), but the decision logic can be, and that's
where the bugs would live: escalating when it shouldn't costs a browser
launch on every page; not escalating when it should silently parses a
Cloudflare interstitial as if it were listings.
"""

from __future__ import annotations

import pytest

from car_tracker.sources import fetch
from car_tracker.sources.fetch import FetchError, describe, fetch_html, fetch_json, looks_unusable

LISTINGS_HTML = '<html><body><div class="row talalati-sor">...</div></body></html>'
CHALLENGE_HTML = "<html><head><title>Just a moment...</title></head><body>checking your browser</body></html>"
BLOCK_HTML = "<html><body>Sorry, you have been blocked</body></html>"


# --- classification ----------------------------------------------------

def test_a_real_page_is_usable():
    assert looks_unusable(200, LISTINGS_HTML) is False


@pytest.mark.parametrize("body", [CHALLENGE_HTML, BLOCK_HTML])
def test_bot_walls_are_unusable_even_with_a_200(body):
    """Cloudflare serves interstitials with a 200 as often as a 403 - status
    alone would wave them straight through to the parser."""
    assert looks_unusable(200, body) is True


def test_any_error_status_is_unusable():
    assert looks_unusable(403, LISTINGS_HTML) is True


def test_describe_names_the_wall_it_found():
    assert "challenge" in describe(403, CHALLENGE_HTML)
    assert "block" in describe(403, BLOCK_HTML)


# --- escalation --------------------------------------------------------

def test_no_browser_launch_when_impersonation_already_works(monkeypatch):
    monkeypatch.setattr(fetch, "_fetch_with_impersonation", lambda url, **kw: (200, LISTINGS_HTML))
    monkeypatch.setattr(
        fetch, "_fetch_with_browser", lambda url, **kw: pytest.fail("must not escalate on a good response")
    )
    assert fetch_html("https://example.com") == LISTINGS_HTML


def test_escalates_to_the_browser_when_challenged(monkeypatch):
    monkeypatch.setattr(fetch, "_fetch_with_impersonation", lambda url, **kw: (403, CHALLENGE_HTML))
    monkeypatch.setattr(fetch, "_fetch_with_browser", lambda url, **kw: (200, LISTINGS_HTML))
    assert fetch_html("https://example.com") == LISTINGS_HTML


def test_escalates_when_curl_cffi_is_missing(monkeypatch):
    monkeypatch.setattr(fetch, "_fetch_with_impersonation", lambda url, **kw: None)
    monkeypatch.setattr(fetch, "_fetch_with_browser", lambda url, **kw: (200, LISTINGS_HTML))
    assert fetch_html("https://example.com") == LISTINGS_HTML


def test_error_names_both_stages_when_both_are_walled(monkeypatch):
    """A failure has to say what actually happened - "403" alone sent this
    project down an IP-reputation dead end once already."""
    monkeypatch.setattr(fetch, "_fetch_with_impersonation", lambda url, **kw: (403, BLOCK_HTML))
    monkeypatch.setattr(fetch, "_fetch_with_browser", lambda url, **kw: (403, CHALLENGE_HTML))
    with pytest.raises(FetchError) as exc:
        fetch_html("https://example.com")
    message = str(exc.value)
    assert "block" in message and "challenge" in message


# --- JSON unwrapping ---------------------------------------------------

def test_json_passes_through_untouched(monkeypatch):
    monkeypatch.setattr(fetch, "_fetch_with_impersonation", lambda url, **kw: (200, '{"results": [1]}'))
    assert fetch_json("https://example.com") == '{"results": [1]}'


def test_json_is_unwrapped_from_the_browser_pre_tag(monkeypatch):
    """A browser navigated to a JSON URL renders it inside <pre>, so the
    browser stage returns markup where the API returned a document."""
    monkeypatch.setattr(fetch, "_fetch_with_impersonation", lambda url, **kw: None)
    monkeypatch.setattr(
        fetch,
        "_fetch_with_browser",
        lambda url, **kw: (200, '<html><body><pre>{"results": [1]}</pre></body></html>'),
    )
    assert fetch_json("https://example.com") == '{"results": [1]}'


def test_browser_stage_reports_how_to_install_it_when_absent(monkeypatch):
    """The message has to be actionable: this runs on the owner's laptop,
    where nobody can read a stack trace for them."""
    monkeypatch.setattr(fetch, "_fetch_with_impersonation", lambda url, **kw: (403, CHALLENGE_HTML))
    monkeypatch.setitem(__import__("sys").modules, "playwright.sync_api", None)
    with pytest.raises(FetchError) as exc:
        fetch_html("https://example.com")
    assert "playwright install" in str(exc.value)


def test_missing_browser_binary_becomes_an_actionable_message(monkeypatch):
    """Playwright installed but its browser not downloaded is the normal
    state right after install. Its own error is a wall of stack trace; the
    wrapper scripts also grep this message for "playwright install" to
    trigger the automatic download, so the wording is load-bearing."""

    class _FakeChromium:
        def launch(self, **kwargs):
            raise RuntimeError("BrowserType.launch: Executable doesn't exist at /somewhere")

    class _FakePlaywright:
        chromium = _FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(fetch, "_fetch_with_impersonation", lambda url, **kw: (403, CHALLENGE_HTML))
    monkeypatch.setattr(fetch, "sync_playwright", _FakePlaywright, raising=False)

    import sys
    import types

    fake_module = types.ModuleType("playwright.sync_api")
    fake_module.sync_playwright = _FakePlaywright
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)

    with pytest.raises(FetchError) as exc:
        fetch_html("https://example.com")
    message = str(exc.value)
    assert "playwright install" in message
    assert "Executable doesn't exist" in message  # the real cause is preserved, not swallowed
