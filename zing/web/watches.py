"""Scheduled watch store — saved re-audit targets for the web monitor, stdlib only.

`zing serve` can keep a list of *watches*: a target plus a cadence (interval),
suite, an alert threshold, and a set of webhooks. A background scheduler in the
web server runs each due watch on its interval and POSTs an alert when the risk
crosses the threshold or regresses versus the previous run. This module is the
persistence layer for those watch definitions — a tiny SQLite store, no new
dependency beyond ``sqlite3``.

Storage lives alongside the audit history in ``$ZING_DATA_DIR`` (default
``~/.zing``) as ``watches.db``. Like :mod:`zing.web.history`, every function
opens a fresh short-lived connection so the module is safe to call from
FastAPI's threadpool, lazily creates its table, and is best-effort: a malformed
row must never crash the scheduler loop.

Secret handling: the stored ``api_key`` is what the scheduler needs to actually
run the audit, so it is kept in the DB. But :func:`list_all` (the listing the
browser sees) NEVER returns it — only :func:`get` and :func:`due`, used
server-side by the scheduler, expose the key.

Pinned knowledge-base profile: when a watch is created, the profile its
claimed model resolves to is snapshotted into this database (``kb_snapshots``,
linked by ``kb_snapshot_id``; how it matched and where it came from in
``kb_usage``). Every scheduled run audits against that fixed snapshot, so a
later knowledge-base edit cannot silently change what a monitor measures;
:func:`pin` re-pins it to the current knowledge base on request. A watch whose
model matched no profile at creation resolves the live knowledge base per run.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from zing import datadir, i18n
from zing.knowledge import snapshot as kb_snapshot

# Full column set, in table order. ``api_key`` lives here for the scheduler, but
# is filtered out of the public listing (see _LIST_COLS).
_ALL_COLS = (
    "id",
    "name",
    "base_url",
    "api_key",
    "model",
    "claimed_model",
    "api",
    "declared_provider",
    "suite",
    "interval_sec",
    "alert_on",
    "webhooks",
    "enabled",
    "created_ts",
    "last_run_ts",
    "last_risk",
    "last_score",
    "last_report_id",
    "language",
    "kb_snapshot_id",
    "kb_usage",
    "kb_pinned_ts",
)

# Columns safe to return to the browser — everything except the API key.
_LIST_COLS = tuple(c for c in _ALL_COLS if c != "api_key")


_DB_NAME = "watches.db"


def _db_path() -> Path:
    return datadir.db_path(_DB_NAME)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Yield a fresh connection with rows as dicts; commit + close on exit."""
    with datadir.connect(_DB_NAME) as conn:
        _ensure_table(conn)
        yield conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Lazily create the watches table. Idempotent."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watches (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            name              TEXT,
            base_url          TEXT,
            api_key           TEXT,
            model             TEXT,
            claimed_model     TEXT,
            api               TEXT,
            declared_provider TEXT,
            suite             TEXT,
            interval_sec      INTEGER,
            alert_on          TEXT,
            webhooks          TEXT,
            enabled           INTEGER DEFAULT 1,
            created_ts        REAL,
            last_run_ts       REAL,
            last_risk         TEXT,
            last_score        REAL,
            last_report_id    INTEGER,
            language          TEXT
        )
        """
    )
    # Databases created before alerts were translatable lack `language`; add
    # it (NULL = English, see zing.i18n.normalize).
    cols = {r[1] for r in conn.execute("PRAGMA table_info(watches)")}
    if "language" not in cols:
        conn.execute("ALTER TABLE watches ADD COLUMN language TEXT")
    kb_snapshot.ensure_table(conn)
    kb_snapshot.add_link_columns(
        conn, "watches", {"kb_snapshot_id": "INTEGER", "kb_usage": "TEXT", "kb_pinned_ts": "REAL"}
    )


def init() -> None:
    """Create the table if it doesn't exist. Idempotent; safe to call often."""
    with _connect():
        pass


def _row_to_dict(row: sqlite3.Row, *, include_key: bool) -> dict[str, Any]:
    """Convert a row to a plain dict, decoding webhooks JSON and the enabled flag.

    When ``include_key`` is False the ``api_key`` column is omitted entirely so it
    can never leak to a caller that only asked for a listing.
    """
    d = dict(row)
    if not include_key:
        d.pop("api_key", None)
    # webhooks is stored as a JSON list; decode defensively.
    raw = d.get("webhooks")
    try:
        d["webhooks"] = json.loads(raw) if isinstance(raw, str) and raw else []
    except (ValueError, TypeError):
        d["webhooks"] = []
    if not isinstance(d["webhooks"], list):
        d["webhooks"] = []
    d["enabled"] = bool(d.get("enabled"))
    d["language"] = i18n.normalize(d.get("language"))
    # kb_usage: the pinned profile's match/sources (the profile itself stays
    # in kb_snapshots); exposed as `kb`, None when nothing is pinned.
    raw_kb = d.pop("kb_usage", None)
    try:
        kb = json.loads(raw_kb) if isinstance(raw_kb, str) and raw_kb else None
    except (ValueError, TypeError):
        kb = None
    d["kb"] = kb if isinstance(kb, dict) and d.get("kb_snapshot_id") is not None else None
    if d["kb"] is not None:
        d["kb"]["pinned_at"] = d.get("kb_pinned_ts")
    return d


def _pin(conn: sqlite3.Connection, wid: int, knowledge: dict[str, Any] | None) -> None:
    snap = (knowledge or {}).get("profile")
    if isinstance(snap, dict):
        sid: int | None = kb_snapshot.put(conn, snap)
        usage = json.dumps({**(knowledge or {}), "profile": None}, ensure_ascii=False, default=str)
        ts: float | None = time.time()
    else:
        sid, usage, ts = None, None, None
    conn.execute(
        "UPDATE watches SET kb_snapshot_id = ?, kb_usage = ?, kb_pinned_ts = ? WHERE id = ?",
        (sid, usage, ts, int(wid)),
    )
    kb_snapshot.prune(conn, "watches")


def pin(wid: int, knowledge: dict[str, Any] | None) -> None:
    """Pin (or re-pin) a watch to a knowledge-base profile.

    ``knowledge`` is a :class:`~zing.models.KnowledgeUsage` dict with its
    ``profile`` snapshot; without one the watch resolves the live KB per run.
    """
    with _connect() as conn:
        _pin(conn, wid, knowledge)


def pinned_knowledge(wid: int) -> dict[str, Any] | None:
    """The pinned KnowledgeUsage dict (profile snapshot included), or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT kb_snapshot_id, kb_usage, kb_pinned_ts FROM watches WHERE id = ?", (int(wid),)
        ).fetchone()
        if not row or row["kb_snapshot_id"] is None or not row["kb_usage"]:
            return None
        snap = kb_snapshot.get(conn, row["kb_snapshot_id"])
    try:
        usage = json.loads(row["kb_usage"])
    except (ValueError, TypeError):
        return None
    if snap is None or not isinstance(usage, dict):
        return None
    return {**usage, "profile": snap, "pinned_at": row["kb_pinned_ts"]}


def create(cfg: dict[str, Any], knowledge: dict[str, Any] | None = None) -> int:
    """Insert a new watch from a config dict; return its new id.

    Expected keys: name, base_url, api_key, model, claimed_model, api,
    declared_provider, suite, interval_sec, alert_on, webhooks (list), language
    (alert language code; unknown/missing -> English). Unknown keys are ignored;
    missing keys fall back to sensible defaults. ``knowledge`` (a
    KnowledgeUsage dict with its profile) pins the watch's profile.
    """
    cfg = cfg or {}
    webhooks = cfg.get("webhooks") or []
    if not isinstance(webhooks, list):
        webhooks = [webhooks]
    webhooks = [str(w).strip() for w in webhooks if str(w).strip()]
    try:
        interval = max(30, int(cfg.get("interval_sec") or 3600))
    except (TypeError, ValueError):
        interval = 3600
    row = (
        cfg.get("name") or "watch",
        cfg.get("base_url"),
        cfg.get("api_key") or "",
        cfg.get("model"),
        cfg.get("claimed_model") or None,
        cfg.get("api") or "auto",
        cfg.get("declared_provider") or None,
        cfg.get("suite") or "standard",
        interval,
        cfg.get("alert_on") or "medium",
        json.dumps(webhooks, ensure_ascii=False),
        1 if cfg.get("enabled", True) else 0,
        time.time(),
        i18n.normalize(cfg.get("language")),
    )
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO watches
               (name, base_url, api_key, model, claimed_model, api,
                declared_provider, suite, interval_sec, alert_on, webhooks,
                enabled, created_ts, language)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )
        wid = int(cur.lastrowid or -1)
        if knowledge is not None:
            _pin(conn, wid, knowledge)
        return wid


def list_all() -> list[dict[str, Any]]:
    """All watches, newest first, WITHOUT api_key (safe for the browser)."""
    cols = ", ".join(_LIST_COLS)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {cols} FROM watches ORDER BY id DESC"
        ).fetchall()
    return [_row_to_dict(r, include_key=False) for r in rows]


def get(wid: int) -> dict[str, Any] | None:
    """One full watch row INCLUDING api_key, or ``None`` if missing.

    Server-side use only (the scheduler / run-now). Never hand this to a client
    response without stripping the key first.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM watches WHERE id = ?", (int(wid),)
        ).fetchone()
    return _row_to_dict(row, include_key=True) if row else None


def set_enabled(wid: int, enabled: bool) -> None:
    """Enable or disable a watch. No-op if it doesn't exist."""
    with _connect() as conn:
        conn.execute(
            "UPDATE watches SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, int(wid)),
        )


def set_language(wid: int, language: str | None) -> None:
    """Set a watch's alert language (unknown codes become English)."""
    with _connect() as conn:
        conn.execute(
            "UPDATE watches SET language = ? WHERE id = ?",
            (i18n.normalize(language), int(wid)),
        )


def delete(wid: int) -> None:
    """Remove one watch by id. No-op if it doesn't exist."""
    with _connect() as conn:
        conn.execute("DELETE FROM watches WHERE id = ?", (int(wid),))
        kb_snapshot.prune(conn, "watches")


def mark_run(
    wid: int,
    risk: str | None,
    score: float | None,
    report_id: int | None,
    ts: float,
) -> None:
    """Record the outcome of a run: last risk/score/report id and run timestamp."""
    with _connect() as conn:
        conn.execute(
            """UPDATE watches
               SET last_run_ts = ?, last_risk = ?, last_score = ?, last_report_id = ?
               WHERE id = ?""",
            (
                float(ts),
                risk,
                float(score) if isinstance(score, (int, float)) else None,
                int(report_id) if report_id is not None else None,
                int(wid),
            ),
        )


def due(now_ts: float) -> list[dict[str, Any]]:
    """Enabled watches whose interval has elapsed — full rows incl. api_key.

    A watch is due when it has never run, or when ``now - last_run >= interval``.
    Used by the scheduler, so the api_key is included to actually run the audit.
    """
    out: list[dict[str, Any]] = []
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM watches WHERE enabled = 1").fetchall()
    for r in rows:
        d = _row_to_dict(r, include_key=True)
        last = d.get("last_run_ts")
        interval = d.get("interval_sec") or 0
        if last is None or (now_ts - float(last)) >= float(interval):
            out.append(d)
    return out
