"""SQLite schema, version handling, in-place migrations and connections."""

import contextlib
import os
import random
import sqlite3
import time
import uuid
from collections.abc import Callable, Generator
from pathlib import Path

from .errors import DatabaseBusyError, SchemaVersionError
from .values import extras_text, fold

#: The schema this code writes. Version 3 matches names accent-insensitively (the ``*_f`` columns hold
#: ``values.fold`` of the name); the table layout is the same as version 2. A change to the tables or indexes needs
#: a new version and a ``MIGRATIONS`` step: an up-to-date database is opened without running the DDL below.
SCHEMA_VERSION = 3

#: How long one statement waits for another process's lock (set on every connection before it runs anything).
BUSY_TIMEOUT_SECONDS = 30.0
#: How long opening a database keeps retrying after a lock error before giving up with ``DatabaseBusyError``.
OPEN_RETRY_SECONDS = 30.0
_LOCK_MESSAGES = ("database is locked", "database table is locked")

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
    """A connection that waits for other processes' locks (``BUSY_TIMEOUT_SECONDS``) from its very first statement."""
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_SECONDS * 1000)}")
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
    """The schema version a database was written with, or None for a database with no schema yet.

    Both queries are read to the end (``fetchall``), so no statement is left holding a read snapshot that a later
    write on the same connection would have to upgrade (SQLite refuses that upgrade at once, without waiting).
    """
    tables = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'").fetchall()
    if not tables:
        return None
    rows = conn.execute("SELECT MAX(version) FROM schema_version").fetchall()
    return rows[0][0] if rows else None


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


#: ``SCHEMA`` as separate statements, so they can run inside an explicit transaction (``executescript`` would
#: commit it first).
_SCHEMA_STATEMENTS = [statement.strip() for statement in SCHEMA.split(";") if statement.strip()]


def _check_openable(path: Path, found: int) -> None:
    """Raise unless a database written with version ``found`` can be opened or upgraded by this code."""
    if found == SCHEMA_VERSION:
        return
    relation = "newer" if found > SCHEMA_VERSION else "older"
    if relation == "newer" or any(step not in MIGRATIONS for step in range(found, SCHEMA_VERSION)):
        raise SchemaVersionError(
            f"{path} has schema version {found}, which is {relation} than the version {SCHEMA_VERSION} this code "
            "understands. Refusing to open it so the data is not damaged: use matching code, or export the data "
            "with the code that wrote it and import it here (python -m factstore export/import)."
        )


def _backup_before_upgrade(path: Path, found: int) -> None:
    """Copy the database to ``<name>.pre-v<found>.bak`` once, while the caller holds the write lock.

    Holding the lock means no one else can change the database, and the caller has not changed it yet, so the copy
    is the database as it was before ANY opener migrated it, and only one opener at a time can be here. The copy is
    read through a SEPARATE connection: SQLite's backup cannot copy a database while the connection that holds the
    write transaction asks (it answers 'busy' for ever), but a second reader sees the last committed state, which is
    exactly the pre-upgrade one. It is written to a temporary name and moved into place, so a half-written backup
    is never mistaken for a good one.
    """
    final = path.with_name(f"{path.name}.pre-v{found}.bak")
    if final.exists():
        return
    temporary = path.with_name(f"{final.name}.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp")
    source = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS)
    target = sqlite3.connect(temporary)
    try:
        source.backup(target)
    except BaseException:
        target.close()
        source.close()
        temporary.unlink(missing_ok=True)
        raise
    target.close()
    source.close()
    os.replace(temporary, final)


def _ensure_wal(conn: sqlite3.Connection) -> None:
    """Put the database in WAL mode. Converting a database that is not in WAL needs an exclusive lock, and SQLite
    answers 'database is locked' to that at once (the busy timeout does not apply), so only convert when needed and
    let the caller retry."""
    modes = conn.execute("PRAGMA journal_mode").fetchall()
    if not modes or str(modes[0][0]).lower() != "wal":
        conn.execute("PRAGMA journal_mode=WAL").fetchall()


def _open_once(path: Path) -> None:
    """One attempt to open the database: set WAL, then create or upgrade it under the write lock if it needs it."""
    conn = connect(path)
    conn.isolation_level = None  # explicit transactions only: nothing here holds a read snapshot by accident
    try:
        _ensure_wal(conn)
        found = _stored_version(conn)
        if found == SCHEMA_VERSION:
            return  # the usual case: nothing to write, so no write lock is taken and nobody is held up
        if found is not None:
            _check_openable(path, found)  # a newer or unknown version is refused without ever taking the lock
        conn.execute(
            "BEGIN IMMEDIATE"
        )  # the FIRST statement of the transaction: take the write lock, waiting if needed
        try:
            found = _stored_version(conn)  # re-read under the lock: another opener may have finished meanwhile
            if found is not None and found != SCHEMA_VERSION:
                _check_openable(path, found)
                _backup_before_upgrade(path, found)
                for version in range(found, SCHEMA_VERSION):
                    MIGRATIONS[version](conn)
                    conn.execute("UPDATE schema_version SET version = ?", (version + 1,))
            if found != SCHEMA_VERSION:
                for statement in _SCHEMA_STATEMENTS:
                    conn.execute(statement)
                if found is None:
                    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _is_lock_error(error: sqlite3.OperationalError) -> bool:
    return any(message in str(error).lower() for message in _LOCK_MESSAGES)


def initialise(path: Path) -> None:
    """Create the database if it is new, upgrade an older one in place, refuse one this code cannot understand.

    A database written by a newer schema is refused untouched. An older one is migrated automatically when every
    step from its version to this one is known (``MIGRATIONS``); otherwise it is refused and the data has to be
    exported with the code that wrote it and imported here.

    Several processes may open the same database at once (a deploy restarting workers, a CLI run beside the
    server). Each attempt is safe to repeat, so an attempt that hits a lock error (which SQLite can return without
    waiting, for example while another process switches the journal mode) is retried with a short random pause until
    ``OPEN_RETRY_SECONDS`` have passed; then ``DatabaseBusyError`` says the database stayed locked. Any other
    error is raised at once.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    pause = 0.005
    while True:
        try:
            _open_once(path)
            return
        except sqlite3.OperationalError as error:
            if not _is_lock_error(error):
                raise
            if time.monotonic() - started >= OPEN_RETRY_SECONDS:
                raise DatabaseBusyError(
                    f"{path} stayed locked by another process for {OPEN_RETRY_SECONDS:g} s while it was being "
                    f"opened ({error}). Nothing was changed; try again, or find the process holding it."
                ) from error
            time.sleep(random.uniform(pause / 2, pause))  # noqa: S311  # nosec B311 - retry jitter, not security
            pause = min(pause * 2, 0.25)
