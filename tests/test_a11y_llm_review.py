"""Offline tests of the advisory LLM review (tests/a11y/llm_review.py).

No browser and no network: the pure extraction post-processing, the request
building and the response parsing are tested directly, the HTTP client against
an httpx.MockTransport.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from tests.a11y import llm_review as lr

RAW = {
    "title": "  zing —   audit  ",
    "lang": "en",
    "headings": [[1, "Audit"], [1, "Audit"], [2, "x" * 400]],
    "links": [
        {"name": "More", "href": "/a", "context": ""},
        {"name": "More", "href": "/b", "context": "Read the guide"},
        {"name": "More", "href": "/a", "context": ""},
    ],
    "controls": [{"role": "button", "name": "Go", "state": ""}],
    "fields": [{"label": "Relay URL", "placeholder": "https://…", "description": "", "required": False, "type": "text"}],
    "images": [
        {"kind": "svg", "name": "", "decorative": True},
        {"kind": "img", "name": "chart.png", "decorative": False, "src": "chart.png"},
    ],
    "instructions": [f"sentence {i}" for i in range(lr.LIMITS["instructions"] + 7)],
}


def _answer(findings: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    body = {
        "model": lr.MODEL,
        "stop_reason": "end_turn",
        "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": json.dumps({"findings": findings})}],
        "usage": {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 2000},
    }
    body.update(extra)
    return body


F_LINK = {"step": "9.2.4.4", "lang": "en", "element": 'link "More"', "problem": "ambiguous", "suggestion": "Name it"}


# --------------------------------------------------------------------------- #
# compaction
# --------------------------------------------------------------------------- #
def test_compact_page_cleans_dedupes_and_caps() -> None:
    rec = lr.compact_page(RAW, [{"form": "Start", "text": " Invalid ", "field": ""}])
    assert rec["title"] == "zing — audit"
    assert rec["headings"][0] == [1, "Audit"] and len(rec["headings"]) == 2
    assert len(rec["headings"][1][1]) == lr.MAX_TEXT and rec["headings"][1][1].endswith("…")
    # exact duplicates go, same name with another target stays
    assert [x["href"] for x in rec["links"]] == ["/a", "/b"]
    # empty values are dropped from items
    assert rec["links"][0] == {"name": "More", "href": "/a"}
    assert rec["fields"] == [{"label": "Relay URL", "placeholder": "https://…", "type": "text"}]
    # decorative images are counted, not sent
    assert rec["decorative_images"] == 1
    assert rec["images"] == [{"kind": "img", "name": "chart.png", "src": "chart.png"}]
    assert len(rec["instructions"]) == lr.LIMITS["instructions"]
    assert rec["truncated"] == {"instructions": 7}
    assert rec["messages"] == [{"form": "Start", "text": "Invalid"}]


def test_translation_view_puts_english_first() -> None:
    recs = {lang: lr.compact_page(dict(RAW, title=f"T-{lang}")) for lang in ("zh", "de", "en")}
    view = lr.translation_view(recs)
    assert list(view) == ["en", "de", "zh"]
    assert view["de"]["title"] == "T-de"
    assert view["en"]["headings"][0] == "Audit"
    assert view["en"]["links"] == ["More", "More"]


# --------------------------------------------------------------------------- #
# request
# --------------------------------------------------------------------------- #
def test_build_request_shape() -> None:
    rec = lr.compact_page(RAW)
    body = lr.build_request("page", "audit", rec, lang="de")
    assert body["model"] == "claude-opus-5-5"
    # the rubric is the cached system prompt; nothing volatile in it
    assert body["system"] == [{"type": "text", "text": lr.RUBRIC, "cache_control": {"type": "ephemeral"}}]
    assert len(lr.RUBRIC) > 4000  # well above the 512-token cache minimum
    for step in lr.STEPS:
        assert f'"{step}"' in lr.RUBRIC
    # sampling parameters are rejected by this model; the answer is schema-bound
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(body)
    assert body["output_config"]["format"] == {"type": "json_schema", "schema": lr.FINDINGS_SCHEMA}
    assert body["output_config"]["effort"] == "high"
    assert body["fallbacks"] == "default"
    user = body["messages"][0]["content"]
    assert body["messages"][0]["role"] == "user"
    assert '{"lang":"de"' not in user and '"lang": "de"' in user and '"page": "audit"' in user
    data = user.split("<page_data>\n", 1)[1].rsplit("\n</page_data>", 1)[0]
    assert json.loads(data) == rec
    # deterministic: same input, same bytes
    assert json.dumps(lr.build_request("page", "audit", rec, lang="de")) == json.dumps(body)


def test_schema_steps_match_rubric() -> None:
    enum = lr.FINDINGS_SCHEMA["properties"]["findings"]["items"]["properties"]["step"]["enum"]
    assert enum == list(lr.STEPS)
    assert {"9.1.1.1", "9.2.4.4", "9.2.4.6", "9.1.3.3", "9.3.3.3", "9.3.3.2", "translation"} == set(enum)


# --------------------------------------------------------------------------- #
# response parsing
# --------------------------------------------------------------------------- #
def test_parse_response_keeps_valid_findings_only() -> None:
    body = _answer(
        [
            F_LINK,
            dict(F_LINK),  # duplicate
            dict(F_LINK, step="1.4.3"),  # not a reviewed step
            dict(F_LINK, step="translation"),  # wrong task
            dict(F_LINK, element=""),  # unusable
            "junk",
        ]
    )
    fs = lr.parse_response(body, "page", "audit", "de")
    assert fs == [
        {"step": "9.2.4.4", "page": "audit", "lang": "de", "element": 'link "More"', "problem": "ambiguous", "suggestion": "Name it"}
    ]


def test_parse_response_translation_keeps_model_lang() -> None:
    body = _answer([dict(F_LINK, step="translation", lang="fr"), F_LINK])
    fs = lr.parse_response(body, "translation", "kb")
    assert [(f["step"], f["lang"]) for f in fs] == [("translation", "fr")]


@pytest.mark.parametrize(
    "body, msg",
    [
        ({"stop_reason": "refusal", "stop_details": {"category": "cyber"}, "content": []}, "refusal"),
        ({"stop_reason": "max_tokens", "content": [{"type": "text", "text": '{"find'}]}, "max_tokens"),
        ({"stop_reason": "end_turn", "content": [{"type": "text", "text": "no json"}]}, "not JSON"),
        ({"stop_reason": "end_turn", "content": [{"type": "text", "text": "[]"}]}, "findings"),
        ({"stop_reason": "end_turn", "content": []}, "no text"),
    ],
)
def test_parse_response_errors(body: dict[str, Any], msg: str) -> None:
    with pytest.raises(lr.ReviewError, match=msg):
        lr.parse_response(body, "page", "audit", "en")


def test_aggregate_and_cost() -> None:
    f = lr.parse_response(_answer([F_LINK]), "page", "audit", "en")
    steps = lr.aggregate(f, {"page": 1})
    assert set(steps) == set(lr.STEPS)
    assert steps["9.2.4.4"]["verdict"] == "issues"
    assert steps["9.2.4.4"]["findings"] == [
        {"page": "audit", "lang": "en", "element": 'link "More"', "problem": "ambiguous", "suggestion": "Name it"}
    ]
    assert steps["9.1.1.1"]["verdict"] == "ok"
    assert steps["translation"]["verdict"] == "not-reviewed"
    assert lr.usage_cost({"input_tokens": 1_000_000, "output_tokens": 1_000_000}) == pytest.approx(24.0)
    assert lr.usage_cost({"cache_read_input_tokens": 1_000_000}) == pytest.approx(0.2)


# --------------------------------------------------------------------------- #
# HTTP client (mocked transport)
# --------------------------------------------------------------------------- #
def _client(handler: Any, **kw: Any) -> tuple[lr.Client, list[float]]:
    sleeps: list[float] = []
    c = lr.Client("sk-test", transport=httpx.MockTransport(handler), sleep=sleeps.append, **kw)
    return c, sleeps


def test_client_sends_headers_and_counts_usage() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=_answer([F_LINK]))

    c, sleeps = _client(handler)
    out = c.send(lr.build_request("page", "audit", {}, lang="en"))
    assert out["model"] == lr.MODEL and not sleeps
    req = seen[0]
    assert str(req.url) == lr.API_URL
    assert req.headers["x-api-key"] == "sk-test"
    assert req.headers["anthropic-version"] == "2023-06-01"
    assert req.headers["anthropic-beta"] == lr.FALLBACK_BETA
    assert json.loads(req.content)["model"] == lr.MODEL
    assert c.requests == 1 and c.usage["cache_read_input_tokens"] == 2000
    assert c.cost == pytest.approx(lr.usage_cost(_answer([])["usage"]))


def test_client_retries_with_backoff() -> None:
    codes = iter([529, 429, 200])

    def handler(req: httpx.Request) -> httpx.Response:
        code = next(codes)
        if code == 429:
            return httpx.Response(429, headers={"retry-after": "7"}, json={"error": {}})
        if code == 200:
            return httpx.Response(200, json=_answer([]))
        return httpx.Response(code, json={"error": {"type": "overloaded_error"}})

    c, sleeps = _client(handler)
    c.send({"x": 1})
    assert len(sleeps) == 2
    assert 2.0 <= sleeps[0] <= 3.0  # exponential backoff with jitter
    assert sleeps[1] == 7.0  # retry-after honoured
    assert c.requests == 1  # retries do not count against the request budget


def test_client_retries_transport_errors_then_gives_up() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    c, sleeps = _client(handler, retries=3)
    with pytest.raises(lr.ReviewError, match="gave up after 4 attempts: ConnectError"):
        c.send({})
    assert len(sleeps) == 3 and sleeps == sorted(sleeps)


def test_client_does_not_retry_client_errors() -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "bad"}})

    c, sleeps = _client(handler)
    with pytest.raises(lr.ReviewError, match="HTTP 400"):
        c.send({})
    assert len(calls) == 1 and not sleeps


def test_cost_guard_stops_sending() -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_answer([]))

    c, _ = _client(handler, max_requests=2)
    c.send({})
    c.send({})
    with pytest.raises(lr.ReviewError, match="request limit"):
        c.send({})
    assert len(calls) == 2

    c, _ = _client(handler, max_cost=0.001)
    c.send({})
    with pytest.raises(lr.ReviewError, match="cost limit"):
        c.send({})


# --------------------------------------------------------------------------- #
# whole review (mocked API, no browser)
# --------------------------------------------------------------------------- #
def test_review_end_to_end() -> None:
    records = {
        "audit": {"en": lr.compact_page(RAW), "de": lr.compact_page(RAW)},
        "kb": {"en": lr.compact_page(RAW)},
    }
    asked: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        asked.append(body)
        head = json.loads(body["messages"][0]["content"].split("\n")[1])
        if head["task"] == "translation":
            return httpx.Response(200, json=_answer([dict(F_LINK, step="translation", lang="de")]))
        if head["page"] == "kb":
            return httpx.Response(200, json={"stop_reason": "refusal", "content": [], "usage": {}})
        return httpx.Response(200, json=_answer([F_LINK]))

    c, _ = _client(handler)
    rep = lr.review(records, c, pages={"audit": "/v2/", "kb": "/v2/kb"}, log=lambda s: None)
    # page+lang requests, plus one translation request for the page with 2 languages
    assert [(e["task"], e["page"], e["lang"]) for e in rep["pages"]] == [
        ("page", "audit", "en"),
        ("page", "audit", "de"),
        ("translation", "audit", "all"),
        ("page", "kb", "en"),
    ]
    assert len(asked) == 4
    assert [e["status"] for e in rep["pages"]] == ["reviewed", "reviewed", "reviewed", "error"]
    assert "refusal" in rep["pages"][3]["error"]
    assert rep["pages"][0]["path"] == "/v2/" and "data" in rep["pages"][0]
    assert {f["lang"] for f in rep["steps"]["9.2.4.4"]["findings"]} == {"en", "de"}
    assert rep["steps"]["translation"]["verdict"] == "issues"
    assert rep["steps"]["9.3.3.3"]["verdict"] == "ok"
    assert rep["model"] == lr.MODEL and rep["requests"] == 4 and rep["cost_usd_estimate"] > 0
    assert set(rep) >= {"generated_at", "model", "pages", "steps"}
    json.dumps(rep)  # serialisable


def test_review_dry_run_marks_steps_not_reviewed() -> None:
    rep = lr.review({"audit": {"en": lr.compact_page(RAW)}}, None, log=lambda s: None)
    assert [e["status"] for e in rep["pages"]] == ["dry-run"]
    assert {s["verdict"] for s in rep["steps"].values()} == {"not-reviewed"}


def test_main_without_key_is_a_no_op(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = tmp_path / "r.json"
    assert lr.main(["--out", str(out)]) == 0
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().out
    assert not out.exists()
