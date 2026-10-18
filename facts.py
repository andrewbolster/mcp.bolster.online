"""Per-user facts: a small knowledge graph of quads, kept in SQLite.

A fact is (time, subject, object, action) plus optional confidence and
references, e.g. "Szilvia's birthday is on the 18th of October" is time
``--10-18``, subject ``Szilvia Mandic``, object ``Birthday``, action ``Has``.

The tools are registered on the authenticated server only. The owner always
comes from the verified token, never from a tool argument, and every query is
filtered on it.
"""

import asyncio
import contextlib
import json
import os
import random
import re
import sqlite3
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.tools.tool import ToolAnnotations

SCHEMA_VERSION = 1
MAX_TEXT = 200
MAX_REFERENCES = 20
MAX_REFERENCE_LENGTH = 500
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

TIME_FORMATS = (
    "YYYY, YYYY-MM, YYYY-MM-DD, YYYY-MM-DDTHH:MM[:SS[.ffffff]] followed by Z or an offset like +01:00, "
    "or --MM-DD for a date that recurs every year (e.g. --10-18)"
)

_YEAR = re.compile(r"^\d{4}$")
_MONTH = re.compile(r"^\d{4}-\d{2}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RECURRING = re.compile(r"^--(\d{2})-(\d{2})$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})$")


def uuid7(now_ms: int | None = None) -> uuid.UUID:
    """A UUIDv7 (RFC 9562): 48-bit unix-millisecond timestamp, then random bits."""
    millis = (int(time.time() * 1000) if now_ms is None else now_ms) & ((1 << 48) - 1)
    rand = random.SystemRandom().getrandbits(74)
    rand_a, rand_b = rand >> 62, rand & ((1 << 62) - 1)
    value = (millis << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def _utc_key(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")


def parse_time(value: str) -> tuple[str, str | None]:
    """Validate a strict ISO 8601 time. Returns (the value, a sortable UTC key).

    The key is None for ``--MM-DD`` (no year). A coarse value such as ``2026``
    sorts at the start of its period.
    """
    text = value.strip()
    try:
        if _YEAR.match(text):
            return text, _utc_key(datetime(int(text), 1, 1, tzinfo=UTC))
        if _MONTH.match(text):
            return text, _utc_key(datetime(int(text[:4]), int(text[5:7]), 1, tzinfo=UTC))
        if _DATE.match(text):
            day = date.fromisoformat(text)
            return text, _utc_key(datetime(day.year, day.month, day.day, tzinfo=UTC))
        if _DATETIME.match(text):
            return text, _utc_key(datetime.fromisoformat(text))
        recurring = _RECURRING.match(text)
        if recurring:
            date(2000, int(recurring.group(1)), int(recurring.group(2)))  # 2000 is a leap year, so --02-29 is allowed
            return text, None
    except (ValueError, OverflowError):
        pass
    raise ToolError(f"Invalid time {value!r}. Use strict ISO 8601: {TIME_FORMATS}.")


def _text(name: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ToolError(f"{name} must not be empty.")
    if len(cleaned) > MAX_TEXT:
        raise ToolError(f"{name} must be at most {MAX_TEXT} characters.")
    return cleaned


def _confidence(value: float | None) -> float | None:
    if value is not None and not 0.0 <= value <= 1.0:
        raise ToolError("confidence must be a number between 0.0 and 1.0.")
    return value


def _references(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if len(value) > MAX_REFERENCES:
        raise ToolError(f"references can hold at most {MAX_REFERENCES} items.")
    cleaned = [item.strip() for item in value]
    if any(not item or len(item) > MAX_REFERENCE_LENGTH for item in cleaned):
        raise ToolError(f"each reference must be 1 to {MAX_REFERENCE_LENGTH} characters.")
    return cleaned


def _fold(text: str) -> str:
    return text.strip().casefold()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def data_dir() -> Path:
    return Path(os.environ.get("MCP_DATA_DIR") or Path(__file__).resolve().parent / "data")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS facts (
    id          TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    time        TEXT NOT NULL,
    time_sort   TEXT,
    subject     TEXT NOT NULL,
    object      TEXT NOT NULL,
    action      TEXT NOT NULL,
    subject_f   TEXT NOT NULL,
    object_f    TEXT NOT NULL,
    action_f    TEXT NOT NULL,
    confidence  REAL,
    refs        TEXT NOT NULL DEFAULT '[]',
    created     TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    updated     TEXT,
    updated_by  TEXT
);
CREATE INDEX IF NOT EXISTS facts_owner_time ON facts (owner, time_sort);
CREATE INDEX IF NOT EXISTS facts_owner_subject ON facts (owner, subject_f);
"""

_ready: set[Path] = set()


def _connect() -> sqlite3.Connection:
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "facts.sqlite3"
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    if path not in _ready:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
        _ready.add(path)
    return conn


@contextlib.contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    """A connection that commits on success, rolls back on error, and always closes."""
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "time": row["time"],
        "subject": row["subject"],
        "object": row["object"],
        "action": row["action"],
        "confidence": row["confidence"],
        "references": json.loads(row["refs"]),
        "created": row["created"],
        "created_by": row["created_by"],
        "updated": row["updated"],
        "updated_by": row["updated_by"],
    }


def _login() -> str:
    token = get_access_token()
    login = token.claims.get("login") if token else None
    if not login:
        raise ToolError("Not authenticated: sign in at /auth/mcp to use facts.")
    return str(login)


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _insert(owner: str, fact: dict[str, Any]) -> dict[str, Any]:
    time_text, time_sort = parse_time(fact["time"])
    subject, obj, action = (_text(n, fact[n]) for n in ("subject", "object", "action"))
    refs = _references(fact["references"]) or []
    row_id, created = str(uuid7()), _now()
    with _db() as conn:
        conn.execute(
            "INSERT INTO facts (id, owner, time, time_sort, subject, object, action, subject_f, object_f, action_f,"
            " confidence, refs, created, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row_id, owner, time_text, time_sort, subject, obj, action, _fold(subject), _fold(obj), _fold(action),
                _confidence(fact["confidence"]), json.dumps(refs), created, owner,
            ),
        )  # fmt: skip
        return _row(conn.execute("SELECT * FROM facts WHERE id = ?", (row_id,)).fetchone())


def _fetch(owner: str, fact_id: str) -> dict[str, Any]:
    with _db() as conn:
        found = conn.execute("SELECT * FROM facts WHERE id = ? AND owner = ?", (fact_id.strip(), owner)).fetchone()
    if found is None:
        raise ToolError(f"No fact with id {fact_id!r}.")
    return _row(found)


def _search(owner: str, filters: dict[str, Any]) -> dict[str, Any]:
    where: list[str] = ["owner = ?"]
    params: list[Any] = [owner]
    for name in ("subject", "object", "action"):
        if filters[name] is not None:
            where.append(f"{name}_f = ?")
            params.append(_fold(filters[name]))
    if filters["time"] is not None:
        where.append("time = ?")
        params.append(parse_time(filters["time"])[0])
    for name, op in (("time_from", ">="), ("time_to", "<=")):
        if filters[name] is not None:
            _, key = parse_time(filters[name])
            if key is None:
                raise ToolError(f"{name} needs a date with a year. Find recurring facts with time='--MM-DD' instead.")
            where.append(f"time_sort {op} ?")
            params.append(key)
    if filters["min_confidence"] is not None:
        where.append("confidence >= ?")
        params.append(_confidence(filters["min_confidence"]))
    for term in _fold(filters["q"] or "").split():  # every word must appear, in any order
        where.append("(subject_f || ' ' || object_f || ' ' || action_f) LIKE ? ESCAPE '\\'")
        params.append(_like(term))
    limit = max(1, min(int(filters["limit"]), MAX_LIMIT))
    with _db() as conn:
        rows = conn.execute(
            f"SELECT * FROM facts WHERE {' AND '.join(where)} ORDER BY created DESC, rowid DESC LIMIT ?",  # nosec B608 - fixed column names, bound values
            [*params, limit],
        ).fetchall()
    return {"count": len(rows), "facts": [_row(r) for r in rows]}


def _update(owner: str, fact_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    sets: dict[str, Any] = {}
    if changes["time"] is not None:
        sets["time"], sets["time_sort"] = parse_time(changes["time"])
    for name in ("subject", "object", "action"):
        if changes[name] is not None:
            sets[name] = _text(name, changes[name])
            sets[f"{name}_f"] = _fold(sets[name])
    if changes["confidence"] is not None:
        sets["confidence"] = _confidence(changes["confidence"])
    if changes["references"] is not None:
        sets["refs"] = json.dumps(_references(changes["references"]))
    if not sets:
        raise ToolError(
            "Nothing to update: supply at least one of time, subject, object, action, confidence, references."
        )
    sets["updated"], sets["updated_by"] = _now(), owner
    assignments = ", ".join(f"{column} = ?" for column in sets)
    with _db() as conn:
        cursor = conn.execute(
            f"UPDATE facts SET {assignments} WHERE id = ? AND owner = ?",  # nosec B608 - fixed column names, bound values
            [*sets.values(), fact_id.strip(), owner],
        )
        if cursor.rowcount == 0:
            raise ToolError(f"No fact with id {fact_id!r}.")
        return _row(conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id.strip(),)).fetchone())


def _delete(owner: str, fact_id: str) -> dict[str, Any]:
    with _db() as conn:
        cursor = conn.execute("DELETE FROM facts WHERE id = ? AND owner = ?", (fact_id.strip(), owner))
    if cursor.rowcount == 0:
        raise ToolError(f"No fact with id {fact_id!r}.")
    return {"deleted": fact_id.strip()}


def register_fact_tools(server: FastMCP) -> None:
    """Register the fact tools on ``server`` (the authenticated server only)."""

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def add_fact(
        time: Annotated[str, f"When the fact holds, strict ISO 8601: {TIME_FORMATS}"],
        subject: Annotated[str, "Who or what the fact is about, e.g. 'Szilvia Mandic'"],
        object: Annotated[str, "What the fact concerns, e.g. 'Birthday'"],  # noqa: A002
        action: Annotated[str, "How subject relates to object, e.g. 'Has'"],
        confidence: Annotated[float | None, "How sure you are, from 0.0 to 1.0"] = None,
        references: Annotated[list[str] | None, "Sources or links supporting the fact"] = None,
    ) -> dict[str, Any]:
        """Remember a fact as a (time, subject, object, action) quad. Returns the stored fact with its id.

        Example: Szilvia's birthday is on the 18th of October ->
        time='--10-18', subject='Szilvia Mandic', object='Birthday', action='Has'.
        """
        owner = _login()
        fact = {
            "time": time, "subject": subject, "object": object, "action": action,
            "confidence": confidence, "references": references,
        }  # fmt: skip
        return await asyncio.to_thread(_insert, owner, fact)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_fact(id: Annotated[str, "The fact's id, as returned by add_fact or search_facts"]) -> dict[str, Any]:  # noqa: A002
        """Read one of your facts by id. Example: id='0198f6d2-7c3e-7a41-9b0e-2f5d8a1c4e90'."""
        owner = _login()
        return await asyncio.to_thread(_fetch, owner, id)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def search_facts(
        subject: Annotated[str | None, "Match this subject (case-insensitive, exact)"] = None,
        object: Annotated[str | None, "Match this object (case-insensitive, exact)"] = None,  # noqa: A002
        action: Annotated[str | None, "Match this action (case-insensitive, exact)"] = None,
        time: Annotated[str | None, "Match this exact time value, e.g. '--10-18' for yearly facts"] = None,
        time_from: Annotated[str | None, "Only facts at or after this ISO date (needs a year)"] = None,
        time_to: Annotated[str | None, "Only facts at or before this ISO date (needs a year)"] = None,
        min_confidence: Annotated[float | None, "Only facts with at least this confidence (0.0-1.0)"] = None,
        q: Annotated[str | None, "Free text matched within subject, object and action"] = None,
        limit: Annotated[int, f"Maximum facts to return (default {DEFAULT_LIMIT}, max {MAX_LIMIT})"] = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """Search your facts, newest first. Returns {count, facts}.

        time_from and time_to compare dated facts only (a bare year counts from the start of that year);
        yearly '--MM-DD' facts are found with time='--MM-DD'.
        Example: subject='Szilvia Mandic', object='Birthday'.
        """
        owner = _login()
        filters = {
            "subject": subject, "object": object, "action": action, "time": time, "time_from": time_from,
            "time_to": time_to, "min_confidence": min_confidence, "q": q, "limit": limit,
        }  # fmt: skip
        return await asyncio.to_thread(_search, owner, filters)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True))
    async def update_fact(
        id: Annotated[str, "The id of the fact to change"],  # noqa: A002
        time: Annotated[str | None, f"New time, strict ISO 8601: {TIME_FORMATS}"] = None,
        subject: Annotated[str | None, "New subject"] = None,
        object: Annotated[str | None, "New object"] = None,  # noqa: A002
        action: Annotated[str | None, "New action"] = None,
        confidence: Annotated[float | None, "New confidence, 0.0 to 1.0"] = None,
        references: Annotated[list[str] | None, "Replacement list of references; [] clears them"] = None,
    ) -> dict[str, Any]:
        """Change fields of one of your facts. Only the fields you supply change. Returns the updated fact.

        Example: id='0198f6d2-…', confidence=0.9.
        """
        owner = _login()
        changes = {
            "time": time, "subject": subject, "object": object, "action": action,
            "confidence": confidence, "references": references,
        }  # fmt: skip
        return await asyncio.to_thread(_update, owner, id, changes)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    async def delete_fact(id: Annotated[str, "The id of the fact to delete"]) -> dict[str, Any]:  # noqa: A002
        """Permanently delete one of your facts by id. Example: id='0198f6d2-7c3e-7a41-9b0e-2f5d8a1c4e90'."""
        owner = _login()
        return await asyncio.to_thread(_delete, owner, id)
