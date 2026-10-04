"""Layout, zoom, spacing, motion and contrast checks axe does not cover.

BITV 9.1.3.4 Orientation, 9.1.4.4 Resize text, 9.1.4.10 Reflow,
9.1.4.11 Non-text contrast, 9.1.4.12 Text spacing, 9.2.2.2 Pause/stop/hide,
9.2.3.3-style reduced motion (best practice), forced colours (EN 301 549
11.7 user preferences, applied to the web as a best practice).
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page

from tests.a11y.harness import LANGS, PAGES, THEMES, assert_no_issues, expand_all, settle, to_top

PAGE_IDS = list(PAGES)

DESCRIBE = """
const describeEl = el => {
  const t = (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
  const cls = typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\\s+/).join('.') : '';
  return `<${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${cls}> "${t}"`;
};
"""

HSCROLL_JS = (
    """
() => {
  """
    + DESCRIBE
    + """
  const doc = document.scrollingElement || document.documentElement;
  const vw = doc.clientWidth;
  if (doc.scrollWidth <= vw + 1) return [];
  // name the widest offenders that are not inside their own scroll container
  const out = [];
  for (const el of document.body.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.right <= vw + 1) continue;
    let p = el.parentElement, scrolled = false;
    while (p && p !== document.body) {
      const o = getComputedStyle(p).overflowX;
      if (o === 'auto' || o === 'scroll' || o === 'hidden' || o === 'clip') { scrolled = true; break; }
      p = p.parentElement;
    }
    if (!scrolled && !(el.parentElement && el.parentElement.getBoundingClientRect().right > vw + 1)) out.push(describeEl(el) + ` right edge ${Math.round(r.right)}px`);
  }
  return [`page scrolls horizontally: ${doc.scrollWidth}px content in a ${vw}px viewport`].concat(out.slice(0, 10));
}
"""
)

CLIPPED_JS = (
    """
() => {
  """
    + DESCRIBE
    + """
  const out = [];
  for (const el of document.body.querySelectorAll('*')) {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 2 || r.height <= 2) continue;               // visually-hidden helpers
    if (s.position === 'absolute' && s.clip && s.clip !== 'auto') continue;
    if (el.closest('[aria-hidden=true], svg, canvas')) continue;
    const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    const fx = s.overflowX, fy = s.overflowY;
    const cutX = (fx === 'hidden' || fx === 'clip') && el.scrollWidth > el.clientWidth + 1;
    const cutY = (fy === 'hidden' || fy === 'clip') && el.scrollHeight > el.clientHeight + 1;
    if (!(cutX || cutY)) continue;
    if (!hasText && !el.querySelector('*')) continue;
    if (!(el.innerText || '').trim()) continue;
    out.push(`text cut off (${cutX ? 'width' : 'height'}${s.textOverflow === 'ellipsis' ? ', ellipsis' : ''}): ${describeEl(el)}`);
  }
  return out;
}
"""
)

TEXT_SPACING_CSS = """
* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }
p { margin-bottom: 2em !important; }
"""


def _issues_after(page: Page) -> list[str]:
    settle(page)
    return list(page.evaluate(HSCROLL_JS)) + list(page.evaluate(CLIPPED_JS))


@pytest.mark.bitv("9.1.4.10")
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_reflow_at_320_css_px(open_page, page_id: str, lang: str) -> None:
    """9.1.4.10 Reflow: 320 CSS px wide (= 1280 px at 400 %), no 2-D scrolling,
    nothing cut off. Long translations (de, fr, pt) are the usual offenders."""
    page = open_page(PAGES[page_id], lang, viewport={"width": 320, "height": 640})
    expand_all(page)
    assert_no_issues(_issues_after(page), f"{page_id} [{lang}] at 320 px", "reflow")


@pytest.mark.bitv("9.1.4.4")
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_resize_text_200_percent(open_page, page_id: str, lang: str) -> None:
    """9.1.4.4 Resize text: browser zoom 200 % on a 1280 px screen (= 640 CSS px
    at device scale 2) keeps every text readable."""
    page = open_page(PAGES[page_id], lang, viewport={"width": 640, "height": 450}, device_scale_factor=2)
    expand_all(page)
    assert_no_issues(_issues_after(page), f"{page_id} [{lang}] at 200 % zoom", "resize-text")


@pytest.mark.bitv("9.1.4.12")
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_text_spacing_override(open_page, page_id: str, lang: str) -> None:
    """9.1.4.12 Text spacing: WCAG's spacing bookmarklet values lose no content."""
    page = open_page(PAGES[page_id], lang)
    expand_all(page)
    page.add_style_tag(content=TEXT_SPACING_CSS)
    assert_no_issues(_issues_after(page), f"{page_id} [{lang}] with text spacing", "text-spacing")
    small = open_page(PAGES[page_id], lang, viewport={"width": 375, "height": 700})
    expand_all(small)
    small.add_style_tag(content=TEXT_SPACING_CSS)
    assert_no_issues(_issues_after(small), f"{page_id} [{lang}] with text spacing at 375 px", "text-spacing")


@pytest.mark.bitv("9.1.3.4")
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_orientation_not_locked(open_page, page_id: str) -> None:
    """9.1.3.4 Orientation: works in portrait and landscape phone sizes."""
    issues: list[str] = []
    for vp in ({"width": 390, "height": 844}, {"width": 844, "height": 390}):
        page = open_page(PAGES[page_id], viewport=vp)
        main_h = page.evaluate("() => { const m = document.querySelector('main') || document.body; return m.getBoundingClientRect().height; }")
        if main_h < 50:
            issues.append(f"{vp['width']}x{vp['height']}: main content is not shown")
        locked = page.evaluate(
            "() => { const t = getComputedStyle(document.documentElement).transform + getComputedStyle(document.body).transform; return /matrix\\(0, 1|matrix\\(0, -1/.test(t); }"
        )
        if locked:
            issues.append(f"{vp['width']}x{vp['height']}: page is rotated to force an orientation")
        issues += [f"{vp['width']}x{vp['height']}: {m}" for m in page.evaluate(HSCROLL_JS)]
    assert_no_issues(issues, f"{page_id} [en]", "orientation")


ANIMATIONS_JS = """
() => document.getAnimations()
  .filter(a => a.playState === 'running')
  .map(a => {
    const t = a.effect.getComputedTiming(), el = a.effect.target;
    const vis = el && el.getBoundingClientRect && el.getBoundingClientRect().width > 0;
    return { name: a.animationName || a.transitionProperty || a.constructor.name, infinite: t.iterations === Infinity,
             duration: t.duration, visible: !!vis,
             el: el ? `<${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${typeof el.className === 'string' && el.className ? '.' + el.className.split(' ').join('.') : ''}>` : '?' };
  })
"""


@pytest.mark.bitv("9.2.2.2")
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_reduced_motion_is_respected(open_page, page_id: str) -> None:
    """prefers-reduced-motion: no animation runs longer than 200 ms or loops
    (supports 9.2.2.2 Pause, stop, hide and WCAG 2.3.3)."""
    page = open_page(PAGES[page_id], reduced_motion="reduce")
    expand_all(page)
    anims: list[dict[str, Any]] = page.evaluate(ANIMATIONS_JS)
    issues = [
        f"{a['name']} on {a['el']} ({'infinite' if a['infinite'] else str(a['duration']) + ' ms'})"
        for a in anims
        if a["visible"] and (a["infinite"] or (isinstance(a["duration"], (int, float)) and a["duration"] > 200))
    ]
    assert_no_issues(issues, f"{page_id} [en] with reduced motion", "reduced-motion")


@pytest.mark.bitv("9.2.2.2")
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_no_endless_animation_at_rest(open_page, page_id: str) -> None:
    """9.2.2.2 Pause, stop, hide: nothing moves forever on an idle page."""
    page = open_page(PAGES[page_id])
    page.wait_for_timeout(500)
    anims: list[dict[str, Any]] = page.evaluate(ANIMATIONS_JS)
    issues = [f"{a['name']} loops on {a['el']}" for a in anims if a["visible"] and a["infinite"]]
    assert_no_issues(issues, f"{page_id} [en] idle", "pause-stop-hide")


# --------------------------------------------------------------------------- #
# colour
# --------------------------------------------------------------------------- #
COLOR_LIB = """
const parse = c => { const m = /rgba?\\(([^)]+)\\)/.exec(c || ''); if (!m) return null;
  const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
const over = (fg, bg) => [0, 1, 2].map(i => fg[i] * fg[3] + bg[i] * (1 - fg[3])).concat([1]);
const bgOf = el => { const stack = []; for (let p = el; p && p.nodeType === 1; p = p.parentElement) {
    const c = parse(getComputedStyle(p).backgroundColor); if (c && c[3] > 0) { stack.push(c); if (c[3] >= 1) break; } }
  let bg = parse(getComputedStyle(document.documentElement).backgroundColor) || [255, 255, 255, 1];
  if (bg[3] < 1) bg = over(bg, [255, 255, 255, 1]);
  for (const c of stack.reverse()) bg = over(c, bg); return bg; };
"""

CONTROL_BOUNDARY_JS = (
    """
() => {
  """
    + COLOR_LIB
    + DESCRIBE
    + """
  const out = [];
  const sel = 'input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]), select, textarea, [role=switch], [role=checkbox], [role=radio], [role=slider]';
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect(); if (r.width < 3 || r.height < 3) continue;
    const s = getComputedStyle(el); if (s.visibility === 'hidden' || s.display === 'none' || el.disabled) continue;
    if (s.appearance !== 'none' && /checkbox|radio|range|color/.test(el.type || '')) continue;  // native widget, UA-drawn
    const around = bgOf(el.parentElement || document.body);
    let best = 1;
    const own = parse(s.backgroundColor);
    if (own && own[3] > 0) best = Math.max(best, ratio(over(own, around), around));
    for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
      if (parseFloat(s['border' + side + 'Width']) >= 1 && s['border' + side + 'Style'] !== 'none') {
        const c = parse(s['border' + side + 'Color']); if (c) best = Math.max(best, ratio(over(c, around), around));
      }
    }
    const sh = parse(s.boxShadow); if (sh && s.boxShadow !== 'none') best = Math.max(best, ratio(over(sh, around), around));
    if (best < 3) out.push(`control boundary contrast ${best.toFixed(2)}:1 < 3:1: ${describeEl(el)}`);
  }
  return out;
}
"""
)

NO_TRANSITIONS_CSS = "*, *::before, *::after { transition: none !important; animation: none !important; }"

FOCUS_RING_JS = (
    """
() => {
  """
    + COLOR_LIB
    + DESCRIBE
    + """
  const el = document.activeElement; if (!el || el === document.body) return null;
  const s = getComputedStyle(el);
  const around = bgOf(el.parentElement || document.body);
  const cands = [];
  if (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 1) cands.push(parse(s.outlineColor));
  if (s.boxShadow && s.boxShadow !== 'none') cands.push(parse(s.boxShadow));
  // a border that changes colour on focus is an indicator too
  const sides = ['Top', 'Right', 'Bottom', 'Left'].filter(sd => parseFloat(s['border' + sd + 'Width']) >= 1 && s['border' + sd + 'Style'] !== 'none');
  const focusedBorders = sides.map(sd => s['border' + sd + 'Color']);
  el.blur();
  const plain = getComputedStyle(el);
  const changed = sides.filter((sd, k) => plain['border' + sd + 'Color'] !== focusedBorders[k]);
  el.focus({ preventScroll: true });
  if (changed.length === sides.length && sides.length) cands.push(...focusedBorders.map(parse));
  const best = Math.max(0, ...cands.filter(Boolean).map(c => ratio(over(c, around), around)));
  return { desc: describeEl(el), best, i: el.getAttribute('data-a11y-i') };
}
"""
)


@pytest.mark.bitv("9.1.4.11")
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_form_control_boundaries_contrast(open_page, page_id: str, theme: str) -> None:
    """9.1.4.11 Non-text contrast: inputs, selects and switches are visibly
    delimited (3:1 against what is around them)."""
    page = open_page(PAGES[page_id], "en", theme)
    expand_all(page)
    page.add_style_tag(content=NO_TRANSITIONS_CSS)
    assert_no_issues(page.evaluate(CONTROL_BOUNDARY_JS), f"{page_id} [en, {theme}]", "non-text-contrast")


@pytest.mark.bitv("9.1.4.11")
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_focus_indicator_contrast(open_page, page_id: str, theme: str) -> None:
    """9.1.4.11 Non-text contrast of the focus indicator (outline or ring
    reaches 3:1 against the background) for every Tab stop."""
    page = open_page(PAGES[page_id], "en", theme)
    expand_all(page)
    page.add_style_tag(content=NO_TRANSITIONS_CSS)  # measure the end state, not a fade-in
    page.mouse.move(0, 0)
    to_top(page)
    issues: list[str] = []
    seen: set[str] = set()
    for _ in range(400):
        page.keyboard.press("Tab")
        cur = page.evaluate(FOCUS_RING_JS)
        if cur is None:
            break
        if cur["desc"] in seen:
            continue
        seen.add(cur["desc"])
        if cur["best"] < 3:
            issues.append(f"focus indicator contrast {cur['best']:.2f}:1 < 3:1: {cur['desc']}")
    assert_no_issues(issues, f"{page_id} [en, {theme}]", "focus-contrast")


FORCED_COLORS_JS = (
    """
() => {
  """
    + DESCRIBE
    + """
  const out = [];
  const sel = 'button, a[href], [role=button], [role=tab], [role=switch], input:not([type=hidden]), select, textarea';
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect(); if (r.width < 3 || r.height < 3) continue;
    const s = getComputedStyle(el); if (s.visibility === 'hidden') continue;
    const text = (el.innerText || el.value || '').trim();
    const graphic = el.querySelector('svg, img, canvas');
    if (!text && !graphic && !/^(input|select|textarea)$/i.test(el.tagName)) out.push(`control has no visible content in forced colours (CSS-only icon?): ${describeEl(el)}`);
    const boxed = ['Top', 'Right', 'Bottom', 'Left'].some(sd => parseFloat(s['border' + sd + 'Width']) >= 1 && s['border' + sd + 'Style'] !== 'none');
    if (!boxed && el.matches('[role=switch], [role=tab], input:not([type=checkbox]):not([type=radio]), select, textarea'))
      out.push(`control has no border in forced colours, its shape disappears: ${describeEl(el)}`);
  }
  return out;
}
"""
)


@pytest.mark.bitv("11.7")
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_forced_colors_mode(open_page, page_id: str) -> None:
    """Windows high-contrast / forced colours: controls keep a visible shape and
    content (user colour preferences, EN 301 549 11.7 / best practice)."""
    page = open_page(PAGES[page_id], forced_colors="active")
    expand_all(page)
    assert_no_issues(page.evaluate(FORCED_COLORS_JS), f"{page_id} [en] forced colours", "forced-colors")
