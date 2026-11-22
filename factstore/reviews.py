"""Reviews: any actor can ask another actor to review a fact, and anyone who can see a fact can review it.

Reviewing is about a fact only. A review never edits somebody else's fact: a dispute by someone other than the
owner becomes the reviewer's own fact with confidence -1 that points back at the disputed one (this is a fact
store, not a reality store).
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from .config import Config
from .errors import NotFoundError, PermissionDeniedError, ValidationError
from .rows import fact_dict, fetch_visible, insert_fact
from .values import actor_id, iso, now_iso, parse_instant, uuid7

OUTCOMES = ("confirmed", "disputed", "unsure")


def _note(note: str | None, cfg: Config) -> str | None:
    if note is None:
        return None
    cleaned = note.strip()
    if len(cleaned) > cfg.max_reference_length:
        raise ValidationError(f"note must be at most {cfg.max_reference_length} characters.")
    return cleaned or None


def _request_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def request_review(
    conn: sqlite3.Connection, cfg: Config, actor: str, fact_id: str, of_actor: str, note: str | None = None
) -> dict[str, Any]:
    """Ask ``of_actor`` to review one of the actor's own facts.

    While the request is open it lets ``of_actor`` read that one fact and nothing else. Asking again for the same
    fact and reviewer returns the request that is already open.
    """
    reviewer = actor_id(of_actor)
    if reviewer == actor:
        raise ValidationError("You cannot ask yourself to review a fact; use mark_reviewed.")
    fact = fetch_visible(conn, actor, fact_id, "mine")
    existing = conn.execute(
        "SELECT * FROM review_requests WHERE fact_id = ? AND requested_of = ? AND status = 'open'",
        (fact["id"], reviewer),
    ).fetchone()
    if existing is not None:
        return {**_request_dict(existing), "already_open": True}
    request_id, now = str(uuid7()), now_iso()
    conn.execute(
        "INSERT INTO review_requests (id, fact_id, requested_by, requested_of, note, requested_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'open')",
        (request_id, fact["id"], actor, reviewer, _note(note, cfg), now),
    )
    created = conn.execute("SELECT * FROM review_requests WHERE id = ?", (request_id,)).fetchone()
    return {**_request_dict(created), "already_open": False}


def mark_reviewed(
    conn: sqlite3.Connection, cfg: Config, actor: str, fact_id: str, outcome: str, note: str | None = None
) -> dict[str, Any]:
    """Record the actor's review of a fact they can see.

    ``confirmed`` also stamps the fact's reviewed_by/reviewed_at. ``disputed`` by someone other than the owner
    creates the reviewer's own confidence -1 fact referencing the disputed one; the owner's fact is untouched.
    ``unsure`` only logs. Every outcome closes the actor's open requests on the fact.
    """
    if outcome not in OUTCOMES:
        raise ValidationError(f"outcome must be one of {', '.join(OUTCOMES)}.")
    fact = fetch_visible(conn, actor, fact_id, "all")
    review_id, now = str(uuid7()), now_iso()
    clean_note = _note(note, cfg)
    conn.execute(
        "INSERT INTO reviews (id, fact_id, reviewer, outcome, note, at) VALUES (?, ?, ?, ?, ?, ?)",
        (review_id, fact["id"], actor, outcome, clean_note, now),
    )
    conn.execute(
        "UPDATE review_requests SET status = 'done', resolved_at = ? "
        "WHERE fact_id = ? AND requested_of = ? AND status = 'open'",
        (now, fact["id"], actor),
    )
    counter_fact: dict[str, Any] | None = None
    if outcome == "confirmed":
        conn.execute("UPDATE facts SET reviewed_by = ?, reviewed_at = ? WHERE id = ?", (actor, now, fact["id"]))
    elif outcome == "disputed" and fact["created_by"] != actor:
        copied = ["subject", "subject_f", "subject_kind", "action", "action_f", "object", "object_f", "object_kind"]
        counter = {
            **{key: fact[key] for key in copied},
            "id": str(uuid7()),
            "confidence": -1.0,
            "public": 0,
            "attributes": json.dumps({"disputes": fact["id"]}),
            "refs": json.dumps([f"fact:{fact['id']}"]),
            "created_by": actor,
            "created_at": now,
        }
        insert_fact(conn, counter)
        counter_fact = fact_dict(conn.execute("SELECT * FROM facts WHERE id = ?", (counter["id"],)).fetchone())
    review = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    return {
        "review": _request_dict(review),
        "fact": fact_dict(conn.execute("SELECT * FROM facts WHERE id = ?", (fact["id"],)).fetchone()),
        "counter_fact": counter_fact,
    }


def pending_reviews(conn: sqlite3.Connection, cfg: Config, actor: str, direction: str = "received") -> dict[str, Any]:
    """Open review requests: ``received`` (asked of the actor, with the fact) or ``sent`` (made by the actor)."""
    if direction == "received":
        rows = conn.execute(
            "SELECT * FROM review_requests WHERE requested_of = ? AND status = 'open' ORDER BY requested_at, id",
            (actor,),
        ).fetchall()
    elif direction == "sent":
        rows = conn.execute(
            "SELECT * FROM review_requests WHERE requested_by = ? AND status = 'open' ORDER BY requested_at, id",
            (actor,),
        ).fetchall()
    else:
        raise ValidationError("direction must be 'received' or 'sent'.")
    requests = []
    for row in rows:
        try:
            fact = fact_dict(fetch_visible(conn, actor, row["fact_id"], "all"))
        except NotFoundError:  # only possible for 'sent' on a fact the owner has since deleted
            continue
        requests.append({**_request_dict(row), "fact": fact})
    return {"count": len(requests), "requests": requests}


def due_for_review(
    conn: sqlite3.Connection, cfg: Config, actor: str, before: str | None = None, limit: int | None = None
) -> dict[str, Any]:
    """The actor's own facts last reviewed (or, never reviewed, created) before ``before``, oldest first."""
    if before is None:
        cutoff = iso(datetime.now(UTC) - timedelta(days=cfg.review_interval_days))
    else:
        cutoff = iso(parse_instant(before))
    size = max(1, min(int(limit or cfg.default_limit), cfg.max_limit))
    rows = conn.execute(
        "SELECT * FROM facts WHERE created_by = ? AND COALESCE(reviewed_at, created_at) < ? "
        "ORDER BY COALESCE(reviewed_at, created_at), rowid LIMIT ?",
        (actor, cutoff, size),
    ).fetchall()
    return {"before": cutoff, "count": len(rows), "facts": [fact_dict(row) for row in rows]}


def require_owner(row: sqlite3.Row, actor: str) -> None:
    if row["created_by"] != actor:
        raise PermissionDeniedError("Only the creator of a fact can change or delete it.")
