"""Encryption at rest for secrets zing stores locally (the watch API keys).

A stored secret is sealed as ``enc:v1:<Fernet token>``: AES-128-CBC with an
HMAC-SHA256 tag, from ``cryptography`` (part of the ``web`` extra, the only
place secrets are stored). Values that are only pointers to a secret
(``env:VAR`` / ``file:/path``, see :func:`zing.config.resolve_secret`) and the
empty string are stored as is.

The master key comes from, in order:

1. ``ZING_SECRET_KEY`` — itself resolved with :func:`~zing.config.resolve_secret`,
   so a literal key, ``env:OTHER`` or ``file:/run/secrets/zing_key`` all work.
   A comma-separated list rotates: the first key seals, every key opens.
2. ``<data dir>/secret.key`` — generated owner-only (``0600``) on first use.
   It may hold a comma-separated list too, briefly, while a rotation runs.

Threat model: with the default key file next to the databases, a copy of a
database on its own (a backup, a synced folder, a support bundle) no longer
exposes the keys; someone who can read the whole data directory still can.
Keep the key outside it (``ZING_SECRET_KEY``) for real separation.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import os
from pathlib import Path
from typing import Any

from zing import datadir

PREFIX = "enc:v1:"
_REFERENCES = ("env:", "file:")
_KEY_FILE = "secret.key"
ENV = "ZING_SECRET_KEY"


class SecretError(Exception):
    """A secret could not be sealed or opened (missing extra, bad or wrong key)."""


def _fernet() -> Any:
    try:
        from cryptography import fernet
    except ImportError as exc:  # pragma: no cover - the web extra ships it
        raise SecretError(
            "encrypting stored keys needs the 'cryptography' package: "
            "pip install 'zing-audit[web]'"
        ) from exc
    return fernet


def generate_key() -> str:
    return str(_fernet().Fernet.generate_key().decode("ascii"))


def is_sealed(stored: str | None) -> bool:
    return bool(stored) and str(stored).startswith(PREFIX)


def is_reference(stored: str | None) -> bool:
    return bool(stored) and str(stored).startswith(_REFERENCES)


def needs_seal(stored: str | None) -> bool:
    """True for a raw secret still stored in plain text."""
    return bool(stored) and not is_sealed(stored) and not is_reference(stored)


class SecretBox:
    """Seal and open secrets with a list of keys (first seals, all open)."""

    def __init__(self, keys: list[str], source: str = "") -> None:
        if not keys:
            raise SecretError("no secret key given")
        fernet = _fernet()
        try:
            self._multi = fernet.MultiFernet([fernet.Fernet(k.encode("ascii")) for k in keys])
        except (ValueError, TypeError, UnicodeEncodeError) as exc:
            raise SecretError(f"invalid secret key from {source or 'input'}: {exc}") from exc
        self._invalid = fernet.InvalidToken
        self.keys = list(keys)
        self.source = source

    def fingerprint(self) -> str:
        """First 8 hex chars of SHA-256 of the sealing key — safe to show."""
        return hashlib.sha256(self.keys[0].encode("ascii")).hexdigest()[:8]

    def seal(self, plain: str | None) -> str:
        if not plain:
            return ""
        if not needs_seal(plain):
            return str(plain)
        return PREFIX + self._multi.encrypt(str(plain).encode("utf-8")).decode("ascii")

    def open(self, stored: str | None) -> str:
        if not stored:
            return ""
        if not is_sealed(stored):
            return str(stored)
        try:
            return str(self._multi.decrypt(str(stored)[len(PREFIX):].encode("ascii")).decode("utf-8"))
        except (self._invalid, UnicodeError) as exc:
            raise SecretError(
                f"stored key cannot be decrypted with the key from {self.source} "
                f"(fingerprint {self.fingerprint()}): wrong or rotated-away master key"
            ) from exc

    def can_open(self, stored: str | None) -> bool:
        try:
            self.open(stored)
        except SecretError:
            return False
        return True

    def reseal(self, stored: str | None) -> str:
        """Re-encrypt a sealed value with the first key; seal a plain one."""
        if is_sealed(stored):
            return self.seal(self.open(stored))
        return self.seal(stored)


def key_file() -> Path:
    return datadir.db_path(_KEY_FILE)


def _split(value: str) -> list[str]:
    return [k.strip() for k in value.split(",") if k.strip()]


def _read_key_file(path: Path) -> list[str]:
    try:
        keys = _split(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError) as exc:
        raise SecretError(f"cannot read secret key file {path}: {exc}") from exc
    if not keys:
        raise SecretError(f"secret key file {path} is empty; restore it from your backup")
    return keys


def _create_key_file(path: Path) -> bool:
    """Write a fresh key unless one exists. True when this call created it.

    ``O_EXCL`` makes two processes racing here agree on one key; an existing
    file is never overwritten, since that would orphan every sealed secret.
    """
    datadir.ensure_data_dir()
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(generate_key() + "\n")
    return True


def write_key_file(key: str, path: Path | None = None) -> Path:
    """Atomically replace the key file (rotation); ``key`` may be a comma list."""
    path = path or key_file()
    datadir.ensure_data_dir()
    tmp = path.with_name(path.name + ".tmp")
    with contextlib.suppress(FileNotFoundError):
        tmp.unlink()
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(key + "\n")
    os.replace(tmp, path)
    return path


def load_keys() -> tuple[list[str], str, bool]:
    """``(keys, source, created)`` per the order in the module docstring."""
    from zing.config import resolve_secret

    raw = os.environ.get(ENV, "").strip()
    if raw:
        try:
            value = resolve_secret(raw)
        except Exception as exc:
            raise SecretError(f"{ENV}: {exc}") from exc
        keys = _split(value)
        if not keys:
            raise SecretError(f"{ENV} is set but resolves to no key")
        return keys, ENV, False
    path = key_file()
    created = _create_key_file(path)
    return _read_key_file(path), str(path), created


@functools.lru_cache(maxsize=8)
def _cached(env_value: str, data_dir: str) -> tuple[SecretBox, bool]:
    keys, source, created = load_keys()
    return SecretBox(keys, source), created


def default() -> SecretBox:
    """The process-wide box, cached per (``ZING_SECRET_KEY``, data dir)."""
    return _cached(os.environ.get(ENV, ""), str(datadir.data_dir()))[0]


def default_created() -> bool:
    """True when :func:`default` generated a brand-new key file."""
    return _cached(os.environ.get(ENV, ""), str(datadir.data_dir()))[1]


def clear_cache() -> None:
    _cached.cache_clear()
