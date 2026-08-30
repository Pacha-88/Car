"""The escalation ladder in sources/fetch.py.

The network behaviour it exists for can't be exercised from CI (that's the
whole point of the module), but the decision logic can be, and that's
where the bugs would live: escalating when it shouldn't costs a browser
launch on every page; not escalating when it should silently parses a
Cloudflare interstitial as if it were listings.
"""

from __future__ import annotations

import json

import pytest

from car_tracker.sources import fetch
from car_tracker.sources.fetch import FetchError, describe, fetch_html, fetch_json, looks_unusable

LISTINGS_HTML = '<html><body><div class="row talalati-sor">...</div></body></html>'
CHALLENGE_HTML = "<html><head><title>Just a moment...</title></head><body>checking your browser</body></html>"
BLOCK_HTML = "<html><body>Sorry, you have been blocked</body></html>"


@pytest.fixture(autouse=True)
def _no_browser_leaks_between_tests():
    """The browser is now shared for a whole run, so a context created by one
    test must not be inherited by the next."""
    fetch.close_browser()
    yield
    fetch.close_browser()


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


def test_json_from_the_browser_gets_its_entities_back(monkeypatch):
    """The browser serializes the JSON as HTML text on the way into that
    <pre>, so every & < > in the data arrives as an entity. Stripping only
    the tags shipped `Wheels &amp; Tires` into the database as a trim name -
    valid JSON, silently wrong data."""
    monkeypatch.setattr(fetch, "_fetch_with_impersonation", lambda url, **kw: None)
    # What Chrome actually serializes: & < > become entities, while the
    # JSON's own \" escape passes through a text node untouched.
    monkeypatch.setattr(
        fetch,
        "_fetch_with_browser",
        lambda url, **kw: (200, '<html><body><pre>{"trim": "Wheels &amp; Tires, 19\\" &lt;OEM&gt;"}</pre></body></html>'),
    )
    unwrapped = fetch_json("https://example.com")
    assert unwrapped == '{"trim": "Wheels & Tires, 19\\" <OEM>"}'
    assert json.loads(unwrapped) == {"trim": 'Wheels & Tires, 19" <OEM>'}


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
        def launch_persistent_context(self, **kwargs):
            raise RuntimeError("BrowserType.launch: Executable doesn't exist at /somewhere")

    class _FakePlaywrightInstance:
        chromium = _FakeChromium()

        def stop(self):
            return None

    class _FakeSyncPlaywright:
        """Matches the .start()/.stop() shape the shared session uses."""

        def start(self):
            return _FakePlaywrightInstance()

    monkeypatch.setattr(fetch, "_fetch_with_impersonation", lambda url, **kw: (403, CHALLENGE_HTML))

    import sys
    import types

    fake_module = types.ModuleType("playwright.sync_api")
    fake_module.sync_playwright = _FakeSyncPlaywright
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    sys.modules["playwright"].sync_api = fake_module

    with pytest.raises(FetchError) as exc:
        fetch_html("https://example.com")
    message = str(exc.value)
    assert "playwright install" in message
    assert "Executable doesn't exist" in message  # the real cause is preserved, not swallowed


# --- rate-limit backoff (added after Tesla's API returned 429 on a burst) ---

def test_impersonation_retries_a_429_then_succeeds(monkeypatch):
    """429 is 'slow down', not 'go away' - a backed-off retry should get the
    real page rather than wasting a browser launch on a rate limit."""
    calls = {"n": 0}

    class _Resp:
        def __init__(self, status, text):
            self.status_code = status
            self.text = text

    def _fake_get(url, **kw):
        calls["n"] += 1
        return _Resp(429, "rate limited") if calls["n"] == 1 else _Resp(200, LISTINGS_HTML)

    import types

    fake_cffi = types.ModuleType("curl_cffi")
    fake_cffi.requests = types.SimpleNamespace(get=_fake_get)
    monkeypatch.setitem(__import__("sys").modules, "curl_cffi", fake_cffi)
    monkeypatch.setattr(fetch.time, "sleep", lambda _s: None)  # don't actually wait

    result = fetch._fetch_with_impersonation("https://example.com", accept_language="en", timeout=5)
    assert result == (200, LISTINGS_HTML)
    assert calls["n"] == 2  # retried exactly once past the 429


def test_impersonation_gives_up_after_persistent_429(monkeypatch):
    """A site that just keeps rate-limiting should return the last 429 so
    the caller escalates, not loop forever."""
    class _Resp:
        status_code = 429
        text = "rate limited"

    import types

    fake_cffi = types.ModuleType("curl_cffi")
    fake_cffi.requests = types.SimpleNamespace(get=lambda url, **kw: _Resp())
    monkeypatch.setitem(__import__("sys").modules, "curl_cffi", fake_cffi)
    monkeypatch.setattr(fetch.time, "sleep", lambda _s: None)

    status, _ = fetch._fetch_with_impersonation("https://example.com", accept_language="en", timeout=5)
    assert status == 429


def test_browser_launch_prefers_real_chrome_then_falls_back(monkeypatch):
    """channel='chrome' (real Chrome, new-headless) is tried first; if it's
    not installed, the bundled Chromium (channel=None) is the fallback."""
    tried = []

    class _FakeChromium:
        def launch_persistent_context(self, **kwargs):
            tried.append(kwargs.get("channel"))
            if kwargs.get("channel") == "chrome":
                raise RuntimeError("Chromium distribution 'chrome' is not found")
            return object()  # bundled Chromium launches fine

    context = fetch._launch_browser(
        __import__("types").SimpleNamespace(chromium=_FakeChromium()), headed=False
    )
    assert context is not None
    assert tried == ["chrome", None]  # real Chrome first, then bundled


def test_retry_after_header_overrides_the_fixed_backoff(monkeypatch):
    """A server that says how long to wait knows better than a fixed curve -
    Tesla's API rate-limits bursts and answers 429."""
    waits = []
    calls = {"n": 0}

    class _Resp:
        def __init__(self, status, headers):
            self.status_code = status
            self.text = "rate limited"
            self.headers = headers

    def _fake_get(url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(429, {"Retry-After": "20"})
        return _Resp(200, {})

    import types

    fake_cffi = types.ModuleType("curl_cffi")
    fake_cffi.requests = types.SimpleNamespace(get=_fake_get)
    monkeypatch.setitem(__import__("sys").modules, "curl_cffi", fake_cffi)
    monkeypatch.setattr(fetch.time, "sleep", lambda s: waits.append(s))

    fetch._fetch_with_impersonation("https://example.com", accept_language="en", timeout=5)
    assert waits == [20], f"should wait the server's 20s, not the default curve; got {waits}"


def test_absurd_retry_after_is_capped(monkeypatch):
    """A server asking for an hour must not stall the whole daily run."""
    waits = []

    class _Resp:
        status_code = 429
        text = "rate limited"
        headers = {"Retry-After": "86400"}

    import types

    fake_cffi = types.ModuleType("curl_cffi")
    fake_cffi.requests = types.SimpleNamespace(get=lambda url, **kw: _Resp())
    monkeypatch.setitem(__import__("sys").modules, "curl_cffi", fake_cffi)
    monkeypatch.setattr(fetch.time, "sleep", lambda s: waits.append(s))

    fetch._fetch_with_impersonation("https://example.com", accept_language="en", timeout=5)
    assert waits and max(waits) <= fetch._MAX_RETRY_AFTER_SECONDS


def test_browser_is_reused_across_fetches(monkeypatch):
    """One run fetches dozens of URLs. Launching a browser per URL was slow
    and, in headed mode, opened and closed a window for every page."""
    launches = {"n": 0}
    navigations = {"n": 0}

    class _FakePage:
        def __init__(self):
            self.closed = False

        def goto(self, url, **kw):
            navigations["n"] += 1
            return type("R", (), {"status": 200})()

        def content(self):
            return LISTINGS_HTML

        def is_closed(self):
            return self.closed

        def close(self):
            self.closed = True

    class _FakeContext:
        """Behaves like a real persistent context: it comes up with one tab
        already open, and new_page() adds to that list."""

        def __init__(self):
            self.pages = [_FakePage()]

        def add_init_script(self, _s):
            return None

        def new_page(self):
            page = _FakePage()
            self.pages.append(page)
            return page

        def close(self):
            return None

    def _fake_launch(playwright, *, headed):
        launches["n"] += 1
        return _FakeContext()

    import sys
    import types

    fake_module = types.ModuleType("playwright.sync_api")
    fake_module.sync_playwright = lambda: type("S", (), {"start": lambda self: object(), "stop": lambda self: None})()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    sys.modules["playwright"].sync_api = fake_module
    monkeypatch.setattr(fetch, "_launch_browser", _fake_launch)

    for _ in range(3):
        status, body = fetch._fetch_with_browser("https://example.com", accept_language="en", timeout=5)
        assert status == 200

    assert launches["n"] == 1, "the browser should start once, not once per fetch"
    assert navigations["n"] == 3, "every fetch still actually navigates"
    context = fetch._SESSION["context"]
    assert len(context.pages) == 1, (
        "one tab, navigated from URL to URL. Opening a tab per fetch left the window's own "
        "blank first tab sitting there unexplained, and closing it emptied the window."
    )
    assert not context.pages[0].closed, "closing our only tab is what made the window vanish mid-run"


def _mark_cdp(context):
    """What _connect_to_your_own_chrome does for real: record that this
    context belongs to someone else's browser."""
    fetch._SESSION["cdp_browser"] = type("B", (), {"close": lambda self: None})()
    return context


def _install_fake_playwright(monkeypatch):
    import sys
    import types

    fake_module = types.ModuleType("playwright.sync_api")
    fake_module.sync_playwright = lambda: type("S", (), {"start": lambda self: object(), "stop": lambda self: None})()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_module)
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    sys.modules["playwright"].sync_api = fake_module

def test_an_attached_browser_gets_its_own_tab_and_keeps_the_persons_tabs(monkeypatch):
    """Rung 4 drives the person's real Chrome. Their open tabs are theirs:
    navigating one away from what they were reading, or closing it, would be
    the tool reaching into their session rather than borrowing it."""
    theirs = []

    class _FakePage:
        def __init__(self, mine):
            self.mine = mine
            self.closed = False
            self.url = None

        def goto(self, url, **kw):
            self.url = url
            return type("R", (), {"status": 200})()

        def content(self):
            return LISTINGS_HTML

        def is_closed(self):
            return self.closed

        def close(self):
            self.closed = True

    class _FakeContext:
        def __init__(self):
            self.pages = theirs

        def add_init_script(self, _s):
            return None

        def new_page(self):
            page = _FakePage(mine=True)
            self.pages.append(page)
            return page

        def close(self):
            raise AssertionError("must never close a context we only borrowed")

    their_tab = _FakePage(mine=False)
    theirs.append(their_tab)

    monkeypatch.setattr(fetch, "_connect_to_your_own_chrome", lambda _pw, _endpoint: _mark_cdp(_FakeContext()))
    _install_fake_playwright(monkeypatch)
    monkeypatch.setenv(fetch._CDP_ENV_VAR, "http://localhost:9222")

    status, _ = fetch._fetch_with_browser("https://example.com", accept_language="en", timeout=5)

    assert status == 200
    assert their_tab.url is None, "the person's own tab must not be navigated away"
    assert their_tab.closed is False
    ours = [p for p in theirs if p.mine]
    assert len(ours) == 1 and ours[0].closed, "our tab is opened for the fetch and cleaned up after"


def test_closing_the_window_skips_one_site_not_the_rest_of_the_run(monkeypatch):
    """Closing the last tab of a persistent context closes the browser with
    it. Since closing the window is how a person says "skip this stubborn
    one", every later URL used to die on the dead context - one skip took
    the whole run with it."""
    launches = {"n": 0}
    first = {"ctx": None}

    class _Page:
        def __init__(self, ctx, body):
            self.ctx, self.body, self.closed = ctx, body, False

        def goto(self, url, **kw):
            if self.ctx.dead:
                raise RuntimeError("browser has been closed")
            return type("R", (), {"status": 200})()

        def content(self):
            if self.ctx.dead:
                raise RuntimeError("browser has been closed")
            return self.body

        def is_closed(self):
            return self.closed or self.ctx.dead

        def close(self):
            self.closed = True

        def wait_for_timeout(self, _ms):
            if first["ctx"] is self.ctx:  # the person shuts this window
                self.ctx.dead = True
                self.ctx.pages.clear()

    class _Context:
        def __init__(self, body):
            self.dead = False
            self.pages = [_Page(self, body)]

        def add_init_script(self, _s):
            return None

        def new_page(self):
            if self.dead:
                raise RuntimeError("browser has been closed")
            page = _Page(self, LISTINGS_HTML)
            self.pages.append(page)
            return page

        def close(self):
            self.dead = True

    def _launch(_playwright, *, headed):
        launches["n"] += 1
        ctx = _Context(CHALLENGE_HTML if launches["n"] == 1 else LISTINGS_HTML)
        if launches["n"] == 1:
            first["ctx"] = ctx
        return ctx

    _install_fake_playwright(monkeypatch)
    monkeypatch.setattr(fetch, "_launch_browser", _launch)
    monkeypatch.setattr(fetch, "_HEADED_SOLVE_SECONDS", 1)
    monkeypatch.setenv("CAR_TRACKER_HEADED", "1")
    monkeypatch.delenv(fetch._CDP_ENV_VAR, raising=False)

    fetch._fetch_with_browser("https://a.example/1", accept_language="en", timeout=1)
    status, _ = fetch._fetch_with_browser("https://b.example/2", accept_language="en", timeout=1)

    assert status == 200, "the next site must still be fetchable after a window is closed"
    assert launches["n"] == 2, "a browser that went away is replaced, not reused as a dead handle"


def test_an_attached_chrome_counts_as_someone_watching(monkeypatch):
    """The attached-Chrome path exists so a person can solve a challenge in
    their own window. Reading only CAR_TRACKER_HEADED gave it the twelve
    second "nobody is watching" wait and printed no instructions - the one
    thing that path is for."""
    monkeypatch.delenv("CAR_TRACKER_HEADED", raising=False)
    monkeypatch.setenv(fetch._CDP_ENV_VAR, "http://localhost:9222")
    assert fetch.headed_mode() is True

    monkeypatch.delenv(fetch._CDP_ENV_VAR, raising=False)
    assert fetch.headed_mode() is False


def test_a_borrowed_browser_is_not_patched_behind_its_owners_back(monkeypatch):
    """The stealth script hides navigator.webdriver on a browser we drive.
    On the person's own Chrome it would apply to pages they open for
    themselves — and there is nothing to hide there anyway, since nothing
    automated it."""
    scripts = []

    class _Context:
        pages: list = []

        def add_init_script(self, s):
            scripts.append(s)

        def new_page(self):
            raise AssertionError("not reached")

        def close(self):
            return None

    _install_fake_playwright(monkeypatch)
    monkeypatch.setattr(fetch, "_connect_to_your_own_chrome", lambda _pw, _e: _mark_cdp(_Context()))
    monkeypatch.setenv(fetch._CDP_ENV_VAR, "http://localhost:9222")

    fetch._shared_context(headed=True)
    assert scripts == [], "nothing gets injected into a context we only borrowed"


def test_a_persistent_rate_limit_never_escalates_to_the_browser(monkeypatch):
    """From a real home run: Tesla answered 429 (a limiter, not a block),
    the code escalated to the browser anyway, and Akamai handed the
    headless browser a hard 403 - a bot-defended API URL opened by a
    headless browser is what an attacker looks like, which is how a
    temporary "slow down" gets extended. The browser leaves from the same
    address, so it can never out-wait a limiter: stop, say so, name the
    wait."""
    monkeypatch.setattr(fetch, "_fetch_with_impersonation", lambda url, **kw: (429, '{"error":"too many"}'))
    monkeypatch.setattr(
        fetch,
        "_fetch_with_browser",
        lambda url, **kw: (_ for _ in ()).throw(AssertionError("the browser must not be launched for a 429")),
    )

    with pytest.raises(fetch.FetchError) as caught:
        fetch.fetch_html("https://www.tesla.com/inventory/api/v4/x")

    message = str(caught.value)
    assert "rate limiting" in message
    assert "Wait" in message


def test_a_hard_403_still_escalates_to_the_browser(monkeypatch):
    """The other verdicts keep the ladder: a fingerprint block is exactly
    what the real browser exists to get past."""
    monkeypatch.setattr(fetch, "_fetch_with_impersonation", lambda url, **kw: (403, "Access Denied"))
    monkeypatch.setattr(fetch, "_fetch_with_browser", lambda url, **kw: (200, LISTINGS_HTML))

    assert fetch.fetch_html("https://example.com/x") == LISTINGS_HTML
