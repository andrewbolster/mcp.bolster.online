"""JSON Lines export and import: the backup format and the migration path between schema versions.

Line 1 is a header naming the schema version. Every other line is a ``fact``, ``review`` or ``review_request``
record carrying all of its fields. Import keeps ids and created_at, skips ids that already exist (so it is
idempotent), and is all-or-nothing.
"""

import json
import sqlite3
from datetime import datetime
from typing import IO, Any

from .config import Config
from .errors import SchemaVersionError, ValidationError
from .rows import DERIVED_FIELDS, fact_dict, insert_fact
from .schema import SCHEMA_VERSION
from .values import (
    actor_id,
    check_attributes,
    check_confidence,
    check_kind,
    check_references,
    check_text,
    fold,
    iso,
    parse_when,
)

FORMAT = "factstore-jsonl"


def export_jsonl(conn: sqlite3.Connection, out: IO[str], actor: str | None) -> int:
    """Write a header, then the facts (of one actor, or all) with the reviews and requests that point at them."""
    out.write(json.dumps({"type": "header", "format": FORMAT, "schema_version": SCHEMA_VERSION}) + "\n")
    if actor is None:
        facts = conn.execute("SELECT * FROM facts ORDER BY created_at, rowid").fetchall()
    else:
        facts = conn.execute("SELECT * FROM facts WHERE created_by = ? ORDER BY created_at, rowid", (actor,)).fetchall()
    for row in facts:
        stored = {key: value for key, value in fact_dict(row).items() if key not in DERIVED_FIELDS}
        out.write(json.dumps({"type": "fact", **stored}, ensure_ascii=False) + "\n")
    ids = [row["id"] for row in facts]
    for table, kind in (("reviews", "review"), ("review_requests", "review_request")):
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            marks = ",".join("?" * len(chunk))
            for row in conn.execute(f"SELECT * FROM {table} WHERE fact_id IN ({marks}) ORDER BY id", chunk):  # nosec B608
                out.write(json.dumps({"type": kind, **dict(row)}, ensure_ascii=False) + "\n")
    return len(facts)


def _stamp(value: Any, label: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValidationError(f"{label} is required.")
        return None
    try:
        return iso(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        raise ValidationError(f"{label} {value!r} is not an ISO 8601 timestamp.") from None


def _fact_record(data: dict[str, Any], cfg: Config) -> dict[str, Any]:
    from_text, from_key = parse_when(data["valid_from"]) if data.get("valid_from") else (None, None)
    to_text, to_key = parse_when(data["valid_to"], end=True) if data.get("valid_to") else (None, None)
    if from_key is not None and to_key is not None and to_key < from_key:
        raise ValidationError("valid_to must not be before valid_from.")
    fact_id = data.get("id")
    if not isinstance(fact_id, str) or not fact_id.strip():
        raise ValidationError("a fact needs an id.")
    subject, action, obj = (check_text(name, data.get(name), cfg) for name in ("subject", "action", "object"))
    return {
        "id": fact_id.strip(),
        "subject": subject, "subject_f": fold(subject), "subject_kind": check_kind("subject_kind", data.get("subject_kind"), cfg),
        "action": action, "action_f": fold(action),
        "object": obj, "object_f": fold(obj), "object_kind": check_kind("object_kind", data.get("object_kind"), cfg),
        "confidence": check_confidence(data.get("confidence", 1.0)),
        "valid_from": from_text, "valid_from_key": from_key, "valid_to": to_text, "valid_to_key": to_key,
        "public": int(bool(data.get("public"))),
        "attributes": json.dumps(check_attributes(data.get("attributes"), cfg)),
        "refs": json.dumps(check_references(data.get("references"), cfg)),
        "created_by": actor_id(str(data.get("created_by") or "")),
        "created_at": _stamp(data.get("created_at"), "created_at", required=True),
        "updated_by": actor_id(data["updated_by"]) if data.get("updated_by") else None,
        "updated_at": _stamp(data.get("updated_at"), "updated_at"),
        "reviewed_by": actor_id(data["reviewed_by"]) if data.get("reviewed_by") else None,
        "reviewed_at": _stamp(data.get("reviewed_at"), "reviewed_at"),
    }  # fmt: skip


def import_jsonl(conn: sqlite3.Connection, cfg: Config, source: IO[str]) -> dict[str, int]:
    """Load records written by ``export_jsonl``. Raises (and imports nothing) on the first bad line."""
    counts = {"facts": 0, "reviews": 0, "review_requests": 0, "skipped": 0}
    saw_header = False
    for number, line in enumerate(source, start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValidationError("each line must be a JSON object.")
            kind = data.get("type")
            if kind == "header":
                if data.get("format") != FORMAT:
                    raise ValidationError(f"not a {FORMAT} file.")
                version = data.get("schema_version")
                if not isinstance(version, int) or version > SCHEMA_VERSION:
                    raise SchemaVersionError(
                        f"file was written with schema version {version}; this code understands up to {SCHEMA_VERSION}."
                    )
                saw_header = True
            elif not saw_header:
                raise ValidationError("the first line must be the header.")
            elif kind == "fact":
                if conn.execute("SELECT 1 FROM facts WHERE id = ?", (data.get("id"),)).fetchone():
                    counts["skipped"] += 1
                else:
                    insert_fact(conn, _fact_record(data, cfg))
                    counts["facts"] += 1
            elif kind in ("review", "review_request"):
                table = "reviews" if kind == "review" else "review_requests"
                if conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (data.get("id"),)).fetchone():  # nosec B608
                    counts["skipped"] += 1
                else:
                    columns = [c for c in data if c != "type"]
                    conn.execute(
                        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",  # nosec B608
                        [data[c] for c in columns],
                    )
                    counts[table] += 1
            else:
                raise ValidationError(f"unknown record type {kind!r}.")
        except (json.JSONDecodeError, ValidationError, sqlite3.Error, KeyError) as error:
            raise ValidationError(f"line {number}: {error}") from error
    if not saw_header:
        raise ValidationError("empty file: expected a header line.")
    return counts
