"""9.4.1.1 Parsing (WCAG 2.1 4.1.1), still listed in EN 301 549 / BITV 2.0.

WCAG 2.2 retired the criterion because browsers repair markup the same way,
but a BITV test still asks for it. Checked in two places:

- the HTML the server sends for every v2 page: complete start and end tags,
  elements nested according to their end tags, no duplicate attributes;
- the DOM after rendering, in every language and with every disclosure
  opened (scripts build most of the UI): no duplicate ids.
"""

from __future__ import annotations

from html.parser import HTMLParser

import httpx
import pytest

from tests.a11y.harness import LANGS, PAGES, assert_no_issues, expand_all

PAGE_IDS = list(PAGES)

# elements that never have an end tag, and those whose end tag may be omitted
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
OPTIONAL_END = {"li", "dt", "dd", "p", "tr", "td", "th", "thead", "tbody", "tfoot", "option", "optgroup", "colgroup"}


class _Checker(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []
        self.issues: list[str] = []

    def _attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = [a for a, _ in attrs]
        dup = sorted({a for a in names if names.count(a) > 1})
        if dup:
            self.issues.append(f"line {self.getpos()[0]}: <{tag}> repeats attribute(s) {', '.join(dup)}")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._attrs(tag, attrs)
        if tag not in VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._attrs(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        open_tags = [t for t, _ in self.stack]
        if tag not in open_tags:
            self.issues.append(f"line {self.getpos()[0]}: </{tag}> closes nothing")
            return
        while self.stack:
            t, line = self.stack.pop()
            if t == tag:
                return
            if t not in OPTIONAL_END:
                self.issues.append(f"line {self.getpos()[0]}: </{tag}> closes <{t}> from line {line} that was never closed")

    def close(self) -> None:
        super().close()
        for t, line in self.stack:
            if t not in OPTIONAL_END | {"html", "body", "head"}:
                self.issues.append(f"line {line}: <{t}> is never closed")


def check_markup(html: str) -> list[str]:
    c = _Checker()
    c.feed(html)
    c.close()
    return c.issues


@pytest.mark.bitv("9.4.1.1")
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_served_markup_is_well_formed(base_url: str, page_id: str) -> None:
    r = httpx.get(base_url + PAGES[page_id], timeout=10, follow_redirects=True)
    assert r.status_code == 200
    assert_no_issues(check_markup(r.text), f"{page_id} (served HTML)", "parsing")


DUP_IDS_JS = """
() => {
  const seen = {};
  for (const el of document.querySelectorAll('[id]')) seen[el.id] = (seen[el.id] || 0) + 1;
  return Object.entries(seen).filter(([, n]) => n > 1).map(([id, n]) => `id "${id}" is used ${n} times`);
}
"""


@pytest.mark.bitv("9.4.1.1")
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("page_id", PAGE_IDS)
def test_rendered_ids_are_unique(open_page, page_id: str, lang: str) -> None:
    page = open_page(PAGES[page_id], lang)
    expand_all(page)
    assert_no_issues(page.evaluate(DUP_IDS_JS), f"{page_id} [{lang}] rendered DOM", "parsing")


def test_checker_catches_broken_markup() -> None:
    """The markup check itself fails on the errors it is meant to find."""
    assert check_markup("<div><span>x</div>") == ["line 1: </div> closes <span> from line 1 that was never closed"]
    assert check_markup('<p class="a" class="b">x</p>') == ["line 1: <p> repeats attribute(s) class"]
    assert check_markup("<section><p>x") == ["line 1: <section> is never closed"]
    assert check_markup("<ul><li>a<li>b</ul><br><img src=x>") == []
