"""Shared fixtures. Fact stores always live in a pytest temp directory, never under the repo's ``data/``."""

import pytest

from factstore import FactStore


@pytest.fixture
def store(tmp_path) -> FactStore:
    return FactStore(tmp_path / "facts.sqlite3")
