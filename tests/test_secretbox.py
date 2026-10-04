"""Encryption at rest for the monitors' stored API keys (zing/secretbox.py).

Covers the box itself, master-key resolution, the watch store's encryption,
legacy plain-text migration, an unreadable key in the scheduler and the
`zing secret` commands.
"""

from __future__ import annotations

import sqlite3
import stat
import time

import pytest

pytest.importorskip("cryptography")

from typer.testing import CliRunner  # noqa: E402

from zing import secretbox  # noqa: E402
from zing.cli import app  # noqa: E402

SECRET = "sk-super-secret-123"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ZING_SECRET_KEY", raising=False)
    secretbox.clear_cache()
    yield
    secretbox.clear_cache()


def _box(*keys: str) -> secretbox.SecretBox:
    return secretbox.SecretBox(list(keys) or [secretbox.generate_key()], "test")


def _raw_keys(path) -> list[str]:
    with sqlite3.connect(path) as conn:
        return [r[0] for r in conn.execute("SELECT api_key FROM watches ORDER BY id")]


def _watch(**kw):
    from zing.web import watches

    cfg = {"name": "w", "base_url": "https://relay.test/v1", "model": "gpt-4o",
           "api_key": SECRET, "interval_sec": 3600, **kw}
    return watches.create(cfg)


# --------------------------------------------------------------------------- #
# The box
# --------------------------------------------------------------------------- #
def test_seal_open_roundtrip():
    box = _box()
    sealed = box.seal(SECRET)
    assert sealed.startswith("enc:v1:") and SECRET not in sealed
    assert box.open(sealed) == SECRET
    assert box.seal(sealed) == sealed  # never double-sealed


@pytest.mark.parametrize("value", ["", None, "env:OPENAI_API_KEY", "file:/run/secrets/k"])
def test_references_and_empty_pass_through(value):
    box = _box()
    assert box.seal(value) == (value or "")
    assert box.open(value) == (value or "")


def test_wrong_key_and_tampering_raise():
    sealed = _box().seal(SECRET)
    with pytest.raises(secretbox.SecretError):
        _box().open(sealed)
    box = _box()
    good = box.seal(SECRET)
    with pytest.raises(secretbox.SecretError):
        box.open(good[:-4] + ("AAAA" if not good.endswith("AAAA") else "BBBB"))


def test_invalid_key_is_a_secret_error():
    with pytest.raises(secretbox.SecretError):
        secretbox.SecretBox(["not-a-fernet-key"], "test")


def test_older_keys_still_open_and_reseal_moves_to_first():
    old, new = secretbox.generate_key(), secretbox.generate_key()
    sealed_old = _box(old).seal(SECRET)
    both = _box(new, old)
    assert both.open(sealed_old) == SECRET
    assert _box(new).open(both.reseal(sealed_old)) == SECRET


# --------------------------------------------------------------------------- #
# Master key resolution
# --------------------------------------------------------------------------- #
def test_key_file_created_owner_only_and_reused(tmp_path):
    box = secretbox.default()
    path = tmp_path / "secret.key"
    assert box.source == str(path) and secretbox.default_created()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    secretbox.clear_cache()
    assert secretbox.default().keys == box.keys
    assert not secretbox.default_created()


def test_concurrent_creation_agrees_on_one_key(tmp_path):
    path = tmp_path / "secret.key"
    assert secretbox._create_key_file(path) is True
    first = path.read_text()
    assert secretbox._create_key_file(path) is False  # the loser reads the winner's
    assert path.read_text() == first


def test_corrupt_key_file_raises_and_is_never_overwritten(tmp_path):
    path = tmp_path / "secret.key"
    path.write_text("garbage")
    with pytest.raises(secretbox.SecretError):
        secretbox.default()
    assert path.read_text() == "garbage"
    path.write_text("")
    with pytest.raises(secretbox.SecretError):
        secretbox.default()


def test_env_key_literal_and_file_reference(tmp_path, monkeypatch):
    key = secretbox.generate_key()
    monkeypatch.setenv("ZING_SECRET_KEY", key)
    assert secretbox.default().keys == [key] and secretbox.default().source == "ZING_SECRET_KEY"
    assert not (tmp_path / "secret.key").exists()

    other = tmp_path / "elsewhere"
    other.write_text(key + "\n")
    monkeypatch.setenv("ZING_SECRET_KEY", f"file:{other}")
    assert secretbox.default().keys == [key]


# --------------------------------------------------------------------------- #
# Watch store
# --------------------------------------------------------------------------- #
def test_store_encrypts_on_disk_and_decrypts_for_the_scheduler():
    from zing.web import watches

    wid = _watch()
    [raw] = _raw_keys(watches._db_path())
    assert raw.startswith("enc:v1:")
    assert SECRET.encode() not in watches._db_path().read_bytes()
    assert watches.get(wid)["api_key"] == SECRET
    assert watches.due(time.time())[0]["api_key"] == SECRET
    [row] = watches.list_all()
    assert "api_key" not in row and row["has_key"] and row["key_status"] == "encrypted"

    watches.update(wid, api_key="sk-new")
    assert _raw_keys(watches._db_path())[0].startswith("enc:v1:")
    assert watches.get(wid)["api_key"] == "sk-new"


def test_references_are_stored_as_is():
    from zing.web import watches

    wid = _watch(api_key="env:RELAY_KEY")
    assert _raw_keys(watches._db_path()) == ["env:RELAY_KEY"]
    assert watches.get(wid)["api_key"] == "env:RELAY_KEY"
    assert watches.list_all()[0]["key_status"] == "reference"


def test_due_only_returns_due_rows():
    from zing.web import watches

    wid = _watch()
    watches.mark_run(wid, None, None, None, time.time())
    assert watches.due(time.time()) == []
    assert [d["id"] for d in watches.due(time.time() + 3600)] == [wid]


def test_init_migrates_legacy_plain_text_and_scrubs_it():
    from zing.web import watches

    watches.init()
    path = watches._db_path()
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO watches (name, base_url, api_key, model, webhooks, interval_sec)"
            " VALUES ('old', 'https://x/v1', ?, 'm', '[]', 3600)", (SECRET,)
        )
        conn.execute(
            "INSERT INTO watches (name, base_url, api_key, model, webhooks, interval_sec)"
            " VALUES ('ref', 'https://x/v1', 'env:K', 'm', '[]', 3600)"
        )
    assert watches.list_all()[-1]["key_status"] == "plain"
    assert watches.init() == 1
    assert watches.init() == 0  # idempotent
    raw = _raw_keys(path)
    assert raw[0].startswith("enc:v1:") and raw[1] == "env:K"
    for p in (path, path.with_name(path.name + "-wal")):
        if p.exists():
            assert SECRET.encode() not in p.read_bytes()
    assert watches.get(1)["api_key"] == SECRET


def test_lost_master_key_is_reported_not_guessed(tmp_path):
    from zing.web import watches

    wid = _watch()
    (tmp_path / "secret.key").write_text(secretbox.generate_key())  # key "lost"
    secretbox.clear_cache()
    row = watches.get(wid)
    assert row["api_key"] is None and row["key_error"]
    assert watches.list_all()[0]["key_status"] == "unreadable"
    assert watches.key_counts()["unreadable"] == 1
    # Re-entering the key heals it.
    watches.update(wid, api_key=SECRET)
    assert watches.get(wid)["api_key"] == SECRET and watches.get(wid)["key_error"] is None


async def test_scheduler_skips_a_watch_whose_key_is_unreadable(tmp_path, monkeypatch):
    from zing.web import server, watches

    wid = _watch()
    watches.mark_run(wid, "low", 90.0, None, 1.0)
    (tmp_path / "secret.key").write_text(secretbox.generate_key())
    secretbox.clear_cache()

    async def boom(*_a, **_k):  # the audit must never start
        raise AssertionError("audited without a key")

    monkeypatch.setattr(server, "run_audit", boom)
    with pytest.raises(server.WatchKeyUnreadable):
        await server._run_one_watch(watches.get(wid))
    row = watches.get(wid)
    assert row["last_run_ts"] > 1.0 and row["last_risk"] == "low"  # result kept


# --------------------------------------------------------------------------- #
# zing secret
# --------------------------------------------------------------------------- #
def test_cli_status_and_export(tmp_path):
    _watch()
    res = CliRunner().invoke(app, ["secret", "status"])
    assert res.exit_code == 0, res.output
    assert str(tmp_path / "secret.key") in res.output and "1 encrypted" in res.output
    res = CliRunner().invoke(app, ["secret", "export"])
    assert res.exit_code == 0
    assert (tmp_path / "secret.key").read_text().strip() in res.output


def test_cli_rotate_key_file(tmp_path):
    from zing.web import watches

    wid = _watch()
    before = (tmp_path / "secret.key").read_text()
    res = CliRunner().invoke(app, ["secret", "rotate"])
    assert res.exit_code == 0, res.output
    after = (tmp_path / "secret.key").read_text()
    assert after != before and "," not in after
    assert stat.S_IMODE((tmp_path / "secret.key").stat().st_mode) == 0o600
    secretbox.clear_cache()
    assert watches.get(wid)["api_key"] == SECRET
    with pytest.raises(secretbox.SecretError):
        _box(before.strip()).open(_raw_keys(watches._db_path())[0])


def test_cli_rotate_env_key_in_two_steps(monkeypatch):
    from zing.web import watches

    old = secretbox.generate_key()
    monkeypatch.setenv("ZING_SECRET_KEY", old)
    wid = _watch()
    res = CliRunner().invoke(app, ["secret", "rotate"])
    assert res.exit_code == 0
    pair = res.stdout.strip().splitlines()[-1]
    new = pair.split(",")[0]
    assert pair == f"{new},{old}"
    monkeypatch.setenv("ZING_SECRET_KEY", pair)
    res = CliRunner().invoke(app, ["secret", "rotate"])
    assert res.exit_code == 0, res.output
    monkeypatch.setenv("ZING_SECRET_KEY", new)
    assert watches.get(wid)["api_key"] == SECRET
