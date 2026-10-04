"""Browser harness for the BITV 2.0 / EN 301 549 / WCAG 2.1 AA tests of web UI v2.

Starts the real app (``create_app``) on a free local port with a throwaway data
dir that holds one saved report and one monitor, and drives it with Playwright
(Chromium). Every test is parametrised over the UI languages found in
``zing/i18n/locales`` and, where colours matter, over the light and dark theme.

Run with ``pytest -m a11y`` (needs ``pip install -e '.[web,a11y]'`` and a
Chromium for Playwright: ``playwright install chromium``). Without Playwright
the whole directory is skipped, so the default test run is unaffected.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("playwright.sync_api", reason="a11y tests need playwright (pip install -e '.[a11y]')")
pytest.importorskip("uvicorn", reason="a11y tests need the web extra")

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright  # noqa: E402

from tests.a11y.bitv_map import describe  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AXE = Path(__file__).resolve().parent / "vendor" / "axe.min.js"
REPORT_FIXTURE = ROOT / "tests" / "fixtures" / "web_report.json"
# findings as JSON (one file per pytest-xdist worker)
_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "")
RESULTS_FILE = Path(os.environ.get("ZING_A11Y_REPORT", ROOT / "a11y-report.json"))
if _WORKER:
    RESULTS_FILE = RESULTS_FILE.with_name(f"{RESULTS_FILE.stem}-{_WORKER}{RESULTS_FILE.suffix}")

# Every UI language (zing/i18n/locales/*.json), English first.
LANGS = sorted((p.stem for p in (ROOT / "zing" / "i18n" / "locales").glob("*.json")), key=lambda c: (c != "en", c))
THEMES = ["light", "dark"]
PAGES = {
    "audit": "/v2/",
    "history": "/v2/history",
    "monitors": "/v2/watches",
    "tools": "/v2/tools",
    "kb": "/v2/kb",
}

WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]
DESKTOP = {"width": 1280, "height": 900}


# --------------------------------------------------------------------------- #
# server
# --------------------------------------------------------------------------- #
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    import httpx
    import uvicorn

    data = tmp_path_factory.mktemp("zing-a11y-data")
    old = os.environ.get("ZING_DATA_DIR")
    os.environ["ZING_DATA_DIR"] = str(data)

    from zing.web import history
    from zing.web.server import create_app

    history.init()
    rid = history.save(json.loads(REPORT_FIXTURE.read_text(encoding="utf-8")))

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            if httpx.get(url + "/api/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    else:  # pragma: no cover
        raise RuntimeError("zing web server did not start")

    # one monitor, so the monitors page has a populated list
    with httpx.Client(base_url=url, headers={"Origin": url}, timeout=10) as c:
        c.post(f"/api/watches/from-history/{rid}", json={})

    yield url

    server.should_exit = True
    thread.join(timeout=10)
    if old is None:
        os.environ.pop("ZING_DATA_DIR", None)
    else:
        os.environ["ZING_DATA_DIR"] = old


# --------------------------------------------------------------------------- #
# browser
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    with sync_playwright() as pw:
        # ZING_A11Y_CHROMIUM: use an already installed Chromium instead of
        # the one matching this Playwright release
        exe = os.environ.get("ZING_A11Y_CHROMIUM") or None
        b = pw.chromium.launch(executable_path=exe)
        yield b
        b.close()


class Opener:
    """Opens v2 pages in a fresh browser context with language/theme preset."""

    def __init__(self, browser: Browser, base_url: str) -> None:
        self.browser = browser
        self.base_url = base_url
        self.contexts: list[BrowserContext] = []

    def __call__(
        self,
        path: str,
        lang: str = "en",
        theme: str = "light",
        viewport: dict[str, int] | None = None,
        **context_opts: Any,
    ) -> Page:
        ctx = self.browser.new_context(
            viewport=viewport or DESKTOP,
            color_scheme="dark" if theme == "dark" else "light",
            **context_opts,
        )
        self.contexts.append(ctx)
        ctx.add_init_script(
            f"try {{ localStorage.setItem('zing.lang', {json.dumps(lang)});"
            f" localStorage.setItem('zing.v2.theme', {json.dumps(theme)}); }} catch (e) {{}}"
        )
        # offline: web fonts etc. are not part of what is tested
        ctx.route(
            "**/*",
            lambda route: route.continue_() if route.request.url.startswith(self.base_url) else route.abort(),
        )
        page = ctx.new_page()
        page.goto(self.base_url + path, wait_until="networkidle")
        settle(page)
        return page

    def close(self) -> None:
        for c in self.contexts:
            c.close()


@pytest.fixture
def open_page(browser: Browser, base_url: str) -> Iterator[Opener]:
    opener = Opener(browser, base_url)
    yield opener
    opener.close()


def settle(page: Page) -> None:
    """Let rendering, fetches and transitions finish."""
    with contextlib.suppress(Exception):
        page.wait_for_load_state("networkidle", timeout=5000)
    page.wait_for_timeout(150)


# --------------------------------------------------------------------------- #
# page states
# --------------------------------------------------------------------------- #
EXPAND_JS = """
() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  let n = 0;
  for (const el of document.querySelectorAll('[aria-expanded="false"]')) {
    if (!vis(el) || el.closest('nav, header') || el.hasAttribute('aria-haspopup')) continue;
    el.click(); n++;
  }
  for (const d of document.querySelectorAll('details:not([open])')) { d.open = true; n++; }
  return n;
}
"""


def expand_all(page: Page) -> None:
    """Open every disclosure on the page (two rounds: opened parts may hold more)."""
    for _ in range(2):
        if not page.evaluate(EXPAND_JS):
            break
        settle(page)


def tab_states(page: Page) -> list[str]:
    """Ids/labels of every tab, so each panel can be shown and checked."""
    return list(
        page.evaluate(
            """() => [...document.querySelectorAll('[role=tab]')]
                 .filter(t => t.getBoundingClientRect().width > 0)
                 .map((t, i) => t.id ? '#' + CSS.escape(t.id) : `:nth-match([role=tab], ${i + 1})`)"""
        )
    )


TO_TOP_JS = """
() => {
  window.scrollTo(0, 0);
  const a = document.createElement('span');
  a.tabIndex = -1;
  a.setAttribute('data-a11y-start', '');
  document.body.prepend(a);
  a.focus({ preventScroll: true });
  a.addEventListener('blur', () => a.remove(), { once: true });
}
"""


def to_top(page: Page) -> None:
    """Move the sequential focus starting point to the top of the page, so the
    next Tab press focuses the first Tab stop (blur() alone keeps the point)."""
    page.evaluate(TO_TOP_JS)


# --------------------------------------------------------------------------- #
# axe
# --------------------------------------------------------------------------- #
def run_axe(page: Page, tags: list[str] | None = None, rules: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run axe-core on the page; returns the violations (rule, impact, nodes)."""
    if not page.evaluate("() => !!window.axe"):
        page.add_script_tag(path=str(AXE))
    opts: dict[str, Any] = {"resultTypes": ["violations"]}
    if tags:
        opts["runOnly"] = {"type": "tag", "values": tags}
    if rules:
        opts["rules"] = rules
    res = page.evaluate("opts => axe.run(document, opts)", opts)
    return list(res["violations"])


def format_violations(violations: list[dict[str, Any]], where: str) -> str:
    lines = [f"{len(violations)} accessibility rule(s) violated on {where}:"]
    for v in violations:
        lines.append(f"\n[{v['impact']}] {v['id']}: {v['help']}  —  {describe(v['tags'])}")
        lines.append(f"    {v['helpUrl']}")
        for node in v["nodes"][:8]:
            lines.append(f"    · {' '.join(map(str, node['target']))}")
            summary = (node.get("failureSummary") or "").replace("\n", " ")
            if summary:
                lines.append(f"        {summary[:300]}")
        if len(v["nodes"]) > 8:
            lines.append(f"    … and {len(v['nodes']) - 8} more")
    return "\n".join(lines)


_results_lock = threading.Lock()


def record(kind: str, where: str, issues: list[Any]) -> None:
    """Append findings to a JSON report (uploaded by the non-blocking CI job)."""
    if not issues:
        return
    with _results_lock:
        data: list[Any] = []
        if RESULTS_FILE.exists():
            try:
                data = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
            except ValueError:
                data = []
        data.append({"kind": kind, "where": where, "issues": issues})
        RESULTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


@pytest.fixture(scope="session", autouse=True)
def _fresh_results() -> None:
    if RESULTS_FILE.exists():
        RESULTS_FILE.unlink()


def assert_no_violations(violations: list[dict[str, Any]], where: str, kind: str = "axe") -> None:
    if violations:
        record(
            kind,
            where,
            [{"rule": v["id"], "impact": v["impact"], "targets": [n["target"] for n in v["nodes"]]} for v in violations],
        )
    assert not violations, format_violations(violations, where)


def assert_no_issues(issues: list[str], where: str, kind: str) -> None:
    record(kind, where, issues)
    assert not issues, f"{len(issues)} {kind} issue(s) on {where}:\n  " + "\n  ".join(issues)
