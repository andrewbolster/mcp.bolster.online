"""Reviews: any actor can ask another actor to review a fact, and anyone who can see a fact can review it.

Reviewing is about a fact only. A review never edits somebody else's fact: a dispute by someone other than the
owner becomes the reviewer's own fact, with the opposite sign of the disputed one, that points back at it (this is
a fact store, not a reality store). An owner cannot dispute their own fact: they change it with update_fact.
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from .config import Config
from .entities import entity
from .errors import NotFoundError, PermissionDeniedError, ValidationError
from .rows import fact_dict, fetch_visible, insert_fact, match_refs
from .values import (
    Ref,
    actor_id,
    check_confidence,
    check_kind,
    check_offset,
    check_text,
    fold,
    iso,
    now_iso,
    page_info,
    page_size,
    parse_instant,
    uuid7,
)

OUTCOMES = ("confirmed", "disputed", "unsure")
OUTCOME_ROLES = ("owner", "reviewer", "all")

#: Facts an actor may read only because they were asked to review them and the request is still open.
_OPEN_GRANTS = "SELECT fact_id FROM review_requests WHERE requested_of = ? AND status = 'open'"


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


def _counter_confidence(disputed: float, stated: float | None) -> float:
    """The confidence of a reviewer's counter-fact: the opposite sign of the fact it disputes.

    Disputing a believed fact (confidence above 0) or one with no statement (0) is a falsification (-1.0);
    disputing a falsification (below 0) asserts it is true (+1.0). A reviewer can state a graded dispute instead,
    but only with the opposite sign.
    """
    wants_positive = disputed < 0
    if stated is None:
        return 1.0 if wants_positive else -1.0
    value = check_confidence(stated)
    if value == 0 or (value > 0) != wants_positive:
        raise ValidationError(
            f"The fact you are disputing has confidence {disputed:g}, so a dispute must state the opposite: "
            f"a confidence {'above 0 (up to 1.0)' if wants_positive else 'below 0 (down to -1.0)'}; got {stated:g}."
        )
    return value


def mark_reviewed(
    conn: sqlite3.Connection,
    cfg: Config,
    actor: str,
    fact_id: str,
    outcome: str,
    note: str | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Record the actor's review of a fact they can see.

    ``confirmed`` also stamps the fact's reviewed_by/reviewed_at. ``disputed`` creates the reviewer's own fact on the
    same triple, with the opposite sign of the disputed fact (-1.0 for a believed fact, +1.0 for a falsification, or
    the graded ``confidence`` the reviewer states), referencing the disputed one; the disputed fact is untouched.
    An owner cannot dispute their own fact (it is rejected: change it with update_fact). ``unsure`` only logs.
    Every outcome closes the actor's open requests on the fact.
    """
    if outcome not in OUTCOMES:
        raise ValidationError(f"outcome must be one of {', '.join(OUTCOMES)}.")
    fact = fetch_visible(conn, actor, fact_id, "all")
    if outcome == "disputed" and fact["created_by"] == actor:
        raise ValidationError(
            "You cannot dispute your own fact. To change what you believe, use update_fact: lower its confidence "
            "(a negative value records that it is false) or set valid_to if it stopped being true. "
            "'confirmed' and 'unsure' reviews of your own facts are fine."
        )
    counter_confidence: float | None = None
    if confidence is not None and outcome != "disputed":
        raise ValidationError("confidence applies to a 'disputed' outcome only.")
    if outcome == "disputed":
        counter_confidence = _counter_confidence(fact["confidence"], confidence)
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
    elif counter_confidence is not None:
        copied = ["subject", "subject_f", "subject_kind", "action", "action_f", "object", "object_f", "object_kind"]
        counter = {
            **{key: fact[key] for key in copied},
            "id": str(uuid7()),
            "confidence": counter_confidence,
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


def pending_reviews(
    conn: sqlite3.Connection,
    cfg: Config,
    actor: str,
    direction: str = "received",
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    """Open review requests: ``received`` (asked of the actor, with the fact) or ``sent`` (made by the actor).

    Oldest first, one page at a time: the reply says how many requests there are in total and whether more follow.
    """
    if direction == "received":
        column = "requested_of"
    elif direction == "sent":
        column = "requested_by"
    else:
        raise ValidationError("direction must be 'received' or 'sent'.")
    size, skip = page_size(cfg, limit), check_offset(offset)
    total = conn.execute(
        f"SELECT COUNT(*) FROM review_requests WHERE {column} = ? AND status = 'open'",  # nosec B608
        (actor,),
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM review_requests WHERE {column} = ? AND status = 'open' "  # nosec B608
        "ORDER BY requested_at, id LIMIT ? OFFSET ?",
        (actor, size, skip),
    ).fetchall()
    requests = []
    for row in rows:
        try:
            fact = fact_dict(fetch_visible(conn, actor, row["fact_id"], "all"))
        except NotFoundError:  # only possible for 'sent' on a fact the owner has since deleted
            continue
        requests.append({**_request_dict(row), "fact": fact})
    return {**page_info(limit=size, offset=skip, count=len(rows), total=total), "requests": requests}


DUE_ORDERS = ("oldest_reviewed", "lowest_confidence", "newest")


def due_for_review(
    conn: sqlite3.Connection,
    cfg: Config,
    actor: str,
    before: str | None = None,
    limit: int | None = None,
    *,
    offset: int = 0,
    action: str | None = None,
    subject: str | None = None,
    object_kind: str | None = None,
    created_before: str | None = None,
    order: str = "oldest_reviewed",
) -> dict[str, Any]:
    """The actor's own facts last reviewed (or, never reviewed, created) before ``before``.

    ``action``, ``subject`` (aliases resolved), ``object_kind`` and ``created_before`` narrow the list. ``order`` is
    ``oldest_reviewed`` (default), ``lowest_confidence`` (then oldest) or ``newest`` (by creation).
    """
    if order not in DUE_ORDERS:
        raise ValidationError(f"order must be one of {', '.join(DUE_ORDERS)}.")
    if before is None:
        cutoff = iso(datetime.now(UTC) - timedelta(days=cfg.review_interval_days))
    else:
        cutoff = iso(parse_instant(before))
    where: list[str] = ["created_by = ?", "COALESCE(reviewed_at, created_at) < ?"]
    params: list[Any] = [actor, cutoff]
    if action is not None:
        where.append("action_f = ?")
        params.append(fold(check_text("action", action, cfg)))
    if subject is not None:
        clause, cparams = match_refs("subject", entity(conn, cfg, actor, "mine", subject, "subject").names)
        where.append(clause)
        params.extend(cparams)
    if object_kind is not None:
        where.append("object_kind = ?")
        params.append(check_kind("object_kind", object_kind, cfg))
    if created_before is not None:
        where.append("created_at < ?")
        params.append(iso(parse_instant(created_before)))
    ordering = {
        "oldest_reviewed": "COALESCE(reviewed_at, created_at), rowid",
        "lowest_confidence": "confidence, COALESCE(reviewed_at, created_at), rowid",
        "newest": "created_at DESC, rowid DESC",
    }[order]
    size, skip = page_size(cfg, limit), check_offset(offset)
    clause = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM facts WHERE {clause}", params).fetchone()[0]  # nosec B608
    rows = conn.execute(
        f"SELECT * FROM facts WHERE {clause} ORDER BY {ordering} LIMIT ? OFFSET ?",  # nosec B608
        [*params, size, skip],
    ).fetchall()
    return {
        "before": cutoff,
        "order": order,
        **page_info(limit=size, offset=skip, count=len(rows), total=total),
        "facts": [fact_dict(row) for row in rows],
    }


def reviews_for(conn: sqlite3.Connection, cfg: Config, actor: str, fact: sqlite3.Row) -> list[dict[str, Any]]:
    """The review entries on a fact that ``actor`` may see, newest first.

    The fact's owner sees every entry (reviewer, outcome, note, time). Anyone else sees only their own entries, so
    one reviewer never learns what another said. A dispute's counter-fact is private to its reviewer and is
    never referenced here.
    """
    where, params = ["fact_id = ?"], [fact["id"]]
    if fact["created_by"] != actor:
        where.append("reviewer = ?")
        params.append(actor)
    rows = conn.execute(
        f"SELECT reviewer, outcome, note, at FROM reviews WHERE {' AND '.join(where)} "  # nosec B608
        "ORDER BY at DESC, id DESC LIMIT ?",
        [*params, cfg.max_reviews_shown],
    ).fetchall()
    return [dict(row) for row in rows]


def review_outcomes(
    conn: sqlite3.Connection,
    cfg: Config,
    actor: str,
    since: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    role: str = "owner",
) -> dict[str, Any]:
    """Recent review entries, newest first, optionally only those at or after ``since``.

    ``role`` chooses whose entries: ``owner`` (default) is what anyone has said about the actor's own facts,
    ``reviewer`` is the reviews the actor wrote themselves (on any fact, confirmed ones included), ``all`` is both.
    Each entry names the fact (id and, when the actor can read it, its triple), the reviewer, the outcome, the note
    and the actor's ``role`` in it. A reviewer only ever gets their own entries on someone else's fact, and sees
    the fact's wording only while they can still read it (its request is open or the fact is public). A dispute is
    reported as the outcome 'disputed': the reviewer's counter-fact itself stays private to the reviewer.
    """
    if role not in OUTCOME_ROLES:
        raise ValidationError(f"role must be one of {', '.join(OUTCOME_ROLES)}.")
    scope = {
        "owner": "f.created_by = ?",
        "reviewer": "r.reviewer = ?",
        "all": "(f.created_by = ? OR r.reviewer = ?)",
    }[role]
    where, params = [scope], [actor] * scope.count("?")
    if since is not None:
        where.append("r.at >= ?")
        params.append(iso(parse_instant(since)))
    clause = " AND ".join(where)
    size, skip = page_size(cfg, limit), check_offset(offset)
    total = conn.execute(
        f"SELECT COUNT(*) FROM reviews r JOIN facts f ON f.id = r.fact_id WHERE {clause}",  # nosec B608
        params,
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT r.id AS review_id, r.fact_id, r.reviewer, r.outcome, r.note, r.at, f.created_by, "
        "f.subject, f.subject_kind, f.action, f.object, f.object_kind, "
        f"(f.created_by = ? OR f.public = 1 OR f.id IN ({_OPEN_GRANTS})) AS readable "
        f"FROM reviews r JOIN facts f ON f.id = r.fact_id WHERE {clause} "  # nosec B608
        "ORDER BY r.at DESC, r.id DESC LIMIT ? OFFSET ?",
        [actor, actor, *params, size, skip],
    ).fetchall()
    outcomes = []
    for row in rows:
        mine = row["created_by"] == actor
        entry: dict[str, Any] = {
            "review_id": row["review_id"],
            "fact_id": row["fact_id"],
            "role": "owner" if mine else "reviewer",
            "reviewer": row["reviewer"],
            "outcome": row["outcome"],
            "note": row["note"],
            "at": row["at"],
        }
        if row["readable"]:  # a reviewer whose access has ended gets the id, their verdict and nothing else
            entry |= {
                "subject_ref": str(Ref(row["subject_kind"], row["subject"])),
                "action": row["action"],
                "object_ref": str(Ref(row["object_kind"], row["object"])),
            }
        outcomes.append(entry)
    return {**page_info(limit=size, offset=skip, count=len(outcomes), total=total), "outcomes": outcomes}


def require_owner(row: sqlite3.Row, actor: str) -> None:
    if row["created_by"] != actor:
        raise PermissionDeniedError("Only the creator of a fact can change or delete it.")
