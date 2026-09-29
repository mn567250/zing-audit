"""Persist a rendered :class:`~zing.models.AuditReport` to disk.

``write_reports`` is the single entry point the CLI calls. It maps a format
selector to the matching renderer(s), names files deterministically from the
target and timestamp, and returns the paths it wrote so the caller can surface
them. Rendering never touches the network and never mutates the report.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from zing.models import AuditReport
from zing.report.pdf import PdfUnavailableError, pdf_available, render_pdf
from zing.report.render import render_html, render_json, render_markdown

# format selector -> (extension, renderer); text renderers return str, PDF bytes
_RENDERERS: dict[str, tuple[str, Callable[[AuditReport], str | bytes]]] = {
    "json": ("json", render_json),
    "md": ("md", render_markdown),
    "html": ("html", render_html),
    "pdf": ("pdf", render_pdf),
}


def _sanitize(name: str) -> str:
    """Reduce an arbitrary target name to a filesystem-safe slug."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return slug or "target"


def _compact_timestamp(generated_at: str | None) -> str:
    """Compact an ISO timestamp to ``YYYYmmddTHHMMSS`` (UTC fallback if absent)."""
    dt: datetime | None = None
    if generated_at:
        try:
            dt = datetime.fromisoformat(generated_at)
        except ValueError:
            dt = None
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%S")


def report_stem(report: AuditReport) -> str:
    """``zing-<sanitized target.name>-<YYYYmmddTHHMMSS>`` (file name without extension)."""
    return f"zing-{_sanitize(report.target.name)}-{_compact_timestamp(report.generated_at)}"


def write_reports(report: AuditReport, out_dir: Path, fmt: str) -> list[Path]:
    """Write the report in ``fmt`` to ``out_dir`` and return the written paths.

    ``fmt`` is one of ``json``, ``md``, ``html``, ``pdf`` or ``all``. ``all``
    includes PDF only when WeasyPrint (the ``pdf`` extra) is installed and
    loads; ``pdf`` alone raises :class:`PdfUnavailableError` without it. The
    directory is created if missing. Filenames are
    ``zing-<sanitized target.name>-<YYYYmmddTHHMMSS>.<ext>``.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "all":
        formats: tuple[str, ...] = ("json", "md", "html") + (("pdf",) if pdf_available() else ())
    else:
        formats = (fmt,)

    stem = report_stem(report)

    written: list[Path] = []
    for key in formats:
        spec = _RENDERERS.get(key)
        if spec is None:
            continue
        ext, renderer = spec
        path = out_dir / f"{stem}.{ext}"
        try:
            content = renderer(report)
        except PdfUnavailableError:
            if fmt == "all":  # best-effort extra; an explicit --format pdf still fails
                continue
            raise
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
