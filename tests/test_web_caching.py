"""Compression and browser caching of the web UI (zing/web/caching.py)."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.responses import PlainTextResponse, StreamingResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

from zing.web import caching  # noqa: E402
from zing.web.server import create_app  # noqa: E402

IMMUTABLE = "public, max-age=31536000, immutable"
_REF = re.compile(r'(?:src|href)="(/[^"]+)"')


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://localhost")


def _versioned(html: str) -> list[str]:
    return [u for u in _REF.findall(html) if "?v=" in u]


@pytest.mark.parametrize(
    "path", ["/v2/", "/v2/history", "/v2/watches", "/v2/tools", "/v2/kb", "/v2/accessibility"]
)
def test_v2_pages_version_their_assets_and_are_revalidated(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["content-type"].startswith("text/html")
    urls = _versioned(r.text)
    assert any(u.startswith("/v2/static/zing.css?v=") for u in urls)
    assert any(u.startswith("/i18n.js?v=") for u in urls)
    # every local script / stylesheet is versioned; the generated /locales.js is not
    assets = [u for u in _REF.findall(r.text) if re.search(r"\.(?:js|css)(?:\?|$)", u)]
    assert set(assets) - set(urls) <= {"/locales.js"}
    # conditional request -> 304 with the same caching policy
    again = client.get(path, headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    assert again.headers["cache-control"] == "no-cache"
    assert again.headers["x-frame-options"] == "DENY"


def test_classic_pages_and_spa_fallback_are_versioned_too(client):
    for path in ("/?ui=v1", "/history", "/v2/some/deep/link", "/some/deep/link"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-cache"
        assert _versioned(r.text), path


def test_versioned_assets_are_immutable_and_unversioned_ones_revalidate(client):
    urls = _versioned(client.get("/v2/").text)
    assert len(urls) >= 8
    for url in urls:
        r = client.get(url)
        assert r.status_code == 200, url
        assert r.headers["cache-control"] == IMMUTABLE, url
        not_modified = client.get(url, headers={"If-None-Match": r.headers["etag"]})
        assert not_modified.status_code == 304, url
        assert not_modified.headers["cache-control"] == IMMUTABLE
        bare = client.get(url.split("?")[0])
        assert bare.headers["cache-control"] == "no-cache", url
        # a stale (or forged) version must not be pinned for a year
        stale = client.get(url.split("?")[0] + "?v=000000000000")
        assert stale.headers["cache-control"] == "no-cache", url


def test_root_scripts_keep_their_type_and_answer_304(client):
    for name in caching.ROOT_ASSETS:
        r = client.get(f"/{name}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/javascript")
        assert client.get(f"/{name}", headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_missing_static_file_is_still_a_plain_404(client):
    r = client.get("/v2/static/nope.js?v=abc")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/plain")


def test_responses_are_gzipped_when_large_enough(client):
    page = client.get("/v2/")
    assert page.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in page.headers["vary"].lower()
    assert client.get("/locales.js").headers["content-encoding"] == "gzip"
    assert client.get("/api/kb").headers["content-encoding"] == "gzip"
    # tiny responses are left alone
    assert "content-encoding" not in client.get("/api/health").headers
    # and nothing is compressed for a client that does not ask for it
    plain = client.get("/v2/", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers


def test_security_checks_still_run_first(client):
    r = client.get("/v2/", headers={"Host": "evil.example"})
    assert r.status_code == 421
    assert "content-encoding" not in r.headers


def _events() -> StreamingResponse:
    async def gen():
        for i in range(3):
            yield f"data: {'x' * 2000} {i}\n\n"

    # text/plain on purpose: the path alone must keep SSE uncompressed, whatever
    # the installed Starlette's content-type exclusions are.
    return StreamingResponse(gen(), media_type="text/plain")


def _big(_request) -> PlainTextResponse:
    return PlainTextResponse("y" * 5000)


def test_sse_paths_are_never_compressed():
    app = Starlette(routes=[
        Route("/api/jobs/{job_id}/events", lambda _r: _events()),
        Route("/api/audit/stream", lambda _r: _events(), methods=["POST"]),
        Route("/api/other", _big),
    ])
    c = TestClient(caching.CompressionMiddleware(app))
    for method, path in (("GET", "/api/jobs/abc/events"), ("POST", "/api/audit/stream")):
        r = c.request(method, path)
        assert "content-encoding" not in r.headers, path
        assert r.text.count("data: ") == 3
    assert c.get("/api/other").headers["content-encoding"] == "gzip"


def test_edited_files_get_a_new_version_without_restart(tmp_path, monkeypatch):
    static = tmp_path / "static"
    (static / "v2").mkdir(parents=True)
    asset = static / "v2" / "a.css"
    asset.write_text("body{}")
    page = static / "v2" / "p.html"
    page.write_text('<link rel="stylesheet" href="/v2/static/a.css"><a href="/v2/">x</a>')
    monkeypatch.setattr(caching, "_STATIC", static)
    monkeypatch.setattr(caching, "_V2", static / "v2")

    first = caching.html_page(page).body.decode()
    v1 = re.search(r"a\.css\?v=(\w+)", first)
    assert v1 and 'href="/v2/"' in first
    assert caching.html_page(page).body.decode() == first  # cached

    asset.write_text("body{color:red}")
    st = asset.stat()
    os.utime(asset, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    second = caching.html_page(page).body.decode()
    v2 = re.search(r"a\.css\?v=(\w+)", second)
    assert v2 and v2[1] != v1[1]

    page.write_text('<script src="/v2/static/a.css"></script>')
    st = page.stat()
    os.utime(page, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert "<script" in caching.html_page(page).body.decode()


def test_asset_file_stays_inside_the_static_dirs():
    assert caching.asset_file("/v2/static/../../server.py") is None
    assert caching.asset_file("/v2/static/") is None
    assert caching.asset_file("/locales.js") is None
    assert caching.asset_file("/i18n.js") == Path(caching._STATIC) / "i18n.js"

