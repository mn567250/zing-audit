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
