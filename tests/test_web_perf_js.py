"""The web UI's performance panel (zing/web/static/perf.js), evaluated under node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from zing.models import RequestRecord
from zing.perf import build_performance

_JS = r"""
const path = require("path");
global.window = {};
global.document = undefined;  // no DOM: the style injection must be skipped
require(path.join(process.argv[1], "perf.js"));
const perf = JSON.parse(process.argv[2]);
const P = window.ZingPerf;
console.log(JSON.stringify({
  section: P.section(perf),
  empty: P.section(null),
  tps: P.chart(perf.requests, "tps"),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_perf_js_renders_section_and_chart():
    recs = [
        RequestRecord(seq=i, endpoint=ep, phase="probe", ok=True, stream=True,
                      start_ms=i * 1000.0, duration_ms=900.0, ttft_ms=250.0,
                      decode_tps_local=100.0 if ep == "target" else 50.0,
                      detector='<img src=x onerror=alert(1)>')
        for i, ep in enumerate(["target", "baseline"] * 3)
    ]
    recs.append(RequestRecord(seq=9, endpoint="target", phase="probe", ok=False, status_code=502))
    perf = build_performance(recs, has_baseline=True, probe_max_tokens=128)
    assert perf is not None
    static = Path(__file__).resolve().parent.parent / "zing" / "web" / "static"
    out = json.loads(subprocess.run(
        ["node", "-e", _JS, str(static), perf.model_dump_json()],
        capture_output=True, text=True, check=True,
    ).stdout)
    section = out["section"]
    assert out["empty"] == ""
    assert "<svg" in section and 'class="zp-pt t"' in section and 'class="zp-pt b"' in section
    assert 'class="zp-fail"' in section  # the failed request
    assert "Target vs baseline" in section and "Decode speed p50 (local)" in section
    assert "<img" not in section and "&lt;img" in section  # detector ids are escaped
    assert "zp-pt" in out["tps"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_perf_js_colors_deltas_and_shows_both_modes():
    recs = []
    for _ in range(4):
        for stream in (True, False):
            for ep, lat in (("target", 800.0), ("baseline", 1200.0)):
                recs.append(RequestRecord(
                    seq=len(recs), endpoint=ep, phase="probe", ok=True, stream=stream,
                    start_ms=len(recs) * 100.0, duration_ms=lat,
                    ttft_ms=200.0 if stream else None,
                    decode_tps_local=(40.0 if ep == "target" else 80.0) if stream else None,
                    e2e_tps_local=100.0,
                ))
    perf = build_performance(recs, has_baseline=True)
    assert perf is not None and [m.mode for m in perf.modes] == ["non_stream"]
    static = Path(__file__).resolve().parent.parent / "zing" / "web" / "static"
    section = json.loads(subprocess.run(
        ["node", "-e", _JS, str(static), perf.model_dump_json()],
        capture_output=True, text=True, check=True,
    ).stdout)["section"]
    # lower latency: better (green ✓); lower decode speed: worse (red ✗)
    assert 'class="r zp-better">✓ -400' in section
    assert 'class="r zp-worse">✗ -40.0' in section
    assert "Streaming" in section and "Non-streaming" in section
    assert 'zp-pt t hollow' in section and "non-streaming request (hollow)" in section
    assert "End-to-end speed p50" in section  # non-stream tiles


_STATIC = Path(__file__).resolve().parent.parent / "zing" / "web" / "static"


def _render(perf_json: str) -> dict:
    js = _JS.replace("tps: P.chart(perf.requests, \"tps\"),", "tps: P.chart(perf.requests, \"tps\"), css: P.CSS,")
    return json.loads(subprocess.run(
        ["node", "-e", js, str(_STATIC), perf_json], capture_output=True, text=True, check=True,
    ).stdout)


def _perf():
    recs = [
        RequestRecord(seq=i, endpoint=ep, phase="probe", ok=True, stream=True,
                      start_ms=i * 1000.0, duration_ms=900.0, ttft_ms=250.0, decode_tps_local=80.0)
        for i, ep in enumerate(["target", "baseline"] * 2)
    ]
    recs.append(RequestRecord(seq=7, endpoint="target", phase="probe", ok=False, status_code=502))
    perf = build_performance(recs, has_baseline=True, probe_max_tokens=128)
    assert perf is not None
    return perf


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_perf_js_css_colours_only_through_variables():
    import re

    css = _render(_perf().model_dump_json())["css"]
    # All colour literals live in the :where() block of --zp-* defaults.
    defaults = re.match(r":where\(\.zp-section,\.zp-live,\.zp-tip\)\{([^}]*)\}", css)
    assert defaults
    decls = dict(d.split(":", 1) for d in defaults.group(1).split(";"))
    assert all(k.startswith("--zp-") for k in decls)
    assert decls["--zp-t"] == "#2a78d6" and decls["--zp-tile"] == "#f5f8f4"  # classic values
    rest = css[defaults.end():]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|(?<![\w-])(white|black)(?![\w-])", rest)
    # v2 maps every property the injected CSS uses.
    v2 = (_STATIC / "v2" / "perf.css").read_text(encoding="utf-8")
    for prop in set(re.findall(r"var\((--zp-[\w-]+)", css)):
        assert prop + ":" in v2, prop


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_perf_js_tabs_and_chart_are_accessible():
    section = _render(_perf().model_dump_json())["section"]
    assert 'role="tablist"' in section and section.count('role="tab"') == 4
    assert 'aria-selected="true"' in section and section.count('aria-selected="false"') == 3
    assert 'tabindex="0"' in section and section.count('tabindex="-1"') == 3
    assert 'aria-controls="zp1-panel"' in section and 'role="tabpanel" id="zp1-panel"' in section
    assert 'aria-labelledby="zp1-tab-latency"' in section
    assert 'role="img" aria-label="Latency (ms) over time: 5 requests; target median 900 ms; ' \
           'baseline median 900 ms; 1 failed"' in section
    # the tooltip contents are also in a data table
    assert '<details class="zp-data">' in section and "Show data table" in section
    assert "failed (502)" in section.split('class="zp-data"')[1]


def test_perf_fragment_translates_every_key():
    base = Path(__file__).resolve().parent.parent / "zing" / "i18n" / "locales" / "fragments" / "v2-perf"
    en = json.loads((base / "en.json").read_text(encoding="utf-8"))["strings"]
    assert all(k == v for k, v in en.items())
    for code in ("fr", "es", "pt", "it", "de"):
        tr = json.loads((base / f"{code}.json").read_text(encoding="utf-8"))["strings"]
        assert set(tr) == set(en), code
