"""Tests for the web Tools page (embedding + rerank auditors).

Skipped automatically when the optional web extra (fastapi) isn't installed.
No network is touched: the auditors are monkeypatched to return canned verdict
dicts, so we only exercise the HTTP plumbing — request parsing, KB dimension
resolution, ConfigError -> 400, secret hygiene, and the served page/nav.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import zing.embed_audit as embed_audit  # noqa: E402
from zing.web.server import create_app  # noqa: E402

SECRET = "sk-tools-secret-key-abcdef123456"


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://localhost")


def _embed_verdict(target) -> dict:
    # Mirror the real audit_embeddings verdict shape, already redacted (api key is
    # a fingerprint, never the raw secret).
    return {
        "risk_level": "clean",
        "score": 100.0,
        "findings": [
            {
                "id": "embed.dimension",
                "title": "Vector dimension matches the claimed model",
                "status": "pass",
                "severity": "info",
                "summary": "Returned 3072-d vectors, as expected.",
                "evidence": {"returned": 3072, "claimed": 3072},
            }
        ],
        "target": {
            "name": target.name,
            "base_url": target.base_url,
            "model": target.model,
            "claimed_model": target.claimed_model,
            "declared_provider": target.declared_provider,
            "api_key_fingerprint": "sha256:deadbeef",
        },
    }


def _rerank_verdict(target) -> dict:
    return {
        "risk_level": "clean",
        "score": 100.0,
        "findings": [
            {
                "id": "rerank.known_answer",
                "title": "Reranker ranks the obvious answer first",
                "status": "pass",
                "severity": "info",
                "summary": "Document 2 ranked first.",
                "evidence": {"top_index": 2, "expected": 2, "ranking": [2, 0, 1, 3]},
            }
        ],
        "target": {
            "name": target.name,
            "base_url": target.base_url,
            "model": target.model,
            "claimed_model": target.claimed_model,
            "declared_provider": target.declared_provider,
            "api_key_fingerprint": "sha256:cafef00d",
        },
    }


def test_embed_endpoint_returns_verdict_and_hides_secret(client, monkeypatch):
    captured = {}

    async def fake_audit(target, claimed_dimensions):
        captured["claimed_dimensions"] = claimed_dimensions
        captured["api_key"] = target.api_key  # the real (resolved) secret
        return _embed_verdict(target)

    monkeypatch.setattr(embed_audit, "audit_embeddings", fake_audit)

    r = client.post(
        "/api/embed",
        json={
            "base_url": "https://relay.embed.test/v1",
            "api_key": SECRET,
            "model": "text-embedding-3-large",
            "claimed_dimensions": 3072,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["risk_level"] == "clean" and body["score"] == 100.0
    assert body["findings"][0]["id"] == "embed.dimension"
    assert "target" in body
    # The verdict reached the auditor with the resolved secret...
    assert captured["api_key"] == SECRET
    assert captured["claimed_dimensions"] == 3072
    # ...but the secret must never cross back to the browser.
    raw = r.text
    assert SECRET not in raw
    assert "api_key" not in body["target"]
    assert "api_key_fingerprint" in body["target"]


def test_embed_resolves_dimension_from_kb_when_not_given(client, monkeypatch):
    captured = {}

    async def fake_audit(target, claimed_dimensions):
        captured["claimed_dimensions"] = claimed_dimensions
        return _embed_verdict(target)

    monkeypatch.setattr(embed_audit, "audit_embeddings", fake_audit)
    # No claimed_dimensions in the request and an unknown model -> 0 (skip match),
    # exercising the KB-resolution branch without depending on KB contents.
    r = client.post(
        "/api/embed",
        json={
            "base_url": "https://relay.embed.test/v1",
            "api_key": SECRET,
            "model": "totally-unknown-embedding-xyz",
        },
    )
    assert r.status_code == 200
    assert captured["claimed_dimensions"] == 0


def test_embed_bad_target_is_400(client, monkeypatch):
    async def fake_audit(target, claimed_dimensions):  # pragma: no cover - never called
        raise AssertionError("auditor must not run on a bad target")

    monkeypatch.setattr(embed_audit, "audit_embeddings", fake_audit)
    # Missing base_url -> ConfigError -> clean 400, not a 500 and no audit.
    r = client.post("/api/embed", json={"model": "m", "api_key": SECRET})
    assert r.status_code == 400
    assert "error" in r.json()
    assert SECRET not in r.text


def test_rerank_endpoint_uses_builtin_probe_and_hides_secret(client, monkeypatch):
    captured = {}

    async def fake_audit(target, query, documents, expected_top_index):
        captured["query"] = query
        captured["documents"] = documents
        captured["expected_top_index"] = expected_top_index
        captured["api_key"] = target.api_key
        return _rerank_verdict(target)

    monkeypatch.setattr(embed_audit, "audit_rerank", fake_audit)

    # No query/documents -> the built-in known-answer probe is used.
    r = client.post(
        "/api/rerank",
        json={
            "base_url": "https://relay.rerank.test/v1",
            "api_key": SECRET,
            "model": "bge-reranker-v2-m3",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["risk_level"] == "clean"
    assert body["findings"][0]["id"] == "rerank.known_answer"
    # Built-in probe wired in.
    assert isinstance(captured["query"], str) and captured["query"]
    assert len(captured["documents"]) >= 2
    assert 0 <= captured["expected_top_index"] < len(captured["documents"])
    # Secret hygiene.
    assert SECRET not in r.text
    assert "api_key" not in body["target"]


def test_rerank_accepts_custom_probe(client, monkeypatch):
    captured = {}

    async def fake_audit(target, query, documents, expected_top_index):
        captured.update(
            query=query, documents=documents, expected_top_index=expected_top_index
        )
        return _rerank_verdict(target)

    monkeypatch.setattr(embed_audit, "audit_rerank", fake_audit)
    r = client.post(
        "/api/rerank",
        json={
            "base_url": "https://relay.rerank.test/v1",
            "api_key": SECRET,
            "model": "bge-reranker-v2-m3",
            "query": "which fruit is yellow?",
            "documents": ["A banana is yellow.", "The sky is blue."],
            "expected_top_index": 0,
        },
    )
    assert r.status_code == 200
    assert captured["query"] == "which fruit is yellow?"
    assert captured["documents"] == ["A banana is yellow.", "The sky is blue."]
    assert captured["expected_top_index"] == 0


def test_rerank_bad_target_is_400(client, monkeypatch):
    async def fake_audit(*a, **k):  # pragma: no cover - never called
        raise AssertionError("auditor must not run on a bad target")

    monkeypatch.setattr(embed_audit, "audit_rerank", fake_audit)
    r = client.post("/api/rerank", json={"base_url": "", "model": ""})
    assert r.status_code == 400
    assert "error" in r.json()


def test_serves_tools_page_and_index_nav(client):
    r = client.get("/tools")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "工具箱" in r.text and "嵌入审计" in r.text and "重排审计" in r.text
    # The home page links to /tools in its nav.
    index = client.get("/").text
    assert 'href="/tools"' in index


# ----- /api/models: relay model listing for the picker's custom provider ----- #


def _mock_relay(monkeypatch, handler):
    """Route every client make_client builds through an httpx.MockTransport."""
    import httpx

    import zing.clients as clients

    real = clients.make_client
    seen: list = []

    def recording(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        clients,
        "make_client",
        lambda cfg, **_: real(cfg, transport=httpx.MockTransport(recording)),
    )
    return seen


def test_models_endpoint_lists_relay_models_and_hides_secret(client, monkeypatch):
    import httpx

    seen = _mock_relay(
        monkeypatch,
        lambda req: httpx.Response(
            200, json={"data": [{"id": "gpt-4o"}, {"id": "deepseek-chat"}, {"id": "gpt-4o"}]}
        ),
    )
    r = client.post(
        "/api/models",
        json={"base_url": "https://relay.example.com/v1", "api_key": SECRET, "api": "openai"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["api"] == "openai"
    assert data["models"] == ["deepseek-chat", "gpt-4o"]
    assert SECRET not in r.text
    assert str(seen[0].url) == "https://relay.example.com/v1/models"
    assert seen[0].headers["authorization"] == f"Bearer {SECRET}"


def test_models_endpoint_works_without_api_key(client, monkeypatch):
    import httpx

    seen = _mock_relay(
        monkeypatch, lambda req: httpx.Response(200, json={"data": [{"id": "llama3.2"}]})
    )
    # Self-hosted relays (Ollama, LM Studio) need no key.
    r = client.post("/api/models", json={"base_url": "http://localhost:11434/v1"})
    assert r.status_code == 200
    assert r.json()["models"] == ["llama3.2"]
    assert "authorization" not in seen[0].headers


def test_models_endpoint_reports_relay_error_without_secret(client, monkeypatch):
    import httpx

    _mock_relay(
        monkeypatch,
        lambda req: httpx.Response(401, json={"error": {"message": f"bad key {SECRET}"}}),
    )
    r = client.post(
        "/api/models",
        json={"base_url": "https://relay.example.com/v1", "api_key": SECRET},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["status_code"] == 401
    assert "bad key" in data["error"]
    assert SECRET not in r.text


def test_models_endpoint_bad_base_url_is_400(client):
    r = client.post("/api/models", json={"base_url": "ftp://nope", "api_key": SECRET})
    assert r.status_code == 400
    assert "base_url" in r.json()["error"]


def test_modelpicker_offers_custom_relay_provider(client):
    r = client.get("/modelpicker.js")
    assert r.status_code == 200
    assert "/api/models" in r.text
    assert "Custom (from relay)" in r.text
