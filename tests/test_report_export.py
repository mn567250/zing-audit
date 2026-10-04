"""PDF rendering, the report writer's formats, and POST /api/report/export."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest

from zing.config import ConfigError, validate_format
from zing.models import AuditReport
from zing.report import render_pdf, write_reports

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "web_report.json"


@pytest.fixture
def report_dict() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def report(report_dict) -> AuditReport:
    return AuditReport.model_validate(report_dict)


def _text(data: bytes) -> str:
    """The PDF's text, page after page (whitespace collapsed)."""
    from pypdf import PdfReader

    pages = PdfReader(io.BytesIO(data)).pages
    return " ".join(" ".join((p.extract_text() or "").split()) for p in pages)


def test_render_pdf_carries_the_whole_report(report):
    data = render_pdf(report)
    assert data.startswith(b"%PDF-") and len(data) > 5000
    text = _text(data)
    for section in ("Verdict", "Dimensions", "Dimension details", "Findings", "Reliability",
                    "Notes", "Disclaimer."):
        assert section in text
    assert report.verdict.headline in text
    assert "Reported prompt tokens far exceed estimate" in text
    assert "HIGH RISK" in text and "page 2" in text


def test_render_pdf_escapes_relay_text_and_loads_nothing(report_dict):
    # relay-controlled text must stay text: no markup, no images, no links
    title = "<img src='http://example.invalid/x.png'/> <b>&amp;</b> <a href='http://x.invalid'>y</a>"
    report_dict["detectors"][0]["findings"][0]["title"] = title
    data = render_pdf(AuditReport.model_validate(report_dict))
    assert " ".join(title.split()) in _text(data)
    assert b"/Subtype /Image" not in data and b"/URI" not in data


def test_render_pdf_writes_chinese_and_marks(report_dict):
    report_dict["verdict"]["headline"] = "中转站返回的模型与声明不符 ✓ ✗ → Δ"
    report_dict["warnings"] = ["长文本" * 80]
    data = render_pdf(AuditReport.model_validate(report_dict))
    text = _text(data)
    assert "中转站返回的模型与声明不符" in text and "✓" in text and "→" in text
    assert b"STSong-Light" in data  # a standard CID font: nothing embedded or shipped


def test_render_pdf_splits_text_longer_than_a_page(report_dict):
    # relay text is unbounded: a finding or warning taller than a page must flow
    # on to the next one (no LayoutError, no endless re-wrapping)
    report_dict["detectors"][0]["findings"][0]["summary"] = "word " * 8000
    report_dict["detectors"][0]["findings"][0]["title"] = "长" * 3000
    report_dict["warnings"] = ["long warning " * 2000]
    text = _text(render_pdf(AuditReport.model_validate(report_dict)))
    assert text.count("warning") == 2000 and "Disclaimer." in text  # every word, footers between


def test_render_pdf_has_scales_groups_and_performance():
    from tests.test_performance_render import _report as perf_report
    from tests.test_scoring_transparency import _attr_report, _report

    text = _text(render_pdf(asyncio.run(_report())))
    assert "Scoring scale" in text and "not counted" in text
    assert "The invalid request was accepted (2xx)." in text
    text = _text(render_pdf(asyncio.run(_attr_report())))
    assert "Core response attributes: all 8" in text and "7 of 8 OK" in text
    text = _text(render_pdf(perf_report()))
    assert "Performance measurements" in text and "Target vs baseline" in text
    assert "Latency (ms)" in text and "failed request" in text


def test_write_reports_pdf_and_all(report, tmp_path):
    [pdf] = write_reports(report, tmp_path / "one", "pdf")
    assert pdf.suffix == ".pdf" and pdf.read_bytes().startswith(b"%PDF-")
    assert pdf.name == "zing-target-20260927T074704.pdf"
    written = write_reports(report, tmp_path / "all", "all")
    assert [p.suffix for p in written] == [".json", ".md", ".html", ".pdf"]


def test_validate_format_accepts_pdf():
    assert validate_format("md") == "md"
    assert validate_format("pdf") == "pdf"
    with pytest.raises(ConfigError):
        validate_format("docx")


# --------------------------------------------------------------------------- #
# POST /api/report/export
# --------------------------------------------------------------------------- #
@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from zing.web.server import create_app

    return TestClient(create_app(), base_url="http://localhost")


@pytest.mark.parametrize(("fmt", "ctype", "start"), [
    ("json", "application/json", b"{"),
    ("md", "text/markdown; charset=utf-8", b"# zing audit"),
    ("html", "text/html; charset=utf-8", b"<!DOCTYPE html>"),
])
def test_export_text_formats(client, report_dict, fmt, ctype, start):
    r = client.post(f"/api/report/export?format={fmt}", json=report_dict)
    assert r.status_code == 200
    assert r.headers["content-type"] == ctype
    assert r.headers["content-disposition"] == f'attachment; filename="zing-target-20260927T074704.{fmt}"'
    assert r.content.startswith(start)


def test_export_renders_the_text_it_is_given(client, report_dict):
    # the UI sends the report with its text already in the UI language
    report_dict["detectors"][0]["findings"][0]["title"] = "Gemeldete Prompt-Tokens weit über der Schätzung"
    r = client.post("/api/report/export?format=md", json=report_dict)
    assert "Gemeldete Prompt-Tokens weit über der Schätzung" in r.text


def test_export_pdf_is_the_cli_pdf(client, report_dict, report):
    # the web UI and the CLI share one renderer: same input, same document
    r = client.post("/api/report/export?format=pdf", json=report_dict)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'attachment; filename="zing-target-20260927T074704.pdf"'
    assert _text(r.content) == _text(render_pdf(report))


def test_export_pdf_failure_is_json(client, report_dict, monkeypatch):
    def broken(_report):
        raise ValueError("boom")

    monkeypatch.setattr("zing.report.render_pdf", broken)
    r = client.post("/api/report/export?format=pdf", json=report_dict)
    assert r.status_code == 500 and r.json()["error"] == "PDF rendering failed: boom"


def test_export_rejects_bad_input(client, report_dict):
    r = client.post("/api/report/export?format=docx", json=report_dict)
    assert r.status_code == 400 and "unknown format" in r.json()["error"]
    r = client.post("/api/report/export?format=md", json={"not": "a report"})
    assert r.status_code == 400 and r.json()["error"].startswith("not a zing report")


def test_export_refuses_cross_site_posts(client, report_dict):
    r = client.post("/api/report/export?format=md", json=report_dict,
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
