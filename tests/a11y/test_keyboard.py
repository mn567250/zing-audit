"""Keyboard operation (BITV 9.2.1.1, 9.2.1.2, 9.2.4.3, 9.2.4.7, 9.3.2.1, 9.1.4.13).

What axe cannot see: the page is walked with the Tab key like a keyboard user
would, every control must be reached, focus must stay visible and on screen,
nothing may trap or move the user, popups close with Escape and composite
widgets (tabs) follow the ARIA keyboard pattern.
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page

from tests.a11y.harness import LANGS, PAGES, THEMES, assert_no_issues, expand_all, settle, to_top

PAGE_IDS = list(PAGES)

# Every element that should be a Tab stop, tagged with data-a11y-i, plus a
# readable description. Native radio groups are one stop; elements inside
# [inert]/aria-hidden/hidden/disabled are not stops.
TAB_STOPS_JS = """
() => {
  const sel = 'a[href], button, input, select, textarea, summary, iframe, [tabindex], [contenteditable=""], [contenteditable=true]';
  const visible = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const radios = new Set();
  const out = [];
  let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (el.tabIndex < 0 || el.disabled || el.closest('[inert], [aria-hidden=true], [hidden]')) continue;
    if (el.matches('input[type=hidden]') || !visible(el)) continue;
    if (el.closest('details:not([open])') && !el.matches('details > summary')) continue;
    if (el.matches('input[type=radio]')) {
      const key = (el.form ? 'f' : '') + el.name;
      if (el.name && radios.has(key)) continue;
      radios.add(key);
    }
    el.setAttribute('data-a11y-i', String(i++));
    out.push(describeEl(el));
  }
  return out;
  function describeEl(el) {
    const name = (el.getAttribute('aria-label') || el.textContent || el.getAttribute('placeholder') || el.name || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
    return `<${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : ''}> "${name}"`;
  }
}
"""

ACTIVE_JS = """
() => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  const r = el.getBoundingClientRect(), s = getComputedStyle(el);
  const name = (el.getAttribute('aria-label') || el.textContent || el.getAttribute('placeholder') || el.name || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
  return {
    i: el.getAttribute('data-a11y-i'),
    desc: `<${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}> "${name}"`,
    box: [r.x, r.y, r.width, r.height],
    shown: r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.opacity !== '0'
           && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth,
  };
}
"""


def walk_tab_order(page: Page, limit: int) -> tuple[list[dict[str, Any]], bool]:
    """Press Tab until focus leaves the page; returns the visited stops and
    whether it ever left (False = trapped or cycling)."""
    to_top(page)
    visited: list[dict[str, Any]] = []
    for _ in range(limit):
        page.keyboard.press("Tab")
        cur = page.evaluate(ACTIVE_JS)
        if cur is None:
            return visited, True
        visited.append(cur)
    return visited, False


def prepare(open_page: Any, page_id: str, lang: str = "en", theme: str = "light") -> tuple[Page, list[str]]:
    page = open_page(PAGES[page_id], lang, theme)
    expand_all(page)
    page.mouse.move(0, 0)
    return page, page.evaluate(TAB_STOPS_JS)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_every_control_reachable_by_tab_without_trap(open_page, page_id: str, lang: str) -> None:
    """9.2.1.1 Keyboard, 9.2.1.2 No keyboard trap, 9.3.2.1 On focus."""
    page, stops = prepare(open_page, page_id, lang)
    url = page.url
    visited, left = walk_tab_order(page, len(stops) * 2 + 20)
    issues: list[str] = []
    if not left:
        tail = ", ".join(v["desc"] for v in visited[-6:])
        issues.append(f"focus never leaves the page after {len(visited)} Tab presses (trap or cycle): … {tail}")
    reached = {v["i"] for v in visited if v["i"] is not None}
    for i, desc in enumerate(stops):
        if str(i) not in reached:
            issues.append(f"not reachable with Tab: {desc}")
    if page.url.split("#")[0] != url.split("#")[0]:
        issues.append(f"moving focus navigated the page to {page.url} (9.3.2.1 On focus)")
    if len(page.context.pages) > 1:
        issues.append("moving focus opened a new window (9.3.2.1 On focus)")
    assert_no_issues(issues, f"{page_id} [{lang}]", "keyboard")


@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_focused_element_is_on_screen(open_page, page_id: str) -> None:
    """9.2.4.3 Focus order / 9.2.4.7 Focus visible: never focus something unseen."""
    page, stops = prepare(open_page, page_id)
    visited, _ = walk_tab_order(page, len(stops) * 2 + 20)
    issues = [f"focused but not visible on screen: {v['desc']} at {v['box']}" for v in visited if not v["shown"]]
    assert_no_issues(issues, f"{page_id} [en]", "keyboard")


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_focus_is_visible(open_page, page_id: str, theme: str) -> None:
    """9.2.4.7 Focus visible: each Tab stop looks different with and without focus."""
    page, stops = prepare(open_page, page_id, "en", theme)
    to_top(page)
    issues: list[str] = []
    seen: set[str] = set()
    for _ in range(len(stops) + 10):
        page.keyboard.press("Tab")
        cur = page.evaluate(ACTIVE_JS)
        if cur is None or cur["i"] is None or cur["i"] in seen:
            if cur is None:
                break
            continue
        seen.add(cur["i"])
        if not cur["shown"]:
            continue
        x, y, w, h = cur["box"]
        clip = {"x": max(x - 6, 0), "y": max(y - 6, 0), "width": w + 12, "height": h + 12}
        focused = page.screenshot(clip=clip, animations="disabled", caret="hide")
        page.evaluate("() => document.activeElement.blur()")
        plain = page.screenshot(clip=clip, animations="disabled", caret="hide")
        page.evaluate(
            "i => { const el = document.querySelector(`[data-a11y-i=\"${i}\"]`); el && el.focus({ preventScroll: true }); }",
            cur["i"],
        )
        if focused == plain:
            issues.append(f"no visible focus indicator: {cur['desc']}")
    assert_no_issues(issues, f"{page_id} [en, {theme}]", "focus-visible")


POPUP_TRIGGERS_JS = """
() => [...document.querySelectorAll('[aria-haspopup]:not([aria-haspopup=false])')]
  .filter(el => el.getBoundingClientRect().width > 0 && !el.disabled)
  .map((el, i) => { el.setAttribute('data-a11y-pop', String(i)); return i; })
"""


@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_popups_close_with_escape_and_return_focus(open_page, page_id: str) -> None:
    """9.2.1.1 Keyboard / 9.1.4.13: menus and popups open with Enter, close with
    Escape, and focus goes back to the button that opened them."""
    page = open_page(PAGES[page_id])
    issues: list[str] = []
    for i in page.evaluate(POPUP_TRIGGERS_JS):
        trig = page.locator(f'[data-a11y-pop="{i}"]')
        name = trig.evaluate("el => el.getAttribute('aria-label') || el.textContent.trim().slice(0, 40)")
        trig.focus()
        page.keyboard.press("Enter")
        settle(page)
        if trig.get_attribute("aria-expanded") != "true":
            issues.append(f"popup button does not open with Enter (aria-expanded): {name!r}")
            continue
        page.keyboard.press("Escape")
        settle(page)
        if trig.get_attribute("aria-expanded") == "true":
            issues.append(f"popup does not close with Escape: {name!r}")
        elif not trig.evaluate("el => el === document.activeElement"):
            issues.append(f"focus does not return to the popup button after Escape: {name!r}")
    assert_no_issues(issues, f"{page_id} [en]", "keyboard")


@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_dialogs_close_with_escape(open_page, page_id: str) -> None:
    """Open modal dialogs take focus and close with Escape (9.2.1.1, 9.2.4.3)."""
    page = open_page(PAGES[page_id])
    expand_all(page)
    issues: list[str] = []
    dialogs = page.locator("dialog[open], [role=dialog]:visible, [role=alertdialog]:visible")
    for k in range(dialogs.count()):
        d = dialogs.nth(k)
        if not d.is_visible():
            continue
        modal = d.evaluate("el => el.matches(':modal') || el.getAttribute('aria-modal') === 'true'")
        if not modal:
            continue
        if not d.evaluate("el => el.contains(document.activeElement)"):
            issues.append("an open modal dialog does not hold the focus")
        page.keyboard.press("Escape")
        settle(page)
        if d.is_visible():
            issues.append("an open modal dialog does not close with Escape")
    assert_no_issues(issues, f"{page_id} [en]", "keyboard")


@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_tabs_follow_arrow_key_pattern(open_page, page_id: str) -> None:
    """ARIA tabs: one Tab stop per tablist, arrow keys move between tabs and
    select them (9.2.1.1 Keyboard, 9.4.1.2 Name, role, value)."""
    page = open_page(PAGES[page_id])
    issues: list[str] = []
    lists = page.locator("[role=tablist]")
    for k in range(lists.count()):
        tl = lists.nth(k)
        if not tl.is_visible():
            continue
        tabs = tl.locator("[role=tab]")
        n = tabs.count()
        if n < 2:
            continue
        in_order = tl.evaluate("el => [...el.querySelectorAll('[role=tab]')].filter(t => t.tabIndex >= 0).length")
        if in_order != 1:
            issues.append(f"tablist {k}: {in_order} tabs are Tab stops (expected 1, the selected tab)")
        sel = tl.locator("[role=tab][aria-selected=true]").first
        if not sel.count():
            issues.append(f"tablist {k}: no tab has aria-selected=true")
            continue
        sel.focus()
        before = sel.evaluate("el => el.id || el.textContent.trim()")
        page.keyboard.press("ArrowRight")
        settle(page)
        after = page.evaluate("() => document.activeElement.getAttribute('role') === 'tab' ? (document.activeElement.id || document.activeElement.textContent.trim()) : null")
        if after is None or after == before:
            issues.append(f"tablist {k}: ArrowRight does not move focus to the next tab")
        else:
            if page.evaluate("() => document.activeElement.getAttribute('aria-selected')") != "true":
                issues.append(f"tablist {k}: the tab focused with ArrowRight is not selected")
            page.keyboard.press("ArrowLeft")
            back = page.evaluate("() => document.activeElement.id || document.activeElement.textContent.trim()")
            if back != before:
                issues.append(f"tablist {k}: ArrowLeft does not move focus back")
        for key in ("Home", "End"):
            page.keyboard.press(key)
        if page.evaluate("() => document.activeElement.getAttribute('role')") != "tab":
            issues.append(f"tablist {k}: Home/End move focus out of the tablist")
    assert_no_issues(issues, f"{page_id} [en]", "keyboard")


TOOLTIP_TRIGGERS_JS = """
() => {
  const out = [];
  document.querySelectorAll('[aria-describedby]').forEach((el, i) => {
    const ids = el.getAttribute('aria-describedby').split(/\\s+/);
    const tip = ids.map(id => document.getElementById(id)).find(t => t && t.getAttribute('role') === 'tooltip');
    if (tip && el.getBoundingClientRect().width > 0) { el.setAttribute('data-a11y-tip', String(i)); out.push([i, tip.id]); }
  });
  return out;
}
"""


@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_tooltips_dismissible_hoverable_persistent(open_page, page_id: str) -> None:
    """9.1.4.13 Content on hover or focus."""
    page = open_page(PAGES[page_id])
    expand_all(page)
    issues: list[str] = []
    for i, tip_id in page.evaluate(TOOLTIP_TRIGGERS_JS):
        trig = page.locator(f'[data-a11y-tip="{i}"]')
        tip = page.locator(f"#{tip_id}")
        trig.focus()
        settle(page)
        if not tip.is_visible():
            issues.append(f"tooltip #{tip_id} does not show on keyboard focus")
            continue
        page.keyboard.press("Escape")
        settle(page)
        if tip.is_visible():
            issues.append(f"tooltip #{tip_id} cannot be dismissed with Escape")
        trig.hover()
        settle(page)
        if tip.is_visible():
            box = tip.bounding_box()
            if box:
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=4)
                settle(page)
                if not tip.is_visible():
                    issues.append(f"tooltip #{tip_id} disappears when the pointer moves onto it")
    assert_no_issues(issues, f"{page_id} [en]", "hover-focus")
