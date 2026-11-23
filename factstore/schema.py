"""SQLite schema, version handling, in-place migrations and connections."""

import contextlib
import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path

from .errors import SchemaVersionError
from .values import extras_text, fold

#: The schema this code writes. Version 3 matches names accent-insensitively (the ``*_f`` columns hold
#: ``values.fold`` of the name); the table layout is the same as version 2.
SCHEMA_VERSION = 3

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
    # free-text search also covers attributes and references, folded the same way names are
    conn.create_function("fact_extras", 2, extras_text, deterministic=True)
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


def _stored_version(conn: sqlite3.Connection) -> int | None:
    """The schema version a database was written with, or None for a database with no schema yet."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'").fetchone() is None:
        return None
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] if row else None


def _refold_names(conn: sqlite3.Connection) -> None:
    """Version 2 -> 3: recompute the folded name columns with the accent-insensitive ``fold``."""
    rows = conn.execute("SELECT id, subject, action, object, subject_f, action_f, object_f FROM facts").fetchall()
    changed = []
    for row in rows:
        folded = (fold(row["subject"]), fold(row["action"]), fold(row["object"]))
        if folded != (row["subject_f"], row["action_f"], row["object_f"]):
            changed.append((*folded, row["id"]))
    conn.executemany("UPDATE facts SET subject_f = ?, action_f = ?, object_f = ? WHERE id = ?", changed)


#: Upgrade steps, keyed by the version each one upgrades FROM (to that version + 1). Each runs inside the one
#: transaction that also bumps ``schema_version``, so a failure leaves the database as it was.
MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {2: _refold_names}


def _migrate(conn: sqlite3.Connection, path: Path, found: int) -> None:
    """Bring a database from ``found`` up to SCHEMA_VERSION in ONE transaction, after taking a backup copy."""
    backup = path.with_name(f"{path.name}.pre-v{found}.bak")
    if not backup.exists():
        target = sqlite3.connect(backup)
        try:
            conn.backup(target)
        finally:
            target.close()
    conn.isolation_level = None  # explicit transaction control
    conn.execute("BEGIN IMMEDIATE")
    try:
        # another process may have migrated while this one waited for the write lock
        current = _stored_version(conn) or found
        while current < SCHEMA_VERSION:
            MIGRATIONS[current](conn)
            current += 1
            conn.execute("UPDATE schema_version SET version = ?", (current,))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.isolation_level = "DEFERRED"  # the default behaviour, restored for the statements that follow


def initialise(path: Path) -> None:
    """Create the database if it is new, upgrade an older one in place, refuse one this code cannot understand.

    A database written by a newer schema is refused untouched. An older one is migrated automatically when every
    step from its version to this one is known (``MIGRATIONS``); otherwise it is refused and the data has to be
    exported with the code that wrote it and imported here.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        found = _stored_version(conn)
        if found is not None and found != SCHEMA_VERSION:
            relation = "newer" if found > SCHEMA_VERSION else "older"
            if relation == "newer" or any(step not in MIGRATIONS for step in range(found, SCHEMA_VERSION)):
                raise SchemaVersionError(
                    f"{path} has schema version {found}, which is {relation} than the version {SCHEMA_VERSION} this "
                    "code understands. Refusing to open it so the data is not damaged: use matching code, or export "
                    "the data with the code that wrote it and import it here (python -m factstore export/import)."
                )
            _migrate(conn, path, found)
        with conn:
            conn.executescript(SCHEMA)
            if found is None:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    finally:
        conn.close()
