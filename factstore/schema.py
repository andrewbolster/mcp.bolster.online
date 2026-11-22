"""SQLite schema, version handling and connections."""

import contextlib
import sqlite3
from collections.abc import Generator
from pathlib import Path

from .errors import SchemaVersionError

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS facts (
    id              TEXT PRIMARY KEY,
    subject         TEXT NOT NULL,
    subject_f       TEXT NOT NULL,
    subject_kind    TEXT,
    action          TEXT NOT NULL,
    action_f        TEXT NOT NULL,
    object          TEXT NOT NULL,
    object_f        TEXT NOT NULL,
    object_kind     TEXT,
    confidence      REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN -1.0 AND 1.0),
    valid_from      TEXT,
    valid_from_key  TEXT,
    valid_to        TEXT,
    valid_to_key    TEXT,
    public          INTEGER NOT NULL DEFAULT 0,
    attributes      TEXT NOT NULL DEFAULT '{}',
    refs            TEXT NOT NULL DEFAULT '[]',
    created_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_by      TEXT,
    updated_at      TEXT,
    reviewed_by     TEXT,
    reviewed_at     TEXT
);
CREATE INDEX IF NOT EXISTS facts_owner_subject ON facts (created_by, subject_f);
CREATE INDEX IF NOT EXISTS facts_owner_action ON facts (created_by, action_f);
CREATE INDEX IF NOT EXISTS facts_public_subject ON facts (public, subject_f);
CREATE INDEX IF NOT EXISTS facts_action_object ON facts (action_f, object_f);
CREATE TABLE IF NOT EXISTS reviews (
    id        TEXT PRIMARY KEY,
    fact_id   TEXT NOT NULL,
    reviewer  TEXT NOT NULL,
    outcome   TEXT NOT NULL CHECK (outcome IN ('confirmed', 'disputed', 'unsure')),
    note      TEXT,
    at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reviews_fact ON reviews (fact_id);
CREATE TABLE IF NOT EXISTS review_requests (
    id            TEXT PRIMARY KEY,
    fact_id       TEXT NOT NULL,
    requested_by  TEXT NOT NULL,
    requested_of  TEXT NOT NULL,
    note          TEXT,
    requested_at  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'declined')),
    resolved_at   TEXT
);
CREATE INDEX IF NOT EXISTS review_requests_of ON review_requests (requested_of, status);
CREATE INDEX IF NOT EXISTS review_requests_fact ON review_requests (fact_id, status);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


@contextlib.contextmanager
def session(path: Path) -> Generator[sqlite3.Connection]:
    """A connection that commits on success, rolls back on error, and always closes."""
    conn = connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialise(path: Path) -> None:
    """Create the database if it is new; refuse one written by a different schema version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        has_version = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'")
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone() if has_version.fetchone() else None
        found = row[0] if row else None
        if found is not None and found != SCHEMA_VERSION:
            relation = "newer" if found > SCHEMA_VERSION else "older"
            raise SchemaVersionError(
                f"{path} has schema version {found}, which is {relation} than the version {SCHEMA_VERSION} this code "
                "understands. Refusing to open it so the data is not damaged: use matching code, or export the data "
                "with the code that wrote it and import it here (python -m factstore export/import)."
            )
        with conn:
            conn.executescript(SCHEMA)
            if found is None:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    finally:
        conn.close()
