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
    # findings: dot colour and glyph come from the severity: no amber dot with a red cross
    glyph_for = {"bad": "x", "warn": "warning", "sky": "info"}
    findings = html[html.index("<h3>Findings"):]
    dots = re.findall(r'<span class="dot (\w+)" aria-hidden="true">(.*?)</span>', findings)
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


async def _scored_report() -> dict:
    # the transparency tests' report: protocol (published scale, one check not
    # counted, one medium finding) + determinism (no scale) in one dimension
    from tests.test_scoring_transparency import _report

    return json.loads((await _report()).model_dump_json())


def _panel(html: str) -> str:
    start = html.index('<div class="zr-dd"')
    return html[start:html.index('<div class="zr-dimw">', start) if '<div class="zr-dimw">' in html[start:] else None]


@needs_node
async def test_dimension_rows_expand_into_scoring_details(tmp_path):
    report = await _scored_report()
    html = _render(tmp_path, "en", report)["html"]
    # one disclosure per scored dimension, collapsed, controlling its panel
    toggles = re.findall(r'<button type="button" class="dtog" aria-expanded="false" aria-controls="(zr-dd-\d+)">', html)
    assert len(toggles) == 1 and f'id="{toggles[0]}" role="region"' in html
    assert html.count('role="meter"') == 1
    panel = _text(_panel(html))
    assert "Score: mean of 2 detectors, equal weight." in panel
    assert "Status: the worst status its detectors concluded." in panel
    assert "Score 85" in panel and "Score 100" in panel
    assert "Detector score: mean of the counted checks' points." in panel
    # every check, positive and negative, with the outcome and its points
    assert "Multi-turn conversation memory 55 pts" in " ".join(panel.split())
    assert "The color from an earlier turn was not recalled." in panel
    assert "Not counted" in panel and "Result: Pass." in panel
    assert "Output varies at temperature=1.0" in panel  # a detector without a scale
    dots = set(re.findall(r'<span class="dot (\w+)"', _panel(html)))
    assert {"good", "warn", "grey"} <= dots
    # the published scale, collapsed, with this run's outcome marked
    assert 'class="linkbtn scl" aria-expanded="false"' in html and "Show scoring scale" in html
    assert "The invalid request was accepted (2xx)." in panel
    assert re.search(r'<li class="hit"><span class="p">100 pts</span><span>Rejected with a 4xx and an OpenAI-style', html)
    assert html.count("This run") == 4  # one hit per check, the not-counted one included


@needs_node
async def test_dimension_details_explain_a_status_override(tmp_path):
    report = await _scored_report()
    dim = next(d for d in report["dimensions"] if d["dimension"] == "protocol")
    dim["status"] = "warn"
    dim["breakdown"]["detector_status"] = "pass"
    dim["breakdown"]["status_override"] = {"from_status": "pass", "to_status": "warn",
                                           "severity": "medium", "findings": ["protocol.multi_turn"]}
    panel = _text(_panel(_render(tmp_path, "en", report)["html"]))
    assert ("Status raised from Pass to Warning by findings of severity Medium: "
            "Multi-turn conversation memory.") in " ".join(panel.split())


@needs_node
@pytest.mark.parametrize(("lang", "points"), [("zh", "55 分"), ("de", "55 Pkt."), ("fr", "55 pts")])
async def test_dimension_details_are_translated(tmp_path, lang, points):
    html = _render(tmp_path, lang, await _scored_report())["html"]
    panel = _text(_panel(html))
    for en in ("Score: mean of", "Not counted", "Show scoring scale", "This run",
               "The invalid request was accepted", "Detector score", "Result:"):
        assert en not in panel, (lang, en)
    assert f'<span class="pts">{points}</span>' in html


@needs_node
def test_old_reports_still_expand(tmp_path):
    # reports from before the breakdown/scale existed: detectors and findings
    report = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    html = _render(tmp_path, "en", report)["html"]
    assert html.count('class="dtog"') == 8
    assert "Score: mean of" in html or "Score from one detector." in html
    assert "Status: the worst status" not in html  # needs the breakdown
    assert not re.search(r"\d pts\b", _text(html))  # no points without a published scale
