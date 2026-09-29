"""Render an :class:`~zing.models.AuditReport` to PDF.

The PDF is the self-contained HTML report (:func:`~zing.report.render.render_html`)
typeset by WeasyPrint, so the two never drift apart. WeasyPrint is the optional
``pdf`` extra (``pip install 'zing-audit[pdf]'``); it is imported lazily and
:func:`pdf_available` lets callers check for it before doing any work.

The HTML carries relay-controlled text (escaped, but still untrusted), so the
renderer is given a URL fetcher that refuses every fetch: a PDF export never
touches the network or the local filesystem.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Any

from zing.models import AuditReport
from zing.report.render import render_html

PDF_INSTALL_HINT = "PDF export needs WeasyPrint: pip install 'zing-audit[pdf]'"


class PdfUnavailableError(RuntimeError):
    """WeasyPrint (the optional ``pdf`` extra) is not installed or cannot load."""


def pdf_available() -> bool:
    """True when WeasyPrint is importable (its native libraries are checked on use)."""
    return importlib.util.find_spec("weasyprint") is not None


def _refuse_fetch(url: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    raise ValueError(f"external resources are disabled in PDF export: {url[:80]}")


def _url_fetcher(weasyprint: Any) -> Any:
    """A fetcher that refuses every URL, for old (function) and new (class) WeasyPrint APIs."""
    base = getattr(weasyprint, "URLFetcher", None)
    if base is None:  # WeasyPrint < 68: any callable
        return _refuse_fetch

    class _RefuseAll(base):  # type: ignore[misc, valid-type]
        def fetch(self, url: str, headers: Any = None) -> Any:
            return _refuse_fetch(url)

    return _RefuseAll()


def render_pdf(report: AuditReport) -> bytes:
    """The HTML report as PDF bytes. Raises :class:`PdfUnavailableError` without WeasyPrint."""
    try:
        import weasyprint
    except (ImportError, OSError) as exc:  # OSError: missing pango/cairo libraries
        raise PdfUnavailableError(f"{PDF_INSTALL_HINT} ({exc})") from exc

    # WeasyPrint logs every CSS property it does not support (e.g. color-scheme);
    # those are expected for a stylesheet written for browsers first.
    wp_log = logging.getLogger("weasyprint")
    level = wp_log.level
    wp_log.setLevel(logging.ERROR)
    try:
        doc = weasyprint.HTML(string=render_html(report), url_fetcher=_url_fetcher(weasyprint))
        pdf = doc.write_pdf()
    finally:
        wp_log.setLevel(level)
    return bytes(pdf or b"")
