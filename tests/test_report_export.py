"""PDF rendering, the report writer's formats, and POST /api/report/export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zing.config import ConfigError, validate_format
from zing.models import AuditReport
from zing.report import PdfUnavailableError, pdf_available, render_pdf, write_reports
from zing.report import pdf as pdf_mod

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "web_report.json"


def _pdf_works() -> bool:
    try:
        import weasyprint  # noqa: F401  (also loads the native Pango libraries)
    except (ImportError, OSError):
        return False
    return True


needs_pdf = pytest.mark.skipif(not _pdf_works(), reason="needs WeasyPrint (the pdf extra)")


@pytest.fixture
def report_dict() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def report(report_dict) -> AuditReport:
    return AuditReport.model_validate(report_dict)


def _no_weasyprint(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "weasyprint":
            raise ImportError("No module named 'weasyprint'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(pdf_mod, "pdf_available", lambda: False)
    monkeypatch.setattr("zing.report.writer.pdf_available", lambda: False)


@needs_pdf
def test_render_pdf_is_the_html_report(report):
    data = render_pdf(report)
    assert data.startswith(b"%PDF-") and len(data) > 5000


@needs_pdf
def test_render_pdf_never_fetches_resources(report, monkeypatch):
    # relay text is escaped, but even an <img> slipping through must not load
    fetched = []

    def fake_html(r):
        return '<html><body><img src="http://example.invalid/x.png"><p>hi</p></body></html>'

    monkeypatch.setattr(pdf_mod, "render_html", fake_html)
    orig = pdf_mod._refuse_fetch
    monkeypatch.setattr(pdf_mod, "_refuse_fetch", lambda url, *a, **k: fetched.append(url) or orig(url))
    assert render_pdf(report).startswith(b"%PDF-")
    assert fetched == ["http://example.invalid/x.png"]


def test_render_pdf_without_weasyprint_says_how_to_install(report, monkeypatch):
    _no_weasyprint(monkeypatch)
    with pytest.raises(PdfUnavailableError, match=r"zing-audit\[pdf\]"):
        render_pdf(report)


@needs_pdf
def test_write_reports_pdf_and_all(report, tmp_path):
    [pdf] = write_reports(report, tmp_path / "one", "pdf")
    assert pdf.suffix == ".pdf" and pdf.read_bytes().startswith(b"%PDF-")
    assert pdf.name == "zing-target-20260927T074704.pdf"
    written = write_reports(report, tmp_path / "all", "all")
    assert [p.suffix for p in written] == [".json", ".md", ".html", ".pdf"]


def test_write_reports_all_skips_pdf_without_weasyprint(report, tmp_path, monkeypatch):
    _no_weasyprint(monkeypatch)
    written = write_reports(report, tmp_path, "all")
    assert [p.suffix for p in written] == [".json", ".md", ".html"]
    with pytest.raises(PdfUnavailableError):
        write_reports(report, tmp_path, "pdf")


def test_validate_format_checks_pdf_support_up_front(monkeypatch):
    assert validate_format("md") == "md"
    monkeypatch.setattr(pdf_mod, "pdf_available", lambda: False)
    with pytest.raises(ConfigError, match=r"zing-audit\[pdf\]"):
        validate_format("pdf")
    monkeypatch.setattr(pdf_mod, "pdf_available", lambda: True)
    assert validate_format("pdf") == "pdf"


def test_pdf_available_matches_the_import():
    assert pdf_available() == (__import__("importlib").util.find_spec("weasyprint") is not None)


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


@needs_pdf
def test_export_pdf(client, report_dict):
    r = client.post("/api/report/export?format=pdf", json=report_dict)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")


def test_export_pdf_unavailable_is_501(client, report_dict, monkeypatch):
    def unavailable(_report):
        raise PdfUnavailableError("PDF export needs WeasyPrint: pip install 'zing-audit[pdf]'")

    monkeypatch.setattr("zing.report.render_pdf", unavailable)
    r = client.post("/api/report/export?format=pdf", json=report_dict)
    assert r.status_code == 501 and "zing-audit[pdf]" in r.json()["error"]


def test_export_rejects_bad_input(client, report_dict):
    r = client.post("/api/report/export?format=docx", json=report_dict)
    assert r.status_code == 400 and "unknown format" in r.json()["error"]
    r = client.post("/api/report/export?format=md", json={"not": "a report"})
    assert r.status_code == 400 and r.json()["error"].startswith("not a zing report")


def test_export_refuses_cross_site_posts(client, report_dict):
    r = client.post("/api/report/export?format=md", json=report_dict,
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
