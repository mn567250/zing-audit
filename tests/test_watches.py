"""Tests for the scheduled-watch store and its web endpoints.

Skipped automatically when the optional web extra (fastapi) isn't installed.
These never touch the network or trigger the real scheduler loop: they cover the
SQLite store roundtrip and the /api/watches CRUD endpoints, asserting that the
api_key never leaks into a listing.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from zing.web.server import create_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://localhost")


def test_watch_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    from zing.web import watches

    assert watches.list_all() == []

    wid = watches.create(
        {
            "name": "prod relay",
            "base_url": "https://relay.test/v1",
            "api_key": "sk-super-secret",
            "model": "gpt-4o",
            "claimed_model": "gpt-4o",
            "api": "openai",
            "suite": "standard",
            "interval_sec": 3600,
            "alert_on": "medium",
            "webhooks": ["https://hooks.slack.com/services/x"],
        }
    )
    assert isinstance(wid, int) and wid > 0

    # Listing must never expose the api_key, but should decode webhooks/enabled.
    rows = watches.list_all()
    assert len(rows) == 1
    row = rows[0]
    assert "api_key" not in row
    assert row["name"] == "prod relay"
    assert row["webhooks"] == ["https://hooks.slack.com/services/x"]
    assert row["enabled"] is True

    # get() is the server-side view and DOES carry the key for the scheduler.
    full = watches.get(wid)
    assert full is not None and full["api_key"] == "sk-super-secret"

    # A brand-new watch (never run) is due immediately.
    import time

    due = watches.due(time.time())
    assert len(due) == 1 and due[0]["id"] == wid

    # Record a run; risk/score/report id + run time persist.
    watches.mark_run(wid, "high", 21.0, 7, ts=time.time())
    after = watches.get(wid)
    assert after["last_risk"] == "high" and after["last_score"] == 21.0
    assert after["last_report_id"] == 7

    # With a fresh last_run and a long interval, it is no longer due.
    assert watches.due(time.time()) == []

    # Disable, then it is excluded from due() regardless of timing.
    watches.set_enabled(wid, False)
    assert watches.list_all()[0]["enabled"] is False
    assert watches.due(time.time() + 10_000) == []

    watches.delete(wid)
    assert watches.list_all() == []


def test_watches_endpoints_create_list_delete(tmp_path, monkeypatch, client):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))

    assert client.get("/api/watches").json() == []

    r = client.post(
        "/api/watches",
        json={
            "name": "my watch",
            "base_url": "https://relay.test/v1",
            "api_key": "sk-do-not-leak",
            "model": "gpt-4o",
            "suite": "standard",
            "alert_on": "medium",
            "interval_sec": 7200,
            "webhooks": ["https://example.com/hook"],
        },
    )
    assert r.status_code == 201
    wid = r.json()["id"]
    assert isinstance(wid, int) and wid > 0

    listed = client.get("/api/watches").json()
    assert len(listed) == 1
    one = listed[0]
    assert one["id"] == wid and one["name"] == "my watch"
    # The endpoint listing must NOT include the api_key anywhere.
    assert "api_key" not in one
    assert "sk-do-not-leak" not in r.text
    assert "sk-do-not-leak" not in client.get("/api/watches").text

    # PATCH toggles enabled.
    assert client.patch(f"/api/watches/{wid}", json={"enabled": False}).status_code == 200
    assert client.get("/api/watches").json()[0]["enabled"] is False

    # DELETE removes it.
    assert client.delete(f"/api/watches/{wid}").status_code == 200
    assert client.get("/api/watches").json() == []


def test_watches_create_bad_target_is_clean_400(tmp_path, monkeypatch, client):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    r = client.post("/api/watches", json={"base_url": "", "model": ""})
    assert r.status_code == 400 and "error" in r.json()
    # Nothing was persisted.
    assert client.get("/api/watches").json() == []


def test_watches_create_unknown_suite_is_400(tmp_path, monkeypatch, client):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    r = client.post(
        "/api/watches",
        json={"base_url": "https://x/v1", "model": "gpt-4o", "suite": "bogus"},
    )
    assert r.status_code == 400


def test_watches_page_and_nav_link(client):
    r = client.get("/watches")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "监控" in r.text
    # The SPA exposes a nav link to /watches.
    assert 'href="/watches"' in client.get("/").text


def test_patch_and_run_missing_watch_404(tmp_path, monkeypatch, client):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    assert client.patch("/api/watches/999999", json={"enabled": True}).status_code == 404
    assert client.post("/api/watches/999999/run").status_code == 404


def test_watch_alert_language_default_create_patch(tmp_path, monkeypatch, client):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    base = {"base_url": "https://relay.test/v1", "model": "gpt-4o", "webhooks": []}

    # No language given -> English; a supported one is stored; junk -> English.
    a = client.post("/api/watches", json=base).json()["id"]
    b = client.post("/api/watches", json={**base, "language": "de"}).json()["id"]
    c = client.post("/api/watches", json={**base, "language": "klingon"}).json()["id"]
    langs = {w["id"]: w["language"] for w in client.get("/api/watches").json()}
    assert langs == {a: "en", b: "de", c: "en"}

    assert client.patch(f"/api/watches/{a}", json={"language": "zh"}).status_code == 200
    assert {w["id"]: w["language"] for w in client.get("/api/watches").json()}[a] == "zh"


def test_watch_db_from_before_alert_languages_is_migrated(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    from zing.web import watches

    # A watches table as created by earlier versions (no `language` column).
    path = watches._db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE watches (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, base_url TEXT,"
            " api_key TEXT, model TEXT, claimed_model TEXT, api TEXT, declared_provider TEXT,"
            " suite TEXT, interval_sec INTEGER, alert_on TEXT, webhooks TEXT, enabled INTEGER DEFAULT 1,"
            " created_ts REAL, last_run_ts REAL, last_risk TEXT, last_score REAL, last_report_id INTEGER)"
        )
        conn.execute("INSERT INTO watches (name, base_url, model, webhooks) VALUES ('old', 'https://x/v1', 'm', '[]')")

    [old] = watches.list_all()
    assert old["name"] == "old" and old["language"] == "en"
    assert old["source_report_id"] is None and old["has_key"] is False
    watches.set_language(old["id"], "fr")
    assert watches.get(old["id"])["language"] == "fr"


async def test_scheduled_watch_alerts_in_its_language(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from zing import notify
    from zing.models import AuditReport
    from zing.web import server, watches

    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    report = AuditReport.model_validate(
        json.loads((Path(__file__).parent / "fixtures" / "web_report.json").read_text("utf-8"))
    )

    async def fake_run_audit(*_a, **_k):
        return report

    sent: list[dict] = []

    async def fake_send(url, report_dict, **kw):
        sent.append({"url": url, **kw})
        return True

    monkeypatch.setattr(server, "run_audit", fake_run_audit)
    monkeypatch.setattr(notify, "send", fake_send)
    wid = watches.create({
        "base_url": "https://relay.test/v1", "api_key": "sk-x", "model": "gpt-4o",
        "alert_on": "medium", "webhooks": ["https://hooks.slack.com/services/x"], "language": "it",
    })
    await server._run_one_watch(watches.get(wid))
    assert [s["lang"] for s in sent] == ["it"]


# ----- scheduling a history run as a monitor ------------------------------ #


def _saved_report(**overrides):
    import json
    from pathlib import Path

    from zing.web import history

    report = json.loads((Path(__file__).parent / "fixtures" / "web_report.json").read_text("utf-8"))
    report.update(overrides)
    return history.save(report)


def test_schedule_history_run_creates_a_paused_draft(tmp_path, monkeypatch, client):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    rid = _saved_report()
    r = client.post(f"/api/watches/from-history/{rid}", json={"language": "de"})
    assert r.status_code == 201
    wid = r.json()["id"]
    [w] = client.get("/api/watches").json()
    assert w["id"] == wid and w["source_report_id"] == rid
    # the run's configuration, but no schedule, no key, and switched off
    assert w["base_url"] == "http://127.0.0.1:9099/v1" and w["model"] == "gpt-4o"
    assert w["name"] == "gpt-4o" and w["suite"] == "standard" and w["api"] == "auto"
    assert w["interval_sec"] is None and w["enabled"] is False and w["has_key"] is False
    assert w["language"] == "de" and w["alert_on"] == "medium" and w["webhooks"] == []

    assert client.post("/api/watches/from-history/999999").status_code == 404


def test_schedule_keeps_a_custom_suites_dimensions(tmp_path, monkeypatch, client):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    rid = _saved_report(suite="custom", dimensions_selected=["security", "protocol"])
    client.post(f"/api/watches/from-history/{rid}")
    [w] = client.get("/api/watches").json()
    assert w["suite"] == "custom" and sorted(w["dimensions"]) == ["protocol", "security"]


def test_draft_needs_interval_and_key_before_it_runs(tmp_path, monkeypatch, client):
    import time

    from zing.web import watches

    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    wid = client.post(f"/api/watches/from-history/{_saved_report()}").json()["id"]

    # never picked up by the scheduler, even if switched on behind the API's back
    watches.set_enabled(wid, True)
    assert watches.due(time.time()) == []
    watches.set_enabled(wid, False)

    r = client.patch(f"/api/watches/{wid}", json={"enabled": True})
    assert r.status_code == 400 and "interval" in r.json()["error"]
    r = client.patch(f"/api/watches/{wid}", json={"enabled": True, "interval_sec": 600})
    assert r.status_code == 400 and "API key" in r.json()["error"]
    # the refused PATCH changed nothing
    assert client.get("/api/watches").json()[0]["interval_sec"] is None
    assert client.post(f"/api/watches/{wid}/run").status_code == 400

    r = client.patch(
        f"/api/watches/{wid}", json={"enabled": True, "interval_sec": 600, "api_key": "sk-draft-secret"}
    )
    assert r.status_code == 200
    [w] = client.get("/api/watches").json()
    assert w["enabled"] is True and w["interval_sec"] == 600 and w["has_key"] is True
    assert "sk-draft-secret" not in client.get("/api/watches").text
    assert watches.get(wid)["api_key"] == "sk-draft-secret"
    assert [d["id"] for d in watches.due(time.time())] == [wid]


def test_patch_validates_schedule_and_alert_settings(tmp_path, monkeypatch, client):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    wid = client.post(
        "/api/watches", json={"base_url": "https://relay.test/v1", "model": "gpt-4o", "api_key": "sk-a"}
    ).json()["id"]
    url = f"/api/watches/{wid}"
    for bad in ({"interval_sec": 10}, {"interval_sec": "600"}, {"interval_sec": True},
                {"alert_on": "extreme"}, {"webhooks": "https://x"}, {"webhooks": ["ftp://x"]}):
        assert client.patch(url, json=bad).status_code == 400, bad
    assert client.patch(url, json={
        "interval_sec": 900, "alert_on": "high", "webhooks": [" https://hooks.test/a ", ""], "api_key": "  ",
    }).status_code == 200
    [w] = client.get("/api/watches").json()
    assert w["interval_sec"] == 900 and w["alert_on"] == "high" and w["webhooks"] == ["https://hooks.test/a"]
    from zing.web import watches

    assert watches.get(wid)["api_key"] == "sk-a"  # a blank key leaves the stored one alone
    # a form-created keyless watch (a relay without auth) can still be switched on
    keyless = client.post("/api/watches", json={"base_url": "https://open.test/v1", "model": "m", "enabled": False}).json()["id"]
    assert client.patch(f"/api/watches/{keyless}", json={"enabled": True}).status_code == 200
