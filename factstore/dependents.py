"""dependents: the entities connected to an entity by chains of facts, nearest first.

``direction='in'`` follows facts that point AT an entity (a claim "Derived from" a dataset depends on it),
``'out'`` follows facts that start from it, ``'both'`` follows either way. The walk is breadth first, so each entity
is reported once, by its shortest path. Every hop is a fact the actor may read (the same visibility rule as every
other read path), so a path never passes through anything the actor cannot see.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .entities import entity
from .errors import ValidationError
from .rows import match_refs, visible
from .shape import check_fields, check_format, shape_rows
from .values import Ref, check_kind, check_offset, check_text, fold, page_info, page_size

MAX_DEPTH = 3
DIRECTIONS = ("in", "out", "both")

#: Fields of a dependent. ``via`` is the actions along the path, ``fact_ids`` the facts it passes through (the last one
#: reached the entity), and ``confidence``, ``valid_from`` and ``valid_to``, ``attributes`` and ``references`` are those
#: of that last fact.
DEPENDENT_FIELDS = (
    "entity",
    "name",
    "kind",
    "depth",
    "via",
    "fact_ids",
    "confidence",
    "valid_from",
    "valid_to",
    "attributes",
    "references",
)
#: A full reply carries these unless ``fields`` says otherwise (attributes and references only when named).
DEFAULT_FULL_FIELDS = DEPENDENT_FIELDS[:9]
COMPACT_DEPENDENT_FIELDS = ("entity", "depth", "via", "fact_ids")

_CHUNK = 200  # names per query, well inside SQLite's limit on bound parameters
_ROW_CAP_FACTOR = 5  # a single query reads at most this many facts per allowed dependent


@dataclass
class _Node:
    ref: Ref
    depth: int
    via: list[str] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)
    last: sqlite3.Row | None = None


def dependents(
    conn: sqlite3.Connection,
    cfg: Config,
    actor: str,
    name: str,
    *,
    via: list[str] | None = None,
    depth: int = 1,
    direction: str = "in",
    scope: str = "mine",
    include_negative: bool = False,
    result_kind: str | None = None,
    fields: list[str] | None = None,
    format: str = "full",  # noqa: A002
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    """The entities reachable from ``name`` in up to ``depth`` hops (1 to 3), nearest first.

    ``via`` limits the walk to facts with those actions (default: any action except aliases, which are structure).
    ``direction`` is ``in`` (facts pointing at the entity: its dependents, the default), ``out`` or ``both``. Values
    (dates, numbers, text) are never entities, so the walk neither returns nor passes through them, and only
    positive-confidence facts are followed unless ``include_negative``. ``result_kind`` keeps only entities of that
    kind in the reply (the walk still passes through the others). After the first hop an entity is identified by
    the name and kind its facts store. The walk stops after ``Config.max_dependents`` entities and says so with
    ``capped``.
    """
    if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= MAX_DEPTH:
        raise ValidationError(f"depth must be 1 to {MAX_DEPTH}.")
    if not isinstance(direction, str) or direction.lower() not in DIRECTIONS:
        raise ValidationError(f"direction must be one of {', '.join(DIRECTIONS)}; got {direction!r}.")
    direction = direction.lower()
    actions: list[str] | None = None
    if via is not None:
        if isinstance(via, str):
            via = [part for part in via.split(",") if part.strip()]
        if not isinstance(via, list) or not via:
            raise ValidationError("via must be a non-empty list of actions, or omitted to follow any action.")
        actions = [fold(check_text("via", item, cfg)) for item in via]
    fmt, chosen = check_format(format), check_fields(fields, DEPENDENT_FIELDS)
    wanted_kind = check_kind("result_kind", result_kind, cfg)
    size, skip = page_size(cfg, limit), check_offset(offset)

    start = entity(conn, cfg, actor, scope, name, "entity")
    if start.canonical.kind in cfg.value_kinds:
        raise ValidationError(
            f"{start.canonical} is a value, not an entity: dependents follows facts between entities."
        )

    vis, vparams = visible(scope, actor)
    where = [vis, "action_f != ?"]
    params: list[Any] = [*vparams, fold(cfg.alias_action)]
    if not include_negative:
        where.append("confidence > 0")
    if actions is not None:
        where.append(f"action_f IN ({','.join('?' * len(actions))})")
        params.extend(actions)
    base = " AND ".join(where)
    sides = [("object", "subject")] if direction == "in" else [("subject", "object")] if direction == "out" else [
        ("object", "subject"),
        ("subject", "object"),
    ]  # fmt: skip

    def is_start(kind: str | None, folded: str) -> bool:
        return any(r.f == folded and (r.kind is None or kind is None or r.kind == kind) for r in start.names)

    root = _Node(start.canonical, 0)
    nodes: dict[tuple[str | None, str], _Node] = {}
    frontier: list[tuple[str | None, str]] = []
    capped = False
    row_cap = cfg.max_dependents * _ROW_CAP_FACTOR

    for level in range(1, depth + 1):
        batches: list[tuple[str, str, str, list[Any]]] = []  # (anchor side, other side, clause, params)
        for anchor, other in sides:
            if level == 1:
                clause, cparams = match_refs(anchor, start.names)
                batches.append((anchor, other, clause, cparams))
            else:
                for i in range(0, len(frontier), _CHUNK):
                    keys = frontier[i : i + _CHUNK]
                    marks = ",".join("(?, ?)" for _ in keys)
                    batches.append(
                        (
                            anchor,
                            other,
                            f"({anchor}_f, COALESCE({anchor}_kind, '')) IN (VALUES {marks})",
                            [part for kind, folded in keys for part in (folded, kind or "")],
                        )
                    )
        found: list[tuple[str | None, str]] = []
        for anchor, other, clause, cparams in batches:
            rows = conn.execute(
                f"SELECT * FROM facts WHERE {base} AND {clause} ORDER BY created_at, rowid LIMIT ?",  # nosec B608 - fixed fragments, bound values
                [*params, *cparams, row_cap + 1],
            ).fetchall()
            if len(rows) > row_cap:
                capped = True
                rows = rows[:row_cap]
            for row in rows:
                kind, folded = row[f"{other}_kind"], row[f"{other}_f"]
                if kind in cfg.value_kinds or kind == cfg.actor_kind or is_start(kind, folded):
                    continue
                key = (kind, folded)
                if key in nodes:
                    continue
                parent = root if level == 1 else nodes.get((row[f"{anchor}_kind"], row[f"{anchor}_f"]))
                if parent is None:  # the anchor was reached under a kind its facts spell differently: not a known node
                    continue
                if len(nodes) >= cfg.max_dependents:
                    capped = True
                    break
                nodes[key] = _Node(
                    Ref(kind, row[other]), level, [*parent.via, row["action"]], [*parent.fact_ids, row["id"]], row
                )
                found.append(key)
            if capped and len(nodes) >= cfg.max_dependents:
                break
        frontier = found
        if not frontier or (capped and len(nodes) >= cfg.max_dependents):
            break

    ordered = sorted(nodes.values(), key=lambda n: (n.depth, str(n.ref).casefold()))
    if wanted_kind is not None:
        ordered = [n for n in ordered if n.ref.kind == wanted_kind]
    extras = chosen is not None and bool({"attributes", "references"} & set(chosen))
    rows_out: list[dict[str, Any]] = []
    for node in ordered[skip : skip + size]:
        last = node.last
        if last is None:  # unreachable: every node in the result was reached through a fact
            continue
        item: dict[str, Any] = {
            "entity": str(node.ref),
            "name": node.ref.name,
            "kind": node.ref.kind,
            "depth": node.depth,
            "via": node.via,
            "fact_ids": node.fact_ids,
            "confidence": last["confidence"],
            "valid_from": last["valid_from"],
            "valid_to": last["valid_to"],
        }
        if extras:
            item["attributes"] = json.loads(last["attributes"])
            item["references"] = json.loads(last["refs"])
        rows_out.append(item)
    shaped = shape_rows(
        rows_out,
        key="dependents",
        fmt=fmt,
        fields=chosen,
        compact_default=COMPACT_DEPENDENT_FIELDS,
    )
    return {
        "start": str(start.canonical),
        "direction": direction,
        "depth": depth,
        "via": [str(item) for item in via] if via else None,
        "capped": capped,
        **page_info(limit=size, offset=skip, count=len(rows_out), total=len(ordered)),
        **shaped,
    }
