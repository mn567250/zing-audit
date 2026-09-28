"""The v2 report view (zing/web/static/v2/report.js), evaluated under node."""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_JS = r"""
const path = require("path");
const [dir, lang, reportJson] = process.argv.slice(1);
global.window = { addEventListener() {} };
global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete",
                    querySelectorAll: () => [], addEventListener() {} };
global.localStorage = { getItem: () => lang, setItem() {} };
require(path.join(dir, "locales.js"));
require(path.join(dir, "lang.js"));
require(path.join(dir, "i18n.js"));
require(path.join(dir, "icons.js"));
require(path.join(dir, "v2", "report.js"));
const el = { querySelectorAll: () => [], querySelector: () => null };
let clicked = null;
window.ZingReport.render(el, JSON.parse(reportJson), { actions: [
  { zh: "再测一个", en: "Test another" },
  { zh: "下载报告 (JSON)", en: "Download report (JSON)", primary: true, onClick: r => { clicked = r.mode; } },
] });
console.log(JSON.stringify({ html: el.innerHTML, globals: Object.keys(window), icons: window.ZING_ICONS }));
"""

_STATIC = Path(__file__).resolve().parent.parent / "zing" / "web" / "static"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "web_report.json"


def _render(tmp_path: Path, lang: str, report: dict) -> dict:
    from zing.i18n import locales_script

    (tmp_path / "locales.js").write_text(locales_script(), encoding="utf-8")
    for name in ("lang.js", "i18n.js", "icons.js"):
        shutil.copy(_STATIC / name, tmp_path / name)
    (tmp_path / "v2").mkdir(exist_ok=True)
    shutil.copy(_STATIC / "v2" / "report.js", tmp_path / "v2" / "report.js")
    out = subprocess.run(
        ["node", "-e", _JS, str(tmp_path), lang, json.dumps(report)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")


@needs_node
def test_report_severity_dots_meters_and_summary(tmp_path):
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    out = _render(tmp_path, "en", report)
    html = out["html"]
    # dot colour and glyph come from the severity: no amber dot with a red cross
    glyph_for = {"bad": "x", "warn": "warning", "sky": "info"}
    dots = re.findall(r'<span class="dot (\w+)" aria-hidden="true">(.*?)</span>', html)
    assert {c for c, _ in dots} == {"bad", "warn"}
    for colour, glyph in dots:
        assert glyph == out["icons"][glyph_for[colour]], colour
    assert "Severity: High." in html and "Severity: Medium." in html
    # dimensions: meters with values, not-run dimensions skipped, counts translated
    assert html.count('role="meter"') == 8
    assert 'aria-valuenow="93"' in html or 'aria-valuenow="92"' in html
    assert "8 dimensions" in html and "findings" in html
    # the risk pill uses the shared vocabulary; the summary drops score + disclaimer
    assert "Bait-and-switch" in html
    summary = re.search(r'<p class="sum">(.*?)</p>', html).group(1)
    assert "Overall health score" not in summary and "black-box" not in summary
    assert "Findings: 4 high, 5 medium." in summary
    # evidence toggles are accessible, actions sit in the card footer
    assert 'aria-expanded="false" aria-controls="zr-ev-' in html
    foot = html[html.index('<footer class="zr-foot">'):]
    assert 'data-action="1"' in foot and "Download report (JSON)" in foot
    assert [g for g in out["globals"] if g.startswith("Zing")] == ["ZingReport"]


@needs_node
@pytest.mark.parametrize("lang", ["zh", "fr", "es", "pt", "it", "de"])
def test_report_is_translated(tmp_path, lang):
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    html = _render(tmp_path, lang, report)["html"]
    text = _text(html)
    for en in ("Per-dimension checks", "Severity:", "Show evidence", "Bait-and-switch",
               "Overall health score", "Claimed model", "Test another"):
        assert en not in text, (lang, en)
    summary = re.search(r'<p class="sum">(.*?)</p>', html).group(1)
    assert "52" not in summary  # no repeated score line
    assert not re.search(r"\b(HIGH|MEDIUM|FAIL|PASS)\b", text)


@needs_node
def test_report_clean_and_translated_summary(tmp_path):
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    clean = copy.deepcopy(report)
    clean["verdict"].update(risk_level="clean", rating="A", overall_score=96.0)
    for det in clean["detectors"]:
        det["findings"] = []
    # a summary already translated by exportReport (e.g. re-imported in French)
    clean["verdict"]["summary"] = (
        "Score de santé global 96/100. Aucun écart significatif constaté. "
        "zing rapporte des preuves boîte noire d'écart et de risque, pas une preuve de fraude."
    )
    html = _render(tmp_path, "en", clean)["html"]
    summary = re.search(r'<p class="sum">(.*?)</p>', html).group(1)
    assert "Score de santé" not in summary and "boîte noire" not in summary
    assert "No warnings or failures" in html
    assert "Consistent (likely genuine)" in html
