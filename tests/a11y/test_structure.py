"""Order, consistency and content heuristics.

BITV 9.1.3.2 Meaningful sequence, 9.2.4.3 Focus order, 9.3.2.4 Consistent
identification, 9.2.4.5 Multiple ways, 9.3.3.4 Error prevention (data),
9.1.3.3 Sensory characteristics, 9.1.4.1 Use of colour.

What these checks decide and where a person is still needed:

* Reading and Tab order are compared with the visual order "top to bottom,
  then left to right within a row" (the UI has no RTL language). A pair only
  counts as inverted when the later element lies *entirely* left of the earlier
  one in the same row, or *entirely* above it in the same column or column to
  the left. Moving up into a column further right (a sidebar) is a normal
  column break and is allowed.
* Consistent identification keys controls by what they do (href, function
  data attributes, the shared header's classes), never by their label, and
  compares accessible name and role computed by axe-core.
* Sensory characteristics is a word-list heuristic (step stays partial).
* Use of colour renders the same component in every state and compares what
  is left without colour (text, icons, shapes): two states may not differ by
  colour alone.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page

from tests.a11y.harness import (
    AXE,
    DESKTOP,
    LANGS,
    PAGES,
    assert_no_issues,
    expand_all,
    settle,
    to_top,
)

PAGE_IDS = list(PAGES)
PHONE = {"width": 375, "height": 800}
VIEWPORTS = {"desktop": DESKTOP, "375px": PHONE}
ORDER_LANGS = [x for x in ("en", "de") if x in LANGS]

# --------------------------------------------------------------------------- #
# shared in-page helpers
# --------------------------------------------------------------------------- #
DESCRIBE = """
const describeEl = el => {
  const t = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
  const cls = typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\\s+/).join('.') : '';
  return `<${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${cls}> "${t}"`;
};
"""

# geometry: "is b shown before a?" for a that comes first (DOM or Tab order)
GEOMETRY = """
const CONTROL = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [tabindex], [role=button], [role=link], [role=tab], [role=switch], [role=checkbox]';
const shown = el => {
  if (el.closest('[aria-hidden=true], [inert], [hidden]')) return false;
  const s = getComputedStyle(el), r = el.getBoundingClientRect();
  return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && parseFloat(s.opacity) > 0;
};
const meaningful = el => !!((el.innerText || '').trim() || el.matches(CONTROL) ||
  el.querySelector(CONTROL + ', img[alt]:not([alt=""]), svg[role=img], canvas, [role=img]'));
const box = el => { const r = el.getBoundingClientRect();
  return { left: r.left + scrollX, right: r.right + scrollX, top: r.top + scrollY, bottom: r.bottom + scrollY, width: r.width, height: r.height }; };
const TOL = 1;
// 'row' / 'column' / null: b (later) is shown before a (earlier)
const inverted = (a, b) => {
  const ov = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  if (ov > 0.5 * Math.min(a.height, b.height)) return b.right <= a.left + TOL ? 'left of it in the same row' : null;
  if (b.bottom > a.top + TOL) return null;                       // not above
  const xov = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  if (xov > 0) return 'above it in the same column';
  if (b.right <= a.left + TOL) return 'above and left of it';
  return null;                                                   // up into a column further right
};
"""

# --------------------------------------------------------------------------- #
# 9.1.3.2 meaningful sequence
# --------------------------------------------------------------------------- #
SEQUENCE_JS = (
    "() => {"
    + DESCRIBE
    + GEOMETRY
    + """
  const out = [];
  const flowKids = p => {
    const kids = [];
    for (const c of p.children) {
      if (/^(SCRIPT|STYLE|TEMPLATE|NOSCRIPT)$/.test(c.tagName)) continue;
      const s = getComputedStyle(c);
      if (s.display === 'contents') { kids.push(...flowKids(c)); continue; }
      if (s.position === 'absolute' || s.position === 'fixed') continue;   // checked below
      if (shown(c) && meaningful(c)) kids.push(c);
    }
    return kids;
  };
  const cause = (p, a, b) => {
    const ps = getComputedStyle(p), why = [];
    if (/reverse/.test(ps.flexDirection) && /flex/.test(ps.display)) why.push('flex-direction: ' + ps.flexDirection);
    if (/reverse/.test(ps.flexWrap) && /flex/.test(ps.display)) why.push('flex-wrap: ' + ps.flexWrap);
    for (const el of [a, b]) {
      const s = getComputedStyle(el);
      if (s.order !== '0' && /flex|grid/.test(ps.display)) why.push(`order: ${s.order} on ${describeEl(el)}`);
      if (/grid/.test(ps.display) && (s.gridRowStart !== 'auto' || s.gridColumnStart !== 'auto' || s.gridArea.split('/').some(x => x.trim() !== 'auto')))
        why.push(`grid placement (${s.gridArea}) on ${describeEl(el)}`);
      if (s.float !== 'none') why.push(`float: ${s.float} on ${describeEl(el)}`);
    }
    return why.length ? why.join(', ') : 'layout';
  };
  for (const p of document.body.querySelectorAll('*')) {
    if (!shown(p) || getComputedStyle(p).display === 'contents') continue;
    const kids = flowKids(p);
    if (kids.length < 2) continue;
    const boxes = kids.map(box);
    const all = kids.length <= 40;
    let first = null, n = 0;
    for (let i = 0; i < kids.length; i++) {
      for (let j = i + 1; j < (all ? kids.length : Math.min(i + 2, kids.length)); j++) {
        const how = inverted(boxes[i], boxes[j]);
        if (!how) continue;
        n++;
        if (!first) first = `${describeEl(kids[j])} comes after ${describeEl(kids[i])} in the DOM but is shown ${how} (${cause(p, kids[i], kids[j])})`;
      }
    }
    if (first) out.push(`reading order differs from visual order inside ${describeEl(p)}: ${first}` + (n > 1 ? ` (+${n - 1} more pair(s))` : ''));
  }
  // content taken out of the flow and shown far from where it is read
  const vh = innerHeight;
  for (const el of document.body.querySelectorAll('*')) {
    const s = getComputedStyle(el);
    if (s.position !== 'absolute' && s.position !== 'fixed') continue;
    if (!shown(el) || !meaningful(el)) continue;
    if (el.closest('dialog, [role=dialog], [role=alertdialog], [role=tooltip], [popover], [role=status], [role=alert], [aria-live], [role=menu], [role=listbox]')) continue;
    const b = box(el);
    if (b.bottom < 0 || b.right < 0) continue;                     // parked off-screen (skip link)
    let ref = el.previousElementSibling;
    while (ref && !(shown(ref) && !/absolute|fixed/.test(getComputedStyle(ref).position))) ref = ref.previousElementSibling;
    if (!ref) ref = el.parentElement;
    while (ref && ref !== document.body && !shown(ref)) ref = ref.parentElement;
    if (!ref || ref === document.body) continue;
    const r = box(ref);
    const dy = Math.max(0, r.top - b.bottom, b.top - r.bottom), dx = Math.max(0, r.left - b.right, b.left - r.right);
    if (dy > Math.max(200, vh / 4) || dx > 400)
      out.push(`${describeEl(el)} is positioned (${s.position}) ${Math.round(Math.max(dx, dy))} px away from where it is read, after ${describeEl(ref)}`);
  }
  return out;
}
"""
)


@pytest.mark.bitv("9.1.3.2")
@pytest.mark.parametrize("viewport", list(VIEWPORTS))
@pytest.mark.parametrize("lang", ORDER_LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_reading_order_matches_visual_order(open_page, page_id: str, lang: str, viewport: str) -> None:
    """9.1.3.2 Meaningful sequence: siblings are shown in DOM order (no CSS
    order / *-reverse / grid placement / float that swaps meaningful content,
    no positioned content far from where it is read)."""
    page = open_page(PAGES[page_id], lang, viewport=VIEWPORTS[viewport])
    expand_all(page)
    page.evaluate("() => window.scrollTo(0, 0)")
    assert_no_issues(page.evaluate(SEQUENCE_JS), f"{page_id} [{lang}, {viewport}]", "meaningful-sequence")


# --------------------------------------------------------------------------- #
# 9.2.4.3 focus order
# --------------------------------------------------------------------------- #
STAMP_JS = """
k => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return false;
  if (!el.hasAttribute('data-a11y-tab')) el.setAttribute('data-a11y-tab', String(k));
  return true;
}
"""

FOCUS_ORDER_JS = (
    "() => {"
    + DESCRIBE
    + GEOMETRY
    + """
  // measure every stop in one layout state: no element scrolled
  window.scrollTo(0, 0);
  for (const el of document.querySelectorAll('*')) { if (el.scrollLeft) el.scrollLeft = 0; if (el.scrollTop) el.scrollTop = 0; }
  const stops = [...document.querySelectorAll('[data-a11y-tab]')]
    .sort((x, y) => +x.getAttribute('data-a11y-tab') - +y.getAttribute('data-a11y-tab'));
  const fixed = el => { for (let p = el; p && p.nodeType === 1; p = p.parentElement) if (getComputedStyle(p).position === 'fixed') return true; return false; };
  const out = [];
  let prev = null;
  for (const el of stops) {
    if (!shown(el) || fixed(el)) { prev = null; continue; }   // a dialog or toast: not part of the page order
    const b = box(el);
    if (prev) {
      const how = inverted(prev.b, b);
      if (how) out.push(`Tab moves from ${describeEl(prev.el)} to ${describeEl(el)}, which is shown ${how}`);
    }
    prev = { el, b };
  }
  return out;
}
"""
)


def tab_through(page: Page, limit: int = 400) -> int:
    """Press Tab from the top until focus leaves the page, stamping each stop
    with its position in the sequence (data-a11y-tab)."""
    page.mouse.move(0, 0)
    to_top(page)
    k = 0
    for k in range(limit):
        page.keyboard.press("Tab")
        if not page.evaluate(STAMP_JS, k):
            break
    return k


@pytest.mark.bitv("9.2.4.3")
@pytest.mark.parametrize("viewport", list(VIEWPORTS))
@pytest.mark.parametrize("lang", ORDER_LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_focus_order_matches_visual_order(open_page, page_id: str, lang: str, viewport: str) -> None:
    """9.2.4.3 Focus order: each Tab press moves forward in the visual reading
    order (right within a row, down within a column, or on to the next column)."""
    page = open_page(PAGES[page_id], lang, viewport=VIEWPORTS[viewport])
    expand_all(page)
    tab_through(page)
    assert_no_issues(page.evaluate(FOCUS_ORDER_JS), f"{page_id} [{lang}, {viewport}]", "focus-order")


# --------------------------------------------------------------------------- #
# 9.3.2.4 consistent identification
# --------------------------------------------------------------------------- #
# Data attributes that hold a control's function (data-act="del",
# data-mk="reset", data-dl="json", ...). Translation, layout and record-id
# attributes are not functions; values with digits are record ids.
NOT_A_FUNCTION = r"^data-(en|a11y|id$|i$|msg$|l0$|w$|v$|f$|page$|theme$|step$|seg$|tip$|zp$|metric$)"
# class tokens that only style a control (a component class like "rdel" or
# "secret-eye" names its function)
STYLE_CLASSES = r"^(btn|sm|lg|pri|primary|danger|danger-solid|ghost|link|linkbtn|in|mono|on|off|active|open|is-.*|has-.*|good|bad|warn|sky|grey|tag|badge|pill|more)$"

IDENTIFY_JS = """
([notFn, styleCls]) => {
  const NOT = new RegExp(notFn), STYLE = new RegExp(styleCls);
  axe.setup(document);
  const out = [];
  try {
    const sel = 'a[href], button, select, input:not([type=hidden]), textarea, summary, [role=button], [role=link], [role=tab], [role=switch], [role=checkbox], [role=menuitem]';
    for (const el of document.querySelectorAll(sel)) {
      const r = el.getBoundingClientRect();
      if ((r.width === 0 || r.height === 0) && !el.matches('.skip-link')) continue;
      if (el.closest('[aria-hidden=true], [inert]')) continue;
      let key = null;
      const href = el.getAttribute('href');
      if (href != null && el.matches('a')) {
        if (/^[?#]/.test(href)) key = 'link ' + href;
        else { const u = new URL(href, location.href); key = 'link ' + (u.origin === location.origin ? '' : u.origin) + u.pathname + u.search + u.hash; }
      }
      if (!key) for (const a of el.attributes) {
        if (a.name.startsWith('data-') && !NOT.test(a.name) && /^[a-z][a-z_-]*$/i.test(a.value)) { key = `[${a.name}=${a.value}]`; break; }
      }
      if (!key && el.id && !/\\d/.test(el.id)) key = '#' + el.id;
      if (!key && typeof el.className === 'string') {
        const cls = el.className.trim().split(/\\s+/).filter(c => c && !STYLE.test(c)).sort();
        if (cls.length) key = el.tagName.toLowerCase() + '.' + cls.join('.');
      }
      if (!key) continue;
      const lm = el.closest('nav, header, footer, main, aside, dialog, [role=dialog], [role=navigation], [role=banner], [role=contentinfo]');
      const where = lm ? (lm.getAttribute('role') || lm.tagName.toLowerCase()) : 'page';
      const vn = axe.utils.getNodeFromTree(el);
      const name = (vn ? axe.commons.text.accessibleTextVirtual(vn) : '').replace(/\\s+/g, ' ').trim();
      const role = (vn && axe.commons.aria.getRole(vn)) || el.tagName.toLowerCase();
      out.push({ key: `${key} in ${where}`, role, name });
    }
  } finally { axe.teardown(); }
  return out;
}
"""


@pytest.mark.bitv("9.3.2.4")
@pytest.mark.parametrize("lang", LANGS)
def test_consistent_identification(open_page, lang: str) -> None:
    """9.3.2.4 Consistent identification: a control that does the same thing
    (same link target, same data-act/-mk/-dl function, same id, same component
    class) has the same accessible name and role on every page it appears on.

    Each page contributes the set of (role, name) it uses for a function in a
    landmark; one page may use several (the logo and the "Audit" link both go
    to /v2/, the audit form has two model pickers). Two pages clash when they
    share no (role, name) for the same function: the same thing is called
    differently."""
    found: dict[str, dict[str, set[tuple[str, str]]]] = {}
    for page_id, path in PAGES.items():
        page = open_page(path, lang)
        expand_all(page)
        page.add_script_tag(path=str(AXE))
        for c in page.evaluate(IDENTIFY_JS, [NOT_A_FUNCTION, STYLE_CLASSES]):
            found.setdefault(c["key"], {}).setdefault(page_id, set()).add((c["role"], c["name"]))
    issues: list[str] = []
    for key, per_page in sorted(found.items()):
        pages = list(per_page)
        clash = [(a, b) for i, a in enumerate(pages) for b in pages[i + 1 :] if not per_page[a] & per_page[b]]
        if not clash:
            continue
        shown = "; ".join(
            f"{pid}: " + " | ".join(f"{role} {name!r}" for role, name in sorted(v)) for pid, v in per_page.items()
        )
        issues.append(f"{key} is identified differently across pages — {shown}")
    assert_no_issues(issues, f"all pages [{lang}]", "consistent-identification")


# --------------------------------------------------------------------------- #
# 9.2.4.5 multiple ways
# --------------------------------------------------------------------------- #
NAV_LINKS_JS = """
() => {
  const navs = [...document.querySelectorAll('nav, [role=navigation]')];
  const out = {};
  for (const nav of navs) for (const a of nav.querySelectorAll('a[href]')) {
    const u = new URL(a.href, location.href);
    if (u.origin !== location.origin) continue;
    const r = a.getBoundingClientRect(), s = getComputedStyle(a);
    // a link in a scrolled row is still there; one that is hidden is not
    const usable = r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && !a.closest('[hidden], [inert], [aria-hidden=true]');
    out[u.pathname] = out[u.pathname] || usable;
  }
  return out;
}
"""


def _norm_path(path: str) -> str:
    return path.rstrip("/") or "/"


@pytest.mark.bitv("9.2.4.5")
@pytest.mark.parametrize("viewport", list(VIEWPORTS))
def test_every_page_reachable_from_every_page(open_page, base_url: str, viewport: str) -> None:
    """9.2.4.5 Multiple ways: every v2 page can be opened by its own URL and
    from a usable link in the navigation landmark of every other page (two
    ways; the app is too small to need search or a site map)."""
    import httpx

    issues: list[str] = []
    for page_id, path in PAGES.items():
        r = httpx.get(base_url + path, timeout=10, follow_redirects=True)
        if r.status_code != 200:
            issues.append(f"{page_id}: direct URL {path} answers HTTP {r.status_code}")
    for page_id, path in PAGES.items():
        page = open_page(path, "en", viewport=VIEWPORTS[viewport])
        links = {_norm_path(k): v for k, v in page.evaluate(NAV_LINKS_JS).items()}
        for other_id, other in PAGES.items():
            if other_id == page_id:
                continue
            got = links.get(_norm_path(other))
            if got is None:
                issues.append(f"{page_id}: its navigation has no link to {other_id} ({other})")
            elif not got:
                issues.append(f"{page_id}: the navigation link to {other_id} ({other}) is hidden")
    assert_no_issues(issues, f"all pages [en, {viewport}]", "multiple-ways")


# --------------------------------------------------------------------------- #
# 9.3.3.4 error prevention (data)
# --------------------------------------------------------------------------- #
# Requests that destroy data. In the test's browser context they never reach
# the server: they are logged and answered with a fake success, so the UI
# behaves as after a real delete while the shared fixture data stays intact.
DESTRUCTIVE_POSTS = re.compile(r"/(reset|clear|purge|wipe|delete|remove)(/|$)")
# Every destructive action of the app; each must be found and checked.
EXPECTED_DESTRUCTIVE = {
    "history": [r"DELETE /api/history/\d+$", r"DELETE /api/history$"],
    "monitors": [r"DELETE /api/watches/\d+$", r"POST /api/secret/reset$"],
    "kb": [r"DELETE /api/kb/entries/\d+$"],
}
# a lost master key (the only state that offers "reset"), answered to this page only
LOCKED_VAULT = {
    "state": "locked", "source": None, "fingerprint": None, "actions": ["unlock", "reset"], "warnings": [],
    "error": None, "counts": {"encrypted": 1, "locked": 0, "unreadable": 0, "plain": 0},
}  # fmt: skip
# one entry of the user's own, so the knowledge base page offers "Delete"
FAKE_KB_ENTRY = {
    "id": 990001, "kind": "model", "provider": "a11y", "model_id": "a11y-test-model", "enabled": True,
    "origin": "a11y", "created_ts": 1790000000, "updated_ts": 1790000000,
}  # fmt: skip

DESTRUCTIVE_WORDS = r"\b(delete|remove|clear|erase|reset|drop|discard|purge|wipe|forget)\b"
UNDO_WORDS = r"\b(undo|restore|revert)\b"

CONTROL_HELPERS = """
const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && !el.closest('[hidden], [inert], [aria-hidden=true]'); };
const label = el => [el.getAttribute('aria-label'), el.innerText, el.getAttribute('title'), el.value]
  .filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim();
const fnOf = el => [...el.attributes].filter(a => a.name.startsWith('data-') && !/^data-(en|a11y)/.test(a.name))
  .map(a => a.value).join(' ').replace(/[-_]/g, ' ');
"""

CANDIDATES_JS = (
    "([words]) => {"
    + CONTROL_HELPERS
    + """
  const re = new RegExp(words, 'i');
  const out = [];
  for (const el of document.querySelectorAll('button, [role=button], a[href], input[type=submit], input[type=button]')) {
    if (!vis(el) || el.disabled) continue;
    if (re.test(label(el)) || re.test(fnOf(el)) || el.matches('.danger, .danger-solid')) {
      el.setAttribute('data-a11y-d', String(out.length));
      out.push(label(el).slice(0, 50) || el.outerHTML.slice(0, 60));
    }
  }
  return out;
}
"""
)

# marks what is on screen before the click; returns the clicked control's identity
SNAPSHOT_JS = (
    "(sel) => {"
    + CONTROL_HELPERS
    + """
  for (const el of document.querySelectorAll('button, [role=button], a[href], input, select, textarea'))
    if (el.getBoundingClientRect().width > 0) el.setAttribute('data-a11y-seen', '');
  const t = document.querySelector(sel);
  return label(t) + '|' + fnOf(t);
}
"""
)

# open disclosures, but not the ones that start a delete (expand_all would)
SAFE_EXPAND_JS = (
    "([words]) => {"
    + CONTROL_HELPERS
    + """
  const re = new RegExp(words, 'i');
  let n = 0;
  for (const el of document.querySelectorAll('[aria-expanded="false"]')) {
    if (!vis(el) || el.closest('nav, header') || el.hasAttribute('aria-haspopup')) continue;
    if (re.test(label(el)) || re.test(fnOf(el)) || el.matches('.danger, .danger-solid')) continue;
    el.click(); n++;
  }
  for (const d of document.querySelectorAll('details:not([open])')) { d.open = true; n++; }
  return n;
}
"""
)

# the controls a click revealed: a confirmation step shows a new "yes" button
NEW_CONTROLS_JS = (
    "([words, undo, clicked]) => {"
    + CONTROL_HELPERS
    + """
  const re = new RegExp(words, 'i'), reUndo = new RegExp(undo, 'i');
  // re-rendered markup brings the clicked control back as a "new" one: skip it
  const fresh = [...document.querySelectorAll('button, [role=button], a[href], input, select, textarea')]
    .filter(el => vis(el) && !el.hasAttribute('data-a11y-seen') && label(el) + '|' + fnOf(el) !== clicked);
  fresh.forEach((el, i) => el.setAttribute('data-a11y-new', String(i)));
  let yes = null, undoBtn = null, typed = null;
  for (const el of fresh) {
    if (el.disabled) continue;
    if (!undoBtn && reUndo.test(label(el))) undoBtn = label(el);
    if (!yes && el.matches('button, input[type=submit]') && !/\\b(no|cancel)\\b/i.test(fnOf(el) + ' ' + label(el)) &&
        (re.test(label(el)) || re.test(fnOf(el)) || el.matches('.danger, .danger-solid')))
      yes = el.getAttribute('data-a11y-new');
  }
  // "Type RESET to confirm": the upper-case word after "type" / "enter"
  const input = fresh.find(el => el.matches('input:not([type=checkbox]):not([type=radio]):not([type=hidden]), textarea') && !el.value);
  if (input) {
    const ids = (input.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
    const q = ids.map(id => (document.getElementById(id) || {}).innerText || '').join(' ') + ' ' + ((input.closest('form') || {}).innerText || '');
    const m = /\\b(?:[Tt]ype|[Ee]nter)\\s+["'“„«]?([A-Z]{3,})\\b/.exec(q);
    typed = { i: input.getAttribute('data-a11y-new'), word: m ? m[1] : null };
  }
  return { yes, undo: undoBtn, typed };
}
"""
)


def _guarded_page(open_page: Any, page_id: str, log: list[str], dialogs: list[str]) -> Page:
    """The page with destructive requests intercepted, and the data seeded
    (for this browser context only) that makes every destructive action show."""
    page: Page = open_page(PAGES[page_id], "en")

    def handle(route: Any) -> None:
        req = route.request
        path = urlparse(req.url).path
        if req.method == "DELETE" or (req.method == "POST" and DESTRUCTIVE_POSTS.search(path)):
            log.append(f"{req.method} {path}")
            route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
        elif req.method == "GET" and path == "/api/secret":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(LOCKED_VAULT))
        elif req.method == "GET" and path == "/api/kb/profiles":
            resp = route.fetch()
            data = resp.json()
            data["entries"] = [FAKE_KB_ENTRY, *(data.get("entries") or [])]
            route.fulfill(response=resp, body=json.dumps(data), content_type="application/json")
        else:
            route.fallback()

    page.context.route("**/api/**", handle)

    def on_dialog(d: Any) -> None:
        dialogs.append(f"{d.type}: {d.message[:80]}")
        d.dismiss()  # "Cancel": nothing may be deleted

    page.on("dialog", on_dialog)
    page.reload(wait_until="networkidle")
    settle(page)
    for _ in range(2):
        if not page.evaluate(SAFE_EXPAND_JS, [DESTRUCTIVE_WORDS]):
            break
        settle(page)
    return page


@pytest.mark.bitv("9.3.3.4")
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_destructive_actions_ask_first(open_page, page_id: str) -> None:
    """9.3.3.4 Error prevention (data): every action that deletes or resets
    data asks first (a confirm() dialog or an inline confirmation step) or can
    be undone. Each destructive-looking control is clicked on a fresh page: a
    destructive request sent by that first click, with no dialog and no undo
    control appearing, fails. An inline confirmation must be what deletes:
    its "yes" is pressed and the request has to follow. Every destructive
    endpoint of the app must be met this way."""
    log: list[str] = []
    dialogs: list[str] = []
    page = _guarded_page(open_page, page_id, log, dialogs)
    names: list[str] = page.evaluate(CANDIDATES_JS, [DESTRUCTIVE_WORDS])
    issues: list[str] = []
    checked: list[str] = []
    for i, name in enumerate(names):
        if i:
            log.clear()
            dialogs.clear()
            page = _guarded_page(open_page, page_id, log, dialogs)
            page.evaluate(CANDIDATES_JS, [DESTRUCTIVE_WORDS])
        target = page.locator(f'[data-a11y-d="{i}"]')
        if not target.count():
            issues.append(f"destructive control {name!r} is gone after reloading the page")
            continue
        clicked = page.evaluate(SNAPSHOT_JS, f'[data-a11y-d="{i}"]')
        target.first.click()
        settle(page)
        new = page.evaluate(NEW_CONTROLS_JS, [DESTRUCTIVE_WORDS, UNDO_WORDS, clicked])
        if log:
            checked += log
            if dialogs:
                issues.append(f"{name!r}: {', '.join(log)} sent although the confirmation dialog was cancelled")
            elif not new["undo"]:
                issues.append(f"{name!r} deletes at once ({', '.join(log)}): no confirmation, no undo")
            continue
        if dialogs or new["yes"] is None:
            continue  # asked by confirm() and nothing sent, or not destructive at all
        if new["typed"] and new["typed"]["word"]:
            page.locator(f'[data-a11y-new="{new["typed"]["i"]}"]').fill(new["typed"]["word"])
        page.locator(f'[data-a11y-new="{new["yes"]}"]').first.click()
        settle(page)
        checked += log
    for pattern in EXPECTED_DESTRUCTIVE.get(page_id, []):
        if not any(re.search(pattern, x) for x in checked):
            issues.append(f"no control found that sends {pattern!r}: destructive action missing or not checked")
    assert_no_issues(issues, f"{page_id} [en]", "error-prevention")
