"""relationships_between: the facts connecting two entities, directly or through one intermediary."""

import json
import sqlite3
from typing import Any

from .config import Config
from .entities import entity
from .errors import ValidationError
from .rows import fact_dict, match_refs, visible
from .shape import COMPACT_FACT_FIELDS, FACT_FIELDS, check_fields, check_format
from .values import fold

MAX_DEPTH = 2
MAX_PATHS = 100
_SEP = "\x1f"
#: Fields a direct fact of ``relationships_between`` can be trimmed to: a fact's, plus which way it points.
DIRECT_FIELDS = (*FACT_FIELDS, "direction")


def relationships_between(
    conn: sqlite3.Connection,
    cfg: Config,
    actor: str,
    a: str,
    b: str,
    *,
    scope: str = "mine",
    max_depth: int = 1,
    fields: list[str] | None = None,
    format: str = "full",  # noqa: A002
) -> dict[str, Any]:
    """Facts linking entity ``a`` and entity ``b`` in either direction, aliases resolved on both sides.

    ``max_depth`` 1 returns direct facts. ``max_depth`` 2 also returns paths through exactly one intermediary
    entity (a to x to b, each hop in either direction). Only positive-confidence facts count, alias facts are
    structure rather than relationships, and the walk never revisits a node.

    ``fields`` trims every fact to those fields (``direction`` applies to direct facts only). ``format='compact'``
    returns ``direct`` as ``{columns, rows}`` and ``indirect`` as ``{fact_columns, columns: [via, facts], rows}``
    where each path's ``facts`` are rows of ``fact_columns``.
    """
    if not isinstance(max_depth, int) or isinstance(max_depth, bool) or not 1 <= max_depth <= MAX_DEPTH:
        raise ValidationError(f"max_depth must be 1 to {MAX_DEPTH}.")
    fmt, chosen = check_format(format), check_fields(fields, DIRECT_FIELDS)
    first = entity(conn, cfg, actor, scope, a, "a")
    second = entity(conn, cfg, actor, scope, b, "b")
    if first.canonical.key == second.canonical.key:
        raise ValidationError(f"a and b are the same entity ({first.canonical}).")

    vis, vparams = visible(scope, actor)
    structural = fold(cfg.alias_action)
    a_subject, a_sp = match_refs("subject", first.names)
    a_object, a_op = match_refs("object", first.names)
    b_subject, b_sp = match_refs("subject", second.names)
    b_object, b_op = match_refs("object", second.names)
    rows = conn.execute(
        f"SELECT *, CASE WHEN {a_subject} THEN 'a_to_b' ELSE 'b_to_a' END AS direction FROM facts "  # nosec B608
        f"WHERE {vis} AND confidence > 0 AND action_f != ? "
        f"AND (({a_subject} AND {b_object}) OR ({b_subject} AND {a_object})) ORDER BY created_at, rowid LIMIT ?",
        [*a_sp, *vparams, structural, *a_sp, *b_op, *b_sp, *a_op, cfg.max_limit + 1],
    ).fetchall()
    direct_truncated = len(rows) > cfg.max_limit
    direct = [{**fact_dict(row), "direction": row["direction"]} for row in rows[: cfg.max_limit]]

    indirect: list[dict[str, Any]] = []
    indirect_truncated = False
    if max_depth >= 2:
        indirect, indirect_truncated = _one_hop_paths(
            conn, vis, vparams, structural, {n.f for n in first.names}, {n.f for n in second.names}
        )
    if fmt == "full" and chosen is None:
        shaped_direct: Any = direct
        shaped_indirect: Any = indirect
    else:
        direct_columns = list(chosen or (*COMPACT_FACT_FIELDS, "direction"))
        fact_columns = [c for c in (chosen or COMPACT_FACT_FIELDS) if c != "direction"] or list(COMPACT_FACT_FIELDS)
        if fmt == "compact":
            shaped_direct = {"columns": direct_columns, "rows": [[r.get(c) for c in direct_columns] for r in direct]}
            shaped_indirect = {
                "fact_columns": fact_columns,
                "columns": ["via", "facts"],
                "rows": [[p["via"], [[f.get(c) for c in fact_columns] for f in p["facts"]]] for p in indirect],
            }
        else:
            shaped_direct = [{c: r.get(c) for c in direct_columns} for r in direct]
            shaped_indirect = [
                {"via": p["via"], "facts": [{c: f.get(c) for c in fact_columns} for f in p["facts"]]} for p in indirect
            ]
    return {
        "a": str(first.canonical),
        "b": str(second.canonical),
        "direct": shaped_direct,
        "direct_truncated": direct_truncated,
        "indirect": shaped_indirect,
        "indirect_truncated": indirect_truncated,
    }


def _one_hop_paths(
    conn: sqlite3.Connection, vis: str, vparams: list[Any], structural: str, starts: set[str], goals: set[str]
) -> tuple[list[dict[str, Any]], bool]:
    """Paths start - via - goal from a depth-capped recursive walk over facts that never revisits a node.

    Returns the paths (at most MAX_PATHS) and whether more existed than were returned.
    """
    edges = (
        f"SELECT id AS fid, subject_f AS src, object_f AS dst FROM facts WHERE {vis} AND confidence > 0 "  # nosec B608
        f"AND action_f != ? UNION ALL "
        f"SELECT id, object_f, subject_f FROM facts WHERE {vis} AND confidence > 0 AND action_f != ?"
    )
    goal_marks = ",".join("?" * len(goals))
    sql = f"""
        WITH RECURSIVE edge(fid, src, dst) AS ({edges}),
        walk(depth, node, facts, nodes) AS (
            SELECT 0, value, '', char(31) || value || char(31) FROM (SELECT DISTINCT value FROM json_each(?))
            UNION ALL
            SELECT w.depth + 1, e.dst, w.facts || e.fid || ',', w.nodes || e.dst || char(31)
            FROM walk w JOIN edge e ON e.src = w.node
            WHERE w.depth < {MAX_DEPTH} AND instr(w.nodes, char(31) || e.dst || char(31)) = 0
        )
        SELECT facts, nodes FROM walk WHERE depth = {MAX_DEPTH} AND node IN ({goal_marks}) LIMIT ?
    """  # nosec B608 - fixed fragments, bound values
    params = [*vparams, structural, *vparams, structural, json.dumps(sorted(starts)), *sorted(goals), MAX_PATHS + 1]
    paths: list[dict[str, Any]] = []
    rows = conn.execute(sql, params).fetchall()
    truncated = len(rows) > MAX_PATHS
    for row in rows[:MAX_PATHS]:
        via = row["nodes"].strip(_SEP).split(_SEP)[1]
        if via in starts or via in goals:  # another name for one of the endpoints, not an intermediary
            continue
        fact_ids = [part for part in row["facts"].split(",") if part]
        facts = [fact_dict(conn.execute("SELECT * FROM facts WHERE id = ?", (fid,)).fetchone()) for fid in fact_ids]
        paths.append({"via": via, "facts": facts})
    return paths, truncated
