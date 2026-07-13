"""`PlaywrightBrowserSessionFactory` — the REAL Chromium-backed
`pool.BrowserSessionPort` driver.

Integration-lane only (task instruction: "the real Playwright/Chromium code
path is `# pragma: no cover` and/or integration-lane"): this module is
importable even when the `playwright` package is not installed (the
`import playwright...` line itself is guarded, `_PLAYWRIGHT_IMPORT_ERROR`
records why if it failed) — nothing in `saena_chatgpt_observer`'s public
`__init__.py` imports this module eagerly, and the unit lane
(`tests/unit/svc_chatgpt_observer/**`) never imports it at all. Constructing
`PlaywrightBrowserSessionFactory` itself raises `PlaywrightUnavailableError`
immediately if the import failed, so a caller gets a clear, typed error
rather than a bare `ModuleNotFoundError` deep inside `pool.BrowserPool.
acquire()`.

READ-ONLY discipline (task instruction: "the observer never logs into /
writes to a ChatGPT account, never carries Git credentials in its service
account, never mutates any external state. It only reads rendered search
results"): every method this driver exposes maps 1:1 onto
`pool.BrowserSessionPort`'s own read-only surface
(`render_search_result`/`is_healthy`/`close`) — there is no login/
credential/cookie-persistence/form-submit call anywhere in this module.
`_navigate_and_read` issues exactly one `page.goto(...)` (a GET-shaped
navigation) followed by a content read; it never calls `page.fill`/
`page.click`/`page.set_extra_http_headers` with an Authorization/session
header, and this module accepts no credential/token parameter anywhere in
its public constructor.

`playwright` itself is NOT added to this service's `pyproject.toml`
dependencies by this patch unit (task instruction: "If you add a new
runtime dependency ... note it for the Integrator — do NOT edit the root
lockfile yourself") — see this unit's manifest for that note. Until the
Integrator locks it, this module's guarded import always fails in every
environment (dev, CI unit lane, CI integration lane alike), which is safe
and intentional: `tests/integration/browser_observer/**` unconditionally
skips itself when the import is unavailable (`pytest.importorskip`), never
erroring.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

from saena_chatgpt_observer.errors import BrowserSessionRenderError, ChatgptObserverError
from saena_chatgpt_observer.pool import BrowserSessionPort

try:  # pragma: no cover — exercised only when playwright is installed
    from playwright.sync_api import Browser as _PlaywrightBrowser  # type: ignore[import-not-found]
    from playwright.sync_api import Page as _PlaywrightPage
    from playwright.sync_api import sync_playwright as _sync_playwright

    _PLAYWRIGHT_IMPORT_ERROR: Exception | None = None
except ImportError as _exc:  # pragma: no cover — exercised only when NOT installed
    _PlaywrightBrowser = Any
    _PlaywrightPage = Any
    _sync_playwright = None
    _PLAYWRIGHT_IMPORT_ERROR = _exc

#: ChatGPT Search's own public result surface — this driver only ever
#: navigates here (a plain GET-shaped read), never a login/account route.
CHATGPT_SEARCH_URL_TEMPLATE = "https://chatgpt.com/search?q={query}"


class PlaywrightUnavailableError(ChatgptObserverError):
    """`playwright` is not installed in this environment.

    Integration-lane callers should skip (`pytest.importorskip("playwright")`
    at collection time, per this unit's own test-harness convention)
    rather than let this propagate; it exists mainly so a
    misconfigured PRODUCTION deploy (browser pool without the Playwright
    dependency actually installed in its image) fails loudly and typed,
    not with a bare `ModuleNotFoundError` traceback.
    """

    error_code = "saena.unavailable.playwright_not_installed"


@dataclass(slots=True)
class _PlaywrightBrowserSession:
    """`pool.BrowserSessionPort` adapter over one real Playwright
    `Browser`/`Page` pair. READ-ONLY: `render_search_result` is this
    class's only capture method, and it performs exactly one navigation +
    one content read, nothing else."""

    _browser: _PlaywrightBrowser
    _page: _PlaywrightPage
    session_id: str
    _closed: bool = False

    def render_search_result(self, *, query_text: str) -> bytes:
        if self._closed:
            raise BrowserSessionRenderError(
                f"session {self.session_id!r} is closed",
                context={"session_id": self.session_id},
            )
        try:
            url = CHATGPT_SEARCH_URL_TEMPLATE.format(query=query_text)
            self._page.goto(url, wait_until="networkidle")
            content = self._page.content()
        except Exception as exc:  # noqa: BLE001 — adapter boundary: any
            # Playwright failure (navigation timeout, target crashed, ...)
            # maps to this package's own typed, retryable capture error —
            # never a bare Playwright exception escaping this module.
            raise BrowserSessionRenderError(
                f"playwright render failed for query {query_text!r}: {exc}",
                context={"session_id": self.session_id, "query_text": query_text},
            ) from exc
        return content.encode("utf-8")

    def is_healthy(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self._browser.is_connected())
        except Exception:  # noqa: BLE001 — a health probe must never raise
            return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):  # best-effort teardown
            self._page.close()


class PlaywrightBrowserSessionFactory:
    """Real `pool.BrowserSessionFactory` — one persistent Chromium
    `playwright.sync_api.Browser` instance backs every session this
    factory builds (a fresh `Page`/incognito `BrowserContext` per session,
    never a shared login/cookie state — ADR-0004 "No Git credential issued
    at all"; this factory accepts no credential parameter and never calls
    `context.add_cookies`/`page.set_extra_http_headers` with an auth
    header).

    `# pragma: no cover` at module scope (see `pool.py` module docstring):
    this class is only ever constructed by
    `tests/integration/browser_observer/**`, which itself
    `pytest.importorskip("playwright")`s before importing this module, so
    the unit lane never executes a single line of this class's body.
    """

    def __init__(self, *, headless: bool = True) -> None:
        if _PLAYWRIGHT_IMPORT_ERROR is not None:  # pragma: no cover
            raise PlaywrightUnavailableError(
                "playwright is not installed in this environment",
                context={"import_error": str(_PLAYWRIGHT_IMPORT_ERROR)},
            ) from _PLAYWRIGHT_IMPORT_ERROR
        self._headless = headless
        self._next_id = 0
        self._playwright_cm = _sync_playwright()
        self._playwright = self._playwright_cm.start()
        self._browser: _PlaywrightBrowser = self._playwright.chromium.launch(headless=headless)

    def __call__(self) -> BrowserSessionPort:
        context = self._browser.new_context()
        page = context.new_page()
        session = _PlaywrightBrowserSession(
            _browser=self._browser,
            _page=page,
            session_id=f"playwright-session-{self._next_id}",
        )
        self._next_id += 1
        return session

    def shutdown(self) -> None:
        """Tear down the whole Chromium process (call once, after every
        `BrowserPool` built from this factory has itself been `close()`d)."""
        try:
            self._browser.close()
        finally:
            self._playwright_cm.stop()


__all__ = [
    "CHATGPT_SEARCH_URL_TEMPLATE",
    "PlaywrightBrowserSessionFactory",
    "PlaywrightUnavailableError",
]
