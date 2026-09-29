"""Local audit history + trends — a tiny SQLite store, stdlib only.

`zing serve` persists every finished AuditReport here so the web app can show a
history table and per-target score trends. No new dependency: just `sqlite3`.

Storage lives in ``$ZING_DATA_DIR`` (default ``~/.zing``) as ``history.db``.
Every public function opens a fresh, short-lived connection so the module is
safe to call from FastAPI's threadpool without sharing a connection across
threads. Writes are best-effort: a malformed report must never break the audit
stream, so :func:`save` swallows its own errors and returns ``-1`` on failure.

Knowledge-base snapshots: the full profile a run was audited against
(``report.knowledge.profile``) is stored once per distinct content in
``kb_snapshots`` and linked from the row (``kb_snapshot_id``); the saved
report JSON carries only the hash, and :func:`get` puts the profile back.
Snapshots no row points to any more are deleted with the rows.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from zing import datadir
from zing.knowledge import snapshot as kb_snapshot

# Columns returned by the list view (everything except the heavy report_json).
_SUMMARY_COLS = (
    "id",
    "ts",
    "base_url",
    "claimed_model",
    "model",
    "mode",
    "suite",
    "risk_level",
    "score",
    "rating",
    "kb_match",
    "watch_id",
)

_DB_NAME = "history.db"


def _db_path() -> Path:
    return datadir.db_path(_DB_NAME)


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ts            TEXT,
            base_url      TEXT,
            claimed_model TEXT,
            model         TEXT,
            mode          TEXT,
            suite         TEXT,
            risk_level    TEXT,
            score         REAL,
            rating        TEXT,
            report_json   TEXT
        )
        """
    )
    # Speeds up trend() lookups for a given target+model.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_target "
        "ON history (base_url, claimed_model, id)"
    )
    kb_snapshot.ensure_table(conn)
    # Databases from before knowledge snapshots lack the link columns.
    kb_snapshot.add_link_columns(conn, "history", {"kb_snapshot_id": "INTEGER", "kb_match": "TEXT"})
    # The monitor (watch) that produced a run; NULL for runs started by hand.
    kb_snapshot.add_link_columns(conn, "history", {"watch_id": "INTEGER"})


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Yield a fresh connection with rows as dicts; commit + close on exit."""
    with datadir.connect(_DB_NAME) as conn:
        _ensure(conn)
        yield conn


def init() -> None:
    """Create the tables if they don't exist. Idempotent; safe to call often."""
    with _connect():
        pass


def save(report: dict[str, Any], watch_id: int | None = None) -> int:
    """Persist one AuditReport dict; return the new row id (``-1`` on failure).

    ``watch_id`` marks a run produced by that monitor, so the UI does not offer
    to schedule it as a monitor again.

    Best-effort by contract: this is called from inside the SSE stream, so any
    extraction or DB error is swallowed rather than allowed to abort the audit.
    """
    try:
        report = dict(report or {})
        target = report.get("target") or {}
        verdict = report.get("verdict") or {}
        score = verdict.get("overall_score")
        knowledge = report.get("knowledge")
        if not isinstance(knowledge, dict):
            knowledge = {}
        snap = knowledge.get("profile")
        if isinstance(snap, dict):
            # The profile lives in kb_snapshots; the row keeps only the hash.
            report["knowledge"] = {**knowledge, "profile": None}
        with _connect() as conn:
            snapshot_id = kb_snapshot.put(conn, snap) if isinstance(snap, dict) else None
            cur = conn.execute(
                """INSERT INTO history
                   (ts, base_url, claimed_model, model, mode, suite,
                    risk_level, score, rating, report_json, kb_snapshot_id, kb_match, watch_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    report.get("generated_at"),
                    target.get("base_url"),
                    # Fall back to the concrete model id when no claim was made, so the
                    # trend grouping key is always populated.
                    target.get("claimed_model") or target.get("model"),
                    target.get("model"),
                    report.get("mode"),
                    report.get("suite"),
                    verdict.get("risk_level"),
                    float(score) if isinstance(score, (int, float)) else None,
                    verdict.get("rating"),
                    json.dumps(report, ensure_ascii=False, default=str),
                    snapshot_id,
                    knowledge.get("match_confidence"),
                    int(watch_id) if watch_id is not None else None,
                ),
            )
            return int(cur.lastrowid or -1)
    except Exception:
        return -1


def recent(limit: int = 50, perf: bool = False) -> list[dict[str, Any]]:
    """Most recent audits, newest first — summary columns only (no report).

    With ``perf`` each row also carries the performance headline of its report
    (``latency_p50_ms`` / ``ttft_p50_ms`` / ``decode_tps_p50``, see
    :func:`_perf_headline`) so the UI can draw trends without one call per group.
    """
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 50
    cols = ", ".join(_SUMMARY_COLS + (("report_json",) if perf else ()))
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {cols} FROM history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    out = [dict(r) for r in rows]
    if perf:
        for item in out:
            item.update(_perf_headline(item.pop("report_json", None)))
    return out


def get(rid: int) -> dict[str, Any] | None:
    """The full saved report for one row (profile snapshot included), or ``None``."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT report_json, kb_snapshot_id FROM history WHERE id = ?", (int(rid),)
        ).fetchone()
        if not row or row["report_json"] is None:
            return None
        snap = kb_snapshot.get(conn, row["kb_snapshot_id"])
    try:
        report = json.loads(row["report_json"])
    except (ValueError, TypeError):
        return None
    if snap is not None and isinstance(report, dict) and isinstance(report.get("knowledge"), dict):
        report["knowledge"]["profile"] = snap
    return report


def watch_of(rid: int) -> int | None:
    """The id of the monitor that produced a saved run (``None`` for manual runs)."""
    with _connect() as conn:
        row = conn.execute("SELECT watch_id FROM history WHERE id = ?", (int(rid),)).fetchone()
    return int(row["watch_id"]) if row and row["watch_id"] is not None else None


def run_duration_sec(report: dict[str, Any] | None) -> float | None:
    """How long a saved run took, in seconds: detectors run one after another,
    so their summed durations are the audit's execution time. None if unknown."""
    total = 0.0
    for det in (report or {}).get("detectors") or []:
        ms = det.get("duration_ms") if isinstance(det, dict) else None
        if isinstance(ms, (int, float)) and not isinstance(ms, bool):
            total += float(ms)
    return round(total / 1000, 1) if total > 0 else None


def snapshot_for(rid: int) -> dict[str, Any] | None:
    """The knowledge-base profile snapshot a saved run used, if any."""
    with _connect() as conn:
        row = conn.execute("SELECT kb_snapshot_id FROM history WHERE id = ?", (int(rid),)).fetchone()
        return kb_snapshot.get(conn, row["kb_snapshot_id"]) if row else None


def _perf_headline(report_json: str | None) -> dict[str, float | None]:
    """Target p50 latency / TTFT / decode speed of a saved report (None if absent)."""
    out: dict[str, float | None] = {"latency_p50_ms": None, "ttft_p50_ms": None, "decode_tps_p50": None}
    try:
        target = (json.loads(report_json or "{}").get("performance") or {}).get("target") or {}
    except (ValueError, TypeError, AttributeError):
        return out

    def p50(key: str) -> float | None:
        stats = target.get(key)
        value = stats.get("p50") if isinstance(stats, dict) else None
        return float(value) if isinstance(value, (int, float)) else None

    out["latency_p50_ms"] = p50("latency_ms")
    out["ttft_p50_ms"] = p50("ttft_ms")
    tps = p50("decode_tps_local")
    out["decode_tps_p50"] = tps if tps is not None else p50("decode_tps_reported")
    return out


def trend(
    base_url: str, claimed_model: str, limit: int = 30
) -> list[dict[str, Any]]:
    """Score and performance history for one target+model, oldest→newest, for a
    sparkline."""
    try:
        limit = max(1, min(int(limit), 365))
    except (TypeError, ValueError):
        limit = 30
    with _connect() as conn:
        # Take the newest `limit`, then flip to chronological order.
        rows = conn.execute(
            """SELECT ts, score, risk_level, report_json FROM history
               WHERE base_url = ? AND claimed_model = ?
               ORDER BY id DESC LIMIT ?""",
            (base_url, claimed_model, limit),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in reversed(rows):
        item = {"ts": r["ts"], "score": r["score"], "risk_level": r["risk_level"]}
        item.update(_perf_headline(r["report_json"]))
        out.append(item)
    return out


def delete(rid: int) -> None:
    """Remove one row by id (and a snapshot nothing else uses). No-op if missing."""
    with _connect() as conn:
        conn.execute("DELETE FROM history WHERE id = ?", (int(rid),))
        kb_snapshot.prune(conn, "history")


def clear() -> None:
    """Wipe all history, snapshots included."""
    with _connect() as conn:
        conn.execute("DELETE FROM history")
        kb_snapshot.prune(conn, "history")
