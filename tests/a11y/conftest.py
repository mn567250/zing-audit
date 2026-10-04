"""Fixtures for the accessibility suite; the machinery lives in harness.py."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="a11y tests need playwright (pip install -e '.[a11y]')")

from tests.a11y.harness import _fresh_results, base_url, browser, open_page  # noqa: E402,F401

_HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if _HERE in Path(str(item.fspath)).resolve().parents:
            item.add_marker(pytest.mark.a11y)
