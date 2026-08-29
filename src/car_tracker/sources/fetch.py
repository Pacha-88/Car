"""Fetching for sites that inspect *how* you connect, not just what you send.

Two of this project's sources (Tesla.com behind Akamai, Használtautó.hu
behind Cloudflare) reject plain Python HTTP clients even from an ordinary
home connection, while a browser on that same connection is served
normally. Headers alone don't explain it — sources/http.py sends a
complete, self-consistent browser header set and still gets 403 from both.

Two things are actually being scored:

  * The TLS handshake. Python's `ssl` module produces a distinctive
    fingerprint (JA3/JA4). Measured 2026-08-28 against Használtautó.hu,
    varying nothing else: plain httpx got the hard "you have been blocked"
    page, while a Chrome/Safari TLS fingerprint got the *solvable* "Just a
    moment..." challenge instead. So a browser-like handshake alone demotes
    a hard block to a challenge.
  * Whether a real browser engine is present, and whether it looks
    automated. A first live run (from the owner's home connection) showed
    the *default* headless browser — Playwright's `chrome-headless-shell` —
    getting the hard block again, worse than the TLS-only attempt: headless
    shells advertise themselves (no real Chrome build id, `navigator.
    webdriver === true`, a headless UA token).

So this module escalates through three rungs, each only if the last was
walled:

  1. `curl_cffi` with a real Chrome TLS fingerprint — no browser to
     install, enough whenever the verdict turns on the handshake alone.
  2. A real browser via Playwright, made to look like an ordinary one:
     the installed Google **Chrome** (not the detectable bundled
     Chromium/headless-shell) in its *new* headless mode when present, the
     automation flag turned off, `navigator.webdriver` unset, and a
     persistent profile so a solved Cloudflare challenge's clearance cookie
     survives to the next page and the next day.
  3. The same browser but *visible* (`CAR_TRACKER_HEADED=1`) — a real
     window a person can watch, and solve a challenge in.
  4. Opt-in, and the end of the line: attach over CDP to the Chrome the
     person already runs (`CAR_TRACKER_CHROME_CDP=http://localhost:9222`).
     Rungs 2 and 3 are an automated browser imitating an ordinary one;
     this one *is* an ordinary one, with its own profile and whatever
     clearance normal browsing has already earned. Reach for it when a
     site hard-blocks the automated browser but serves the same machine's
     everyday Chrome perfectly well.

Everything here is ordinary requests at ordinary volume; the escalation is
about being *recognised* as the normal browser this project is, not about
issuing more traffic than a person would.
"""

from __future__ import annotations

import atexit
import os
import re
import time
from pathlib import Path

# curl_cffi's Chrome TLS profile. Keep in step with sources/http.py's
# USER_AGENT so the handshake and the headers describe the same browser.
IMPERSONATE_PROFILE = "chrome"

# Cloudflare's interstitial ("Just a moment...", "Checking your browser")
# and its hard block, plus Akamai's. A challenge means we got close and a
# real browser engine should finish the job; a block usually means it didn't.
_CHALLENGE_MARKERS = ("just a moment", "checking your browser", "cf-challenge", "challenge-platform")
_BLOCK_MARKERS = ("you have been blocked", "access denied", "attention required")

# 429/503 are "slow down", not "go away" - worth a backed-off retry before
# spending a browser launch on them. Tesla's inventory API answers a burst
# of requests this way, and the first live run showed every Tesla combo
# getting one; the waits below are long because a rate limit measured in
# seconds is not worth failing a daily run over.
_RETRYABLE_STATUS = (429, 503)
_IMPERSONATION_RETRIES = 4
_BACKOFF_SECONDS = (5, 15, 30)  # one per retry after the first attempt
_MAX_RETRY_AFTER_SECONDS = 60  # honour the server's own number, but stay bounded

# How long to keep re-reading a challenge page before giving up. Headless
# has only the automatic clear to wait for; headed has a person who can
# click a checkbox, which is worth waiting properly for.
#
# The headed number is generous because a live run showed why: Cloudflare
# served the hard block first and only produced the "verify you are human"
# widget minutes later. The person solved it - and by then the run had
# given up, so the clearance it earned was never used. Waiting costs
# nothing when nobody is there (the window closing ends the wait early),
# and waiting too little costs the whole run.
_AUTO_SOLVE_SECONDS = 12
_HEADED_SOLVE_SECONDS = 300

# Removes the `navigator.webdriver === true` tell. Belt-and-suspenders with
# the --disable-blink-features launch flag, which unsets it at the source.
_STEALTH_INIT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"

# Rung 4, opt-in: attach to a Chrome the person started themselves, with
# their own profile, extensions, history and - crucially - whatever
# Cloudflare clearance that browser has already earned. Nothing this module
# launches can look as ordinary as a browser that genuinely is ordinary.
#
#   Quit Chrome, then:
#     macOS  open -na "Google Chrome" --args --remote-debugging-port=9222
#     Linux  google-chrome --remote-debugging-port=9222
#   then run with CAR_TRACKER_CHROME_CDP=http://localhost:9222
_CDP_ENV_VAR = "CAR_TRACKER_CHROME_CDP"


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


def _browser_profile_dir() -> Path:
    """A stable per-user directory the browser keeps its profile in, so a
    solved Cloudflare challenge's cf_clearance cookie persists across runs."""
    base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    profile = base / "car-tracker" / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    return profile


def attached_to_own_chrome() -> bool:
    """Whether this run drives a Chrome the person started themselves."""
    return bool(os.environ.get(_CDP_ENV_VAR, "").strip())


def headed_mode() -> bool:
    """Whether there is a real window a person can interact with.

    An attached browser counts. It is the person's own Chrome, on their own
    screen, started by them a moment ago - so a challenge in it is one they
    can see and solve. Reading only CAR_TRACKER_HEADED here meant the
    attached-Chrome path, whose whole purpose is a person solving a
    challenge, silently used the twelve-second "nobody is watching" wait
    and printed no instructions.
    """
    return os.environ.get("CAR_TRACKER_HEADED", "").strip().lower() in ("1", "true", "yes") or attached_to_own_chrome()


# One browser for the whole run, not one per page. A run fetches dozens of
# URLs (six Tesla markets plus pagination), and launching a fresh browser
# for each was both slow and - in headed mode - a flurry of windows opening
# and closing with no explanation. Reusing it also keeps whatever clearance
# the first challenge earned warm for every later page.
_SESSION: dict[str, object] = {}


def _shared_context(headed: bool):
    """The run's browser context, started on first use."""
    if _SESSION.get("context") is not None and _SESSION.get("headed") == headed:
        return _SESSION["context"]
    close_browser()  # a mode switch means the old context is the wrong kind

    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    endpoint = os.environ.get(_CDP_ENV_VAR, "").strip()
    try:
        if endpoint:
            print(f"  browser: attaching to your own Chrome at {endpoint}", flush=True)
            context = _connect_to_your_own_chrome(playwright, endpoint)
        else:
            context = _launch_browser(playwright, headed=headed)
    except Exception:
        playwright.stop()
        raise
    if not endpoint:
        # Only patch a browser we launched. On an attached one the script
        # would be injected into the person's own context, changing pages
        # they open for themselves - and it is pointless there anyway: a
        # browser nobody automated has no navigator.webdriver to hide.
        context.add_init_script(_STEALTH_INIT)
    _SESSION["playwright"] = playwright
    _SESSION["context"] = context
    _SESSION["headed"] = headed
    return context


def close_browser() -> None:
    """Shut the shared browser down. Safe to call when none is running."""
    context = _SESSION.pop("context", None)
    playwright = _SESSION.pop("playwright", None)
    cdp_browser = _SESSION.pop("cdp_browser", None)
    _SESSION.pop("headed", None)
    if cdp_browser is not None:
        # Someone else's browser. `close()` on a connected-to browser
        # disconnects rather than quitting it, which is what we want - the
        # window the person is working in must survive the run. Their
        # context is theirs too, so drop it without closing.
        context = None
        try:
            cdp_browser.close()
        except Exception:
            pass
    for closer in (getattr(context, "close", None), getattr(playwright, "stop", None)):
        if closer is None:
            continue
        try:
            closer()
        except Exception:
            pass  # shutting down; a failure here must not mask real errors


atexit.register(close_browser)


def _fetch_with_impersonation(url: str, *, accept_language: str, timeout: float) -> tuple[int, str] | None:
    """Step 1. None when curl_cffi isn't installed or the transport failed.

    Retries a 429/503 with exponential backoff — Tesla's API rate-limits a
    burst of combos with a 429, which is a wait, not a refusal.
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None

    last: tuple[int, str] | None = None
    for attempt in range(_IMPERSONATION_RETRIES):
        try:
            response = cffi_requests.get(
                url,
                impersonate=IMPERSONATE_PROFILE,
                headers={"Accept-Language": accept_language},
                timeout=timeout,
            )
        except Exception:
            # A TLS/transport failure here is not fatal: a later step may work.
            return None
        last = (response.status_code, response.text)
        if response.status_code not in _RETRYABLE_STATUS:
            return last
        if attempt >= len(_BACKOFF_SECONDS):
            break
        # A server that says how long to wait knows better than a fixed curve.
        retry_after = response.headers.get("Retry-After") if hasattr(response, "headers") else None
        wait = _BACKOFF_SECONDS[attempt]
        if retry_after:
            try:
                wait = min(max(float(retry_after), wait), _MAX_RETRY_AFTER_SECONDS)
            except ValueError:
                pass  # a date-formatted Retry-After; the fixed curve is fine
        time.sleep(wait)
    return last


def _launch_browser(playwright, *, headed: bool):
    """A browser context that presents as an ordinary Chrome.

    Prefers the installed Google Chrome (channel="chrome"): in headless it
    uses Chrome's *new* headless mode, far less detectable than the bundled
    chrome-headless-shell. Falls back to the bundled Chromium only if Chrome
    isn't installed. Raises the last error for the caller to translate.
    """
    args = ["--disable-blink-features=AutomationControlled"]
    last_exc: Exception | None = None
    # chromium_sandbox defaults to False in Playwright, which makes Chrome
    # open with a yellow "You are using an unsupported command-line flag:
    # --no-sandbox. Stability and security will suffer" bar across the top.
    # On a person's own laptop that is alarming, and it is also one more way
    # this browser does not look like the ordinary one it is trying to be.
    # Keep the sandbox; fall back only where the OS genuinely cannot run it
    # (an unprivileged container), where the alternative is not launching.
    for sandbox in (True, False):
        for channel in ("chrome", None):
            try:
                return playwright.chromium.launch_persistent_context(
                    user_data_dir=str(_browser_profile_dir()),
                    channel=channel,
                    headless=not headed,
                    chromium_sandbox=sandbox,
                    args=args,
                )
            except Exception as exc:  # noqa: PERF203 - four tries, clarity over speed
                last_exc = exc
    assert last_exc is not None
    raise last_exc


def _connect_to_your_own_chrome(playwright, endpoint: str):
    """Rung 4: drive the Chrome the person is already running.

    Every rung below this one is an automated browser doing its best
    impression of an ordinary one. This is an ordinary one. It carries the
    person's real profile and cookies, so a Cloudflare clearance they have
    already earned by browsing the site normally simply applies.
    """
    browser = playwright.chromium.connect_over_cdp(endpoint)
    contexts = browser.contexts
    context = contexts[0] if contexts else browser.new_context()
    _SESSION["cdp_browser"] = browser
    return context


def _first_page(context):
    """The context's existing tab, or a new one.

    `launch_persistent_context` already opens a window on about:blank, so
    calling new_page() left a permanently blank first tab sitting next to
    the real one - which is exactly what a person watching a headed run
    sees and has no way to interpret.
    """
    try:
        for page in context.pages:
            if not page.is_closed():
                return page
    except Exception:
        pass  # the browser is gone; new_page() below will say so properly
    return context.new_page()


def _open_page(headed: bool):
    """Return (borrowed, page), restarting a browser that went away.

    Closing the last tab of a persistent context closes the browser with
    it. Since "close the window" is how a person skips one stubborn site,
    that must not also mean "skip every site after it" - which is exactly
    what happened: every later URL died on the closed context.
    """
    for attempt in (1, 2):
        context = _shared_context(headed)
        borrowed = _SESSION.get("cdp_browser") is not None
        try:
            return borrowed, (context.new_page() if borrowed else _first_page(context))
        except Exception:
            if attempt == 2:
                raise
            close_browser()  # window gone - drop the dead handle and start fresh


def _fetch_with_browser(url: str, *, accept_language: str, timeout: float) -> tuple[int, str]:
    """Step 2/3. Raises FetchError with an actionable message if unavailable."""
    try:
        import playwright.sync_api  # noqa: F401 - presence check only
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise FetchError(
            f"{url} needs a real browser, which isn't installed. Install the browser extra:\n"
            '  uv tool install --from "car-tracker[browser] @ git+https://github.com/Pacha-88/Car" car-tracker\n'
            "  playwright install chromium"
        ) from exc

    headed = headed_mode()
    try:
        borrowed, page = _open_page(headed)
    except Exception as exc:
        # Playwright is installed but no usable browser binary is - the
        # normal state right after `pip install playwright`. Its own error
        # is a wall of stack trace; this runs on the owner's laptop, so say
        # the one command that fixes it. The wrapper scripts also grep for
        # "playwright install" to auto-install.
        raise FetchError(
            f"{url} needs a real browser. Playwright is installed but its browser isn't:\n"
            "  playwright install chromium\n"
            f"(original error: {str(exc).splitlines()[0]})"
        ) from exc

    # `borrowed` above says whose browser this is. When it is ours we
    # navigate its one tab from URL to URL, the way a person browsing
    # would. When it is the person's own Chrome (rung 4), their tabs are
    # theirs: a new one, closed after, rather than navigating whatever they
    # were reading out from under them.
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        status = response.status if response else 0
        body = page.content()
        if not looks_unusable(status, body):
            if headed:
                print(f"  browser: {url} loaded fine, no challenge", flush=True)
            return status, body

        # A challenge clears itself after a few seconds of JS. In headed
        # mode there's a person at the keyboard, so wait for them properly -
        # and say what is going on, since an unexplained browser window is
        # just confusing. Either way the cleared cookie lands in the
        # persistent profile and serves later runs.
        if headed:
            print(_headed_instructions(url, status, body), flush=True)
        deadline = time.monotonic() + (_HEADED_SOLVE_SECONDS if headed else _AUTO_SOLVE_SECONDS)
        while time.monotonic() < deadline:
            if headed and page.is_closed():
                # Closing the window is how a person says "skip this one".
                # Without this the run would sit here for the full wait
                # with nothing left to watch it.
                print("  browser: window closed, moving on\n", flush=True)
                break
            try:
                page.wait_for_timeout(1500)
                body = page.content()
            except Exception:
                break  # the window went away mid-read
            if looks_unusable(200, body):
                continue

            # Cleared. Re-request the URL rather than trusting whatever the
            # challenge page redirected to: Cloudflare often lands on the
            # site's home page, and the clearance cookie is what we were
            # actually here to earn. This is the step that was missing when
            # a live run had its challenge solved a moment too late and
            # threw the result away.
            if headed:
                print("  browser: cleared - re-requesting the page\n", flush=True)
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                return (response.status if response else 200), page.content()
            except Exception:
                return 200, body
        if headed:
            print(_still_blocked_advice(url, status, body), flush=True)
        return status, body
    finally:
        # Keep the browser (and its cookies) for the next URL either way -
        # closing the window's only tab in headed mode made the whole thing
        # vanish between combos, which is what a person watching saw as
        # "it opened and then closed itself".
        if borrowed:
            try:
                page.close()
            except Exception:
                pass


def _headed_instructions(url: str, status: int, body: str) -> str:
    minutes = _HEADED_SOLVE_SECONDS // 60
    return (
        f"\n  A browser window is open on {url}\n"
        f"  It shows: {describe(status, body)}\n"
        f"  If it asks you to verify you're human, solve it there - this waits up to {minutes} minutes,\n"
        "  and what you solve is remembered for future runs. Nothing to solve? Close the window to skip.\n"
    )


def _save_for_diagnosis(url: str, body: str) -> Path | None:
    """Keep the page that defeated us.

    A run reported "a white error page" from Tesla, which is not enough to
    fix anything - the wall could have been Akamai, an expired query, or a
    real error the API returned. The page itself says which. Overwritten
    per host, so this never grows.
    """
    host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
    try:
        path = _browser_profile_dir().parent / f"last-blocked-{host}.html"
        path.write_text(body, encoding="utf-8")
        return path
    except Exception:
        return None  # diagnosis is a bonus; never fail a run over it


def _still_blocked_advice(url: str, status: int, body: str) -> str:
    """What to actually do about it — this runs on a person's own laptop."""
    host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
    lines = [f"  browser: still blocked after waiting ({describe(status, body)})", ""]
    saved = _save_for_diagnosis(url, body)
    if saved is not None:
        lines += [f"  The page itself is saved at {saved} - worth opening if this is unfamiliar.", ""]
    if any(m in body[:4000].lower() for m in _BLOCK_MARKERS):
        lines += [
            "  That is a hard block, not a puzzle - there was nothing on the page to solve.",
            f"  Worth checking which kind: open https://{host} in your normal, everyday browser.",
            "    - Same block there  -> the site is refusing your connection itself, and no",
            "      scraper setting can talk it round. It usually lifts on its own in a day or two.",
            "    - Loads fine there  -> it is this automated browser being singled out. Point the",
            "      run at your own Chrome instead, which is indistinguishable because it is real:",
            "        quit Chrome, then  open -na \"Google Chrome\" --args --remote-debugging-port=9222",
            f"        and run with       {_CDP_ENV_VAR}=http://localhost:9222",
        ]
    return "\n".join(lines) + "\n"


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
        raise FetchError(
            f"{url}: blocked at both stages (impersonation: {first_failure}; browser: {describe(status, body)}). "
            "If this persists, try a visible browser: set CAR_TRACKER_HEADED=1 and run again."
        )
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
