"""FastAPI app for `zing serve` — serves the SPA and streams live audits over SSE.

Endpoints:
  GET  /                     the single-page app (classic UI)
  GET  /v2/…                 the v2 UI, served side by side for A/B comparison;
                             ?ui=v1|v2 on any page picks one (remembered in the
                             `zing_ui` cookie)
  GET  /api/health           {ok, version}
  GET  /api/kb/profiles      the merged knowledge base with sources + your kb.db entries
  GET  /api/kb/prompt        research prompt for an external AI (?model=&provider=)
  POST /api/kb/scan          check uploaded profile YAML (writes nothing)
  POST /api/kb/import        check + store profile YAML in kb.db
  GET  /api/kb/export        your kb.db entries as YAML
  POST /api/models           list a relay's /models (connection check + model ids)
  POST /api/audit/stream     run an audit; stream detector progress, batched
                             per-request timing records and the final report
                             as Server-Sent Events (text/event-stream)

The audit runs in-process with the same `run_audit` the CLI uses; a progress
callback pushes per-detector events into a queue the SSE generator drains. The
final report is the model's own redacted `model_dump` (API key fingerprinted,
relay text scrubbed), so nothing secret crosses to the browser.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

# fastapi is the optional [web] extra. This module is only imported when serving
# (CLI `serve`) or by the web tests, both of which handle a missing dependency.
from fastapi import FastAPI, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from zing import __version__, prompts
from zing.config import (
    AuditOptions,
    ConfigError,
    build_target,
    validate_api,
    validate_suite,
)
from zing.models import KnowledgeUsage
from zing.runner import run_audit
from zing.web.security import LocalOnlyMiddleware

_STATIC = Path(__file__).parent / "static"
_V2 = _STATIC / "v2"

# The two UIs served side by side (A/B): classic path -> (classic file, v2 path).
# `?ui=v1|v2` on any of these pages picks a UI and remembers it in a cookie;
# with the cookie set to v2, classic paths redirect to their v2 counterpart.
_UI_COOKIE = "zing_ui"
_UI_PAGES: dict[str, tuple[str, str]] = {
    "/": ("index.html", "/v2/"),
    "/console": ("console.html", "/v2/console"),
    "/history": ("history.html", "/v2/history"),
    "/watches": ("watches.html", "/v2/watches"),
    "/tools": ("tools.html", "/v2/tools"),
}

# How often the watch scheduler wakes to look for due re-audits. The interval an
# individual watch runs on is its own (much larger) interval_sec; this is just
# the polling tick.
_SCHEDULER_TICK_SEC = 30.0

# Live per-request events are batched into one SSE message per window.
_REQUEST_BATCH_SEC = 0.25

# Built-in known-answer rerank probe: one document (index 2) is unmistakably the
# most relevant answer to the query. A genuine reranker must rank it first.
_RERANK_PROBE_QUERY = prompts.text("rerank.web.query")
_RERANK_PROBE_DOCS: list[str] = prompts.get("rerank.web.documents")
_RERANK_PROBE_TOP = 2


def _remember_ui(resp: Response, choice: str | None) -> Response:
    if choice == "v2":
        resp.set_cookie(_UI_COOKIE, "v2", max_age=365 * 24 * 3600, samesite="lax")
    elif choice == "v1":
        resp.delete_cookie(_UI_COOKIE)
    return resp


def _classic_page(request: Request, path: str) -> Response:
    """A classic page, or a redirect to its v2 counterpart when v2 is chosen."""
    file, v2_path = _UI_PAGES[path]
    ui = request.query_params.get("ui")
    choice = ui if ui in ("v1", "v2") else request.cookies.get(_UI_COOKIE)
    resp: Response
    if choice == "v2":
        resp = RedirectResponse(v2_path, status_code=307)
    else:
        resp = FileResponse(_STATIC / file)
    return _remember_ui(resp, ui)


def _v2_page(request: Request, path: str) -> Response:
    """A v2 page; `?ui=v1` goes back to the classic page (and forgets v2)."""
    ui = request.query_params.get("ui")
    resp: Response
    if ui == "v1":
        resp = RedirectResponse(path, status_code=307)
    else:
        resp = FileResponse(_V2 / _UI_PAGES[path][0])
    return _remember_ui(resp, ui)


def _coerce_int(value: Any) -> int:
    """Best-effort int from JSON input (str/float/None all tolerated). 0 on failure."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _watch_knowledge(row: dict[str, Any], kb: Any = None) -> dict[str, Any]:
    """KnowledgeUsage (with profile snapshot) a watch's claimed model resolves to now."""
    from zing.knowledge import load_knowledge_base
    from zing.knowledge.snapshot import knowledge_usage

    claimed = str(row.get("claimed_model") or row.get("model") or "")
    kb = kb if kb is not None else load_knowledge_base()
    resolved = kb.resolve(claimed, row.get("declared_provider") or None)
    return knowledge_usage(kb, resolved, claimed).model_dump(mode="json")


def _kb_embedding_dimensions(model_id: str | None, provider_hint: str | None) -> int:
    """Native embedding dimension for ``model_id`` from the KB; 0 if unknown."""
    if not model_id:
        return 0
    try:
        from zing.knowledge import load_knowledge_base

        resolved = load_knowledge_base().resolve(model_id, provider_hint=provider_hint)
    except Exception:
        return 0
    if resolved is None:
        return 0
    return int(resolved.model.embedding_dimensions or 0)


async def _run_one_watch(row: dict[str, Any]) -> None:
    """Run a single due watch once: audit, persist, alert on regression/threshold.

    Always best-effort — any exception is swallowed by the caller so one bad
    watch can never kill the scheduler loop. The watch's run timestamp is
    recorded even on failure so a permanently broken target doesn't get retried
    every tick.
    """
    from zing.web import history, watches

    wid = int(row["id"])
    now = time.time()
    risk: str | None = None
    score: float | None = None
    report_id: int | None = None
    try:
        suite = validate_suite(str(row.get("suite") or "standard"))
        target = build_target(
            kind="target",
            name=row.get("name") or "watch",
            base_url=row.get("base_url"),
            api_key=row.get("api_key"),
            model=row.get("model"),
            claimed_model=row.get("claimed_model") or None,
            declared_provider=row.get("declared_provider") or None,
            api=validate_api(row.get("api")),
        )
        options = AuditOptions(suite=suite)
        # Audit against the profile pinned when the watch was created, so a
        # knowledge-base edit cannot silently change what the monitor measures.
        pinned_raw = watches.pinned_knowledge(wid)
        pinned = KnowledgeUsage(**pinned_raw) if pinned_raw else None

        # Previous saved run for this target+model — used for the regression check
        # and the "since last run" delta in the alert. notify.send needs the full report,
        # so find the most recent prior history row for this target and re-fetch it.
        claimed = target.claimed_model or target.model
        previous: dict[str, Any] | None = None
        for item in history.recent(50):  # newest first
            if (
                item.get("base_url") == target.base_url
                and item.get("claimed_model") == claimed
            ):
                previous = history.get(int(item["id"]))
                break

        report = await run_audit(target, options, baseline=None, mode="check", pinned=pinned)
        report_dict = json.loads(report.model_dump_json())
        report_id = history.save(report_dict)
        if report_id is not None and report_id < 0:
            report_id = None

        verdict = report_dict.get("verdict") or {}
        # report_dict came through model_dump_json, so risk_level is a plain str.
        raw_risk = verdict.get("risk_level")
        risk = raw_risk if isinstance(raw_risk, str) else None
        raw_score = verdict.get("overall_score")
        score = float(raw_score) if isinstance(raw_score, (int, float)) else None

        # Decide whether to alert: risk crossed the configured threshold, OR it
        # regressed versus the previous saved run.
        from zing.notify import regressed, send

        alert_on = str(row.get("alert_on") or "medium")
        crossed = _risk_meets(risk, alert_on)
        went_worse = regressed(report_dict, previous)
        if crossed or went_worse:
            for url in row.get("webhooks") or []:
                if not isinstance(url, str) or not url.strip():
                    continue
                with contextlib.suppress(Exception):
                    await send(url.strip(), report_dict, previous=previous, lang=row.get("language"))
    finally:
        # Record the run no matter what so cadence stays honest.
        with contextlib.suppress(Exception):
            watches.mark_run(wid, risk, score, report_id, now)


def _risk_meets(risk: str | None, threshold: str) -> bool:
    """True when ``risk`` is at or above the ``threshold`` risk level."""
    from zing.models import RiskLevel

    order = {
        RiskLevel.CLEAN.value: 0,
        RiskLevel.INCONCLUSIVE.value: 1,
        RiskLevel.LOW.value: 2,
        RiskLevel.MEDIUM.value: 3,
        RiskLevel.HIGH.value: 4,
    }
    if not risk:
        return False
    return order.get(risk, 0) >= order.get(threshold, order[RiskLevel.MEDIUM.value])


async def _scheduler_loop() -> None:
    """Poll for due watches every tick and run each one (best-effort, idle-quiet).

    If nothing is due, the loop does nothing and the server stays silent. Each
    watch is wrapped in its own try/except so a single failure never stops the
    loop. Cancellation (on server shutdown) propagates cleanly.
    """
    from zing.web import watches

    while True:
        try:
            due = watches.due(time.time())
        except Exception:
            due = []
        for row in due:
            try:
                await _run_one_watch(row)
            except asyncio.CancelledError:
                raise
            except Exception:
                # One bad watch must never take down the whole loop.
                pass
        await asyncio.sleep(_SCHEDULER_TICK_SEC)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Spawn the watch scheduler on startup; cancel it cleanly on shutdown."""
    from zing.web import watches

    with contextlib.suppress(Exception):
        watches.init()
    task = asyncio.create_task(_scheduler_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


def create_app() -> FastAPI:
    app = FastAPI(
        title="zing",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=_lifespan,
    )
    # Local-only: Host allowlist (DNS rebinding), Origin + JSON checks (CSRF),
    # security headers. See zing/web/security.py.
    app.add_middleware(LocalOnlyMiddleware)

    @app.get("/api/health")
    async def health() -> Any:
        return {"ok": True, "version": __version__, "name": "zing"}

    @app.get("/")
    async def index(request: Request) -> Any:
        return _classic_page(request, "/")

    @app.get("/console")
    async def console(request: Request) -> Any:
        return _classic_page(request, "/console")

    # ----- v2 UI (side by side with the classic one, for A/B) ------------- #
    @app.get("/v2")
    async def v2_bare() -> Any:
        return RedirectResponse("/v2/", status_code=307)

    @app.get("/v2/")
    async def v2_index(request: Request) -> Any:
        return _v2_page(request, "/")

    @app.get("/v2/console")
    async def v2_console(request: Request) -> Any:
        return _v2_page(request, "/console")

    @app.get("/v2/history")
    async def v2_history(request: Request) -> Any:
        return _v2_page(request, "/history")

    @app.get("/v2/watches")
    async def v2_watches(request: Request) -> Any:
        return _v2_page(request, "/watches")

    @app.get("/v2/tools")
    async def v2_tools(request: Request) -> Any:
        return _v2_page(request, "/tools")

    @app.get("/v2/kb")
    async def v2_kb(request: Request) -> Any:
        # v2 only (no classic counterpart): ?ui=v1 goes to the classic start page.
        resp: Response
        if request.query_params.get("ui") == "v1":
            resp = RedirectResponse("/", status_code=307)
        else:
            resp = FileResponse(_V2 / "kb.html")
        return _remember_ui(resp, request.query_params.get("ui"))

    # v2 stylesheets / scripts, e.g. /v2/static/zing.css
    app.mount("/v2/static", StaticFiles(directory=str(_V2)), name="v2-static")

    @app.get("/i18n.js")
    async def i18n_js() -> Any:
        return FileResponse(_STATIC / "i18n.js", media_type="application/javascript")

    @app.get("/locales.js")
    async def locales_js() -> Any:
        # Translation data (zing/i18n/locales/*.json) + the lookup logic.
        from zing.i18n import locales_script

        return Response(locales_script(), media_type="application/javascript")

    @app.get("/lang.js")
    async def lang_js() -> Any:
        return FileResponse(_STATIC / "lang.js", media_type="application/javascript")

    @app.get("/icons.js")
    async def icons_js() -> Any:
        return FileResponse(_STATIC / "icons.js", media_type="application/javascript")

    @app.get("/modelpicker.js")
    async def modelpicker_js() -> Any:
        return FileResponse(
            _STATIC / "modelpicker.js", media_type="application/javascript"
        )

    @app.get("/perf.js")
    async def perf_js() -> Any:
        return FileResponse(_STATIC / "perf.js", media_type="application/javascript")

    @app.get("/secretfield.js")
    async def secretfield_js() -> Any:
        return FileResponse(_STATIC / "secretfield.js", media_type="application/javascript")

    @app.get("/api/kb")
    async def kb() -> Any:
        # Public model metadata only — no keys, no secrets. Mirrors the grouping
        # the CLI `kb --json` command uses: providers sorted, each with its models.
        from zing.knowledge import load_knowledge_base

        knowledge = load_knowledge_base()
        provs = sorted(knowledge.providers.values(), key=lambda p: p.provider)
        providers = [
            {
                "provider": prov.provider,
                "display_name": prov.display_name,
                "models": [{"id": m.id, "aliases": list(m.aliases)} for m in prov.models],
            }
            for prov in provs
        ]
        return JSONResponse({"providers": providers})

    # ----- Knowledge base: browse, research prompt, import/export -------- #
    @app.get("/api/kb/profiles")
    async def kb_profiles() -> Any:
        # Every provider/model as merged for audits, with its source and the
        # user's entries (kb.db) — plus entries that were skipped.
        from zing.knowledge import load_knowledge_base, store

        knowledge = load_knowledge_base()
        providers = []
        for prov in sorted(knowledge.providers.values(), key=lambda p: p.provider):
            models = []
            for m in prov.models:
                key = f"{prov.provider}/{m.id}"
                models.append({
                    **m.model_dump(mode="json"),
                    "source": knowledge.model_sources.get(key),
                    "shadows": knowledge.shadowed.get(key),
                    "entry_id": (knowledge.entries.get(f"model:{key}") or {}).get("id"),
                })
            providers.append({
                **prov.model_dump(mode="json", exclude={"models"}),
                "source": knowledge.provider_sources.get(prov.provider),
                "entry_id": (knowledge.entries.get(f"provider:{prov.provider}") or {}).get("id"),
                "models": models,
            })
        entries = [{k: v for k, v in e.items() if k != "body"} for e in store.list_entries()]
        return JSONResponse({"providers": providers, "entries": entries,
                             "user_kb": knowledge.user_kb, "warnings": knowledge.warnings})

    @app.get("/api/kb/prompt")
    async def kb_prompt(model: str = "", provider: str = "") -> Any:
        from zing.knowledge import load_knowledge_base
        from zing.knowledge.research import research_prompt

        text = research_prompt(model[:200], provider[:64] or None, load_knowledge_base())
        return Response(text, media_type="text/plain; charset=utf-8")

    @app.post("/api/kb/resolve")
    async def kb_resolve(request: Request) -> Any:
        from zing.knowledge import load_knowledge_base

        body = await request.json()
        knowledge = load_knowledge_base()
        r = knowledge.resolve(str(body.get("model") or "")[:200], body.get("provider") or None)
        if r is None:
            return JSONResponse({"matched": False})
        key = f"{r.provider.provider}/{r.model.id}"
        return JSONResponse({"matched": True, "provider": r.provider.provider, "model_id": r.model.id,
                             "match_confidence": r.match_confidence,
                             "source": knowledge.model_sources.get(key)})

    async def _yaml_body(request: Request) -> tuple[str, str | None]:
        body = await request.json()
        text = body.get("yaml") if isinstance(body, dict) else None
        name = body.get("filename") if isinstance(body, dict) else None
        return (text if isinstance(text, str) else ""), (str(name)[:120] if name else None)

    @app.post("/api/kb/scan")
    async def kb_scan(request: Request) -> Any:
        # Check uploaded YAML; nothing is written.
        from zing.knowledge.importer import scan

        text, _name = await _yaml_body(request)
        return JSONResponse(scan(text).to_dict())

    @app.post("/api/kb/import")
    async def kb_import(request: Request) -> Any:
        from zing.knowledge.importer import import_yaml

        text, name = await _yaml_body(request)
        result, ids = import_yaml(text, origin=f"import:{name}" if name else "import")
        body = {**result.to_dict(), "entry_ids": ids}
        return JSONResponse(body, status_code=201 if result.ok else 400)

    @app.get("/api/kb/export")
    async def kb_export(provider: str = "") -> Any:
        from zing.knowledge.importer import export_yaml

        text = export_yaml(provider or None)
        fname = f"zing-kb-{provider or 'mine'}.yaml"
        return Response(text, media_type="application/yaml; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    @app.patch("/api/kb/entries/{entry_id}")
    async def kb_entry_patch(entry_id: int, request: Request) -> Any:
        from zing.knowledge import store

        body = await request.json()
        if "enabled" not in body:
            return JSONResponse({"error": "nothing to change"}, status_code=400)
        if not store.set_enabled(entry_id, bool(body.get("enabled"))):
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"ok": True})

    @app.delete("/api/kb/entries/{entry_id}")
    async def kb_entry_delete(entry_id: int) -> Any:
        from zing.knowledge import store

        if not store.delete(entry_id):
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"ok": True})

    @app.post("/api/models")
    async def relay_models(request: Request) -> Any:
        # List the relay's own /models so the picker can offer ids it really
        # accepts. The API key is optional: self-hosted relays (Ollama, LM Studio)
        # need none, and an empty key sends no auth header.
        from zing.clients import detect_api, make_client

        body = await request.json()
        try:
            target = build_target(
                kind="target",
                name="models",
                base_url=body.get("base_url"),
                api_key=body.get("api_key"),
                model="-",  # required by build_target; unused by GET /models
                api=validate_api(body.get("api")),
            )
        except ConfigError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        # Error text is already redacted by the client (key scrubbed).
        outcome, ids = await make_client(target).list_models()
        if not outcome.ok:
            return JSONResponse(
                {
                    "ok": False,
                    "status_code": outcome.status_code,
                    "error": outcome.error_message or outcome.error_type or "error",
                }
            )
        return JSONResponse(
            {
                "ok": True,
                "api": detect_api(target),
                "models": sorted(set(ids)),
                "duration_ms": round(outcome.duration_ms or 0.0, 1),
            }
        )

    @app.post("/api/audit/stream")
    async def audit_stream(request: Request) -> Any:
        body = await request.json()

        def sse(event: dict[str, Any]) -> str:
            # default=str so any unexpected evidence value can't break the stream.
            return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

        bl = body.get("baseline") or {}
        has_baseline = bool(bl.get("base_url") and bl.get("model"))

        # Validate up front so bad input fails as a clean error event, not a 500.
        try:
            suite = validate_suite(str(body.get("suite") or "standard"))
            target = build_target(
                kind="target",
                name=body.get("name") or "target",
                base_url=body.get("base_url"),
                api_key=body.get("api_key"),
                model=body.get("model"),
                claimed_model=body.get("claimed_model") or None,
                declared_provider=body.get("declared_provider") or None,
                api=validate_api(body.get("api")),
            )
            baseline = None
            if has_baseline:
                baseline = build_target(
                    kind="baseline",
                    name=bl.get("name") or "baseline",
                    base_url=bl.get("base_url"),
                    api_key=bl.get("api_key"),
                    model=bl.get("model"),
                    api=validate_api(bl.get("api")),
                )
            options = AuditOptions(
                suite=suite,
                # probe request mode (standard/deep; the full suite measures both)
                performance_streaming=body.get("performance_streaming") is not False,
            )
        except ConfigError as exc:
            msg = str(exc)  # bind now: `exc` is cleared when the except block exits

            async def err_stream():
                yield sse({"type": "error", "message": msg})
                yield sse({"type": "done"})

            return StreamingResponse(err_stream(), media_type="text/event-stream")

        async def event_stream():
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            async def run() -> None:
                try:
                    report = await run_audit(
                        target,
                        options,
                        baseline=baseline,
                        mode="compare" if baseline is not None else "check",
                        on_event=queue.put_nowait,
                    )
                    report_dict = json.loads(report.model_dump_json())
                    try:  # best-effort persist; never let history break the stream
                        from zing.web import history

                        history.save(report_dict)
                    except Exception:
                        pass
                    queue.put_nowait({"type": "report", "report": report_dict})
                except Exception as exc:  # surface any audit failure to the client
                    queue.put_nowait({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
                finally:
                    queue.put_nowait({"type": "done"})

            task = asyncio.create_task(run())
            loop = asyncio.get_running_loop()
            # Per-request records arrive in bursts (the reliability and probe
            # bursts); batch them into one "requests" event per window.
            pending: list[dict[str, Any]] = []
            flush_at = 0.0
            try:
                while True:
                    timeout = max(0.0, flush_at - loop.time()) if pending else None
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout)
                    except asyncio.TimeoutError:
                        yield sse({"type": "requests", "records": pending})
                        pending = []
                        continue
                    if event.get("type") == "request_done":
                        if not pending:
                            flush_at = loop.time() + _REQUEST_BATCH_SEC
                        pending.append(event["record"])
                        continue
                    if pending:
                        yield sse({"type": "requests", "records": pending})
                        pending = []
                    yield sse(event)
                    if event.get("type") == "done":
                        break
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/history")
    async def history_page(request: Request) -> Any:
        return _classic_page(request, "/history")

    @app.get("/api/history")
    async def history_list(limit: int = 50) -> Any:
        from zing.web import history

        return JSONResponse(history.recent(limit))

    @app.get("/api/history/trend")
    async def history_trend(base_url: str, claimed_model: str, limit: int = 30) -> Any:
        from zing.web import history

        return JSONResponse(history.trend(base_url, claimed_model, limit))

    @app.get("/api/history/{rid}")
    async def history_get(rid: int) -> Any:
        from zing.web import history

        report = history.get(rid)
        if report is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(report)

    @app.delete("/api/history/{rid}")
    async def history_delete(rid: int) -> Any:
        from zing.web import history

        history.delete(rid)
        return JSONResponse({"ok": True})

    @app.delete("/api/history")
    async def history_clear() -> Any:
        from zing.web import history

        history.clear()
        return JSONResponse({"ok": True})

    # ----- Scheduled watches (monitoring) -------------------------------- #
    @app.get("/watches")
    async def watches_page(request: Request) -> Any:
        return _classic_page(request, "/watches")

    @app.get("/api/watches")
    async def watches_list() -> Any:
        from zing.web import watches

        # list_all() never returns api_key, so this is safe to send to the browser.
        rows = watches.list_all()
        # Flag pinned profiles that differ from what the knowledge base resolves now.
        from zing.knowledge import load_knowledge_base

        try:
            kb = load_knowledge_base() if rows else None
        except Exception:
            kb = None
        for row in rows:
            row["kb_current_hash"] = None
            row["kb_changed"] = False
            if kb is None:
                continue
            try:
                current = _watch_knowledge(row, kb).get("profile_hash")
            except Exception:
                continue
            row["kb_current_hash"] = current
            pinned_hash = (row.get("kb") or {}).get("profile_hash")
            row["kb_changed"] = bool(pinned_hash and pinned_hash != current)
        return JSONResponse(rows)

    @app.post("/api/watches")
    async def watches_create(request: Request) -> Any:
        from zing.web import watches

        body = await request.json()
        # Validate the target + suite up front so bad input is a clean 400.
        try:
            suite = validate_suite(str(body.get("suite") or "standard"))
            build_target(
                kind="target",
                name=body.get("name") or "watch",
                base_url=body.get("base_url"),
                api_key=body.get("api_key"),
                model=body.get("model"),
                claimed_model=body.get("claimed_model") or None,
                declared_provider=body.get("declared_provider") or None,
                api=validate_api(body.get("api")),
            )
        except ConfigError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        cfg = {**body, "suite": suite}
        try:
            knowledge = _watch_knowledge(cfg)
        except Exception as exc:  # e.g. a broken ZING_KB_DIR file
            return JSONResponse({"error": f"knowledge base: {exc}"}, status_code=400)
        wid = watches.create(cfg, knowledge=knowledge)
        return JSONResponse({"ok": True, "id": wid}, status_code=201)

    @app.delete("/api/watches/{wid}")
    async def watches_delete(wid: int) -> Any:
        from zing.web import watches

        watches.delete(wid)
        return JSONResponse({"ok": True})

    @app.patch("/api/watches/{wid}")
    async def watches_patch(wid: int, request: Request) -> Any:
        from zing.web import watches

        row = watches.get(wid)
        if row is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        body = await request.json()
        if "enabled" in body:
            watches.set_enabled(wid, bool(body.get("enabled")))
        if "language" in body:
            watches.set_language(wid, body.get("language"))
        if body.get("repin"):
            # Re-pin to the profile the knowledge base resolves to now.
            try:
                watches.pin(wid, _watch_knowledge(row))
            except Exception as exc:
                return JSONResponse({"error": f"knowledge base: {exc}"}, status_code=400)
        return JSONResponse({"ok": True})

    @app.post("/api/watches/{wid}/run")
    async def watches_run(wid: int) -> Any:
        from zing.web import watches

        row = watches.get(wid)
        if row is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        # Run the same path the scheduler uses (audit + persist + alert + mark).
        try:
            await _run_one_watch(row)
        except Exception as exc:  # surface a clean error, not a 500 stack
            return JSONResponse(
                {"error": f"{type(exc).__name__}: {exc}"}, status_code=500
            )
        # Return the freshly saved report so the UI can show the result.
        from zing.web import history

        refreshed = watches.get(wid)
        report = None
        if refreshed and refreshed.get("last_report_id") is not None:
            report = history.get(int(refreshed["last_report_id"]))
        return JSONResponse({"ok": True, "report": report})

    # ----- Tools: embedding & rerank auditors (non-chat surface) ---------- #
    @app.get("/tools")
    async def tools_page(request: Request) -> Any:
        return _classic_page(request, "/tools")

    @app.post("/api/embed")
    async def embed_audit(request: Request) -> Any:
        # Lazy import: the embed auditor pulls in the client stack only on demand.
        from zing.embed_audit import audit_embeddings

        body = await request.json()
        try:
            target = build_target(
                kind="target",
                name=body.get("name") or "embed",
                base_url=body.get("base_url"),
                api_key=body.get("api_key"),
                model=body.get("model"),
                claimed_model=body.get("claimed_model") or None,
                declared_provider=body.get("declared_provider") or None,
                api=validate_api(body.get("api")),
            )
        except ConfigError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        # Resolve the expected output dimension: an explicit claimed value wins;
        # otherwise look the claimed (or requested) model up in the KB. 0 = unknown,
        # in which case the auditor records the observed dimension instead.
        claimed_dimensions = _coerce_int(body.get("claimed_dimensions"))
        if claimed_dimensions <= 0:
            claimed_dimensions = _kb_embedding_dimensions(
                target.claimed_model or target.model,
                target.declared_provider,
            )

        # The verdict is already redacted (api_key is fingerprinted in `target`).
        verdict = await audit_embeddings(target, claimed_dimensions)
        return JSONResponse(verdict)

    @app.post("/api/rerank")
    async def rerank_audit(request: Request) -> Any:
        from zing.embed_audit import audit_rerank

        body = await request.json()
        try:
            target = build_target(
                kind="target",
                name=body.get("name") or "rerank",
                base_url=body.get("base_url"),
                api_key=body.get("api_key"),
                model=body.get("model"),
                api=validate_api(body.get("api")),
            )
        except ConfigError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        # Use the caller's query/documents when given, else a built-in known-answer
        # probe where one document is unmistakably the most relevant.
        query = body.get("query")
        documents = body.get("documents")
        expected_top_index = body.get("expected_top_index")
        if not (isinstance(query, str) and query.strip()) or not (
            isinstance(documents, list) and len(documents) >= 2
        ):
            query = _RERANK_PROBE_QUERY
            documents = list(_RERANK_PROBE_DOCS)
            expected_top_index = _RERANK_PROBE_TOP
        expected_top_index = _coerce_int(expected_top_index)
        if not 0 <= expected_top_index < len(documents):
            expected_top_index = 0

        verdict = await audit_rerank(target, query, documents, expected_top_index)
        return JSONResponse(verdict)

    # Static assets (e.g. future JS/CSS split-outs) under /assets.
    assets = _STATIC / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    # 404 fallback to the SPA shell so deep links work.
    @app.exception_handler(404)
    async def spa_fallback(request: Request, exc: Any) -> Any:  # noqa: ARG001
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "not found"}, status_code=404)
        if request.url.path.startswith("/v2/static/"):
            return Response("not found", status_code=404, media_type="text/plain")
        if request.url.path.startswith("/v2/"):
            return FileResponse(_V2 / "index.html")
        return FileResponse(_STATIC / "index.html")

    return app
