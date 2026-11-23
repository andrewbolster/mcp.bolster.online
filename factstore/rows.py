"""Row mapping and the single visibility rule every read path goes through."""

import json
import sqlite3
from collections.abc import Iterable
from typing import Any, Literal

from .errors import NotFoundError, ValidationError
from .values import Ref

Scope = Literal["mine", "public", "all"]

#: Facts the actor has an open review request on are readable, one fact at a time, until the request is resolved.
_GRANTED = "id IN (SELECT fact_id FROM review_requests WHERE requested_of = ? AND status = 'open')"


def visible(scope: str, actor: str) -> tuple[str, list[Any]]:
    """SQL for which facts a scope may see. No scope ever includes another actor's private fact.

    ``mine``: facts the actor created. ``public``: public facts from anyone. ``all``: both, plus the single facts
    the actor has been asked to review.
    """
    if scope == "mine":
        return "created_by = ?", [actor]
    if scope == "public":
        return "public = 1", []
    if scope == "all":
        return f"(created_by = ? OR public = 1 OR {_GRANTED})", [actor, actor]
    raise ValidationError("scope must be 'mine', 'public' or 'all'.")


def match_refs(column: str, refs: Iterable[Ref]) -> tuple[str, list[Any]]:
    """SQL matching ``column`` ('subject' or 'object') against any of ``refs``.

    A ref without a kind matches any stored kind; a ref with a kind matches that kind or a stored name with no kind.
    """
    parts: list[str] = []
    params: list[Any] = []
    for ref in refs:
        if ref.kind is None:
            parts.append(f"{column}_f = ?")
            params.append(ref.f)
        else:
            parts.append(f"({column}_f = ? AND ({column}_kind IS NULL OR {column}_kind = ?))")
            params.extend([ref.f, ref.kind])
    return ("(" + " OR ".join(parts) + ")", params) if parts else ("0", [])


#: Fields of ``fact_dict`` that are computed from other fields, so a backup does not store them.
DERIVED_FIELDS = ("subject_ref", "object_ref")


def fact_dict(row: sqlite3.Row) -> dict[str, Any]:
    """A fact as returned to callers. ``subject_ref``/``object_ref`` are the names with their kind prefix, which
    can be passed straight back into a query and mean exactly the same entity."""
    return {
        "id": row["id"],
        "subject": row["subject"],
        "subject_kind": row["subject_kind"],
        "subject_ref": str(Ref(row["subject_kind"], row["subject"])),
        "action": row["action"],
        "object": row["object"],
        "object_kind": row["object_kind"],
        "object_ref": str(Ref(row["object_kind"], row["object"])),
        "confidence": row["confidence"],
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "public": bool(row["public"]),
        "attributes": json.loads(row["attributes"]),
        "references": json.loads(row["refs"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_by": row["updated_by"],
        "updated_at": row["updated_at"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
    }


def insert_fact(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    """Insert one fact from already-validated column values."""
    columns = [
        "id",
        "subject",
        "subject_f",
        "subject_kind",
        "action",
        "action_f",
        "object",
        "object_f",
        "object_kind",
        "confidence",
        "valid_from",
        "valid_from_key",
        "valid_to",
        "valid_to_key",
        "public",
        "attributes",
        "refs",
        "created_by",
        "created_at",
        "updated_by",
        "updated_at",
        "reviewed_by",
        "reviewed_at",
    ]
    conn.execute(
        f"INSERT INTO facts ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",  # nosec B608 - fixed names
        [record.get(column) for column in columns],
    )


def fetch_visible(conn: sqlite3.Connection, actor: str, fact_id: str, scope: str = "all") -> sqlite3.Row:
    """One fact the actor may see, or NotFoundError (also for a fact that exists but is private to someone else)."""
    clause, params = visible(scope, actor)
    row = conn.execute(f"SELECT * FROM facts WHERE id = ? AND {clause}", [str(fact_id).strip(), *params]).fetchone()  # nosec B608
    if row is None:
        raise NotFoundError(f"No fact with id {fact_id!r}.")
    return row
