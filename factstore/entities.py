"""Entities: alias resolution, the self binding ('me'), and types, all built from ordinary facts."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from .config import Config
from .errors import AmbiguousEntityError, NoSelfBindingError
from .rows import match_refs, visible
from .values import Ref, fold, parse_ref, utc_key

_VALID_NOW = "(valid_from_key IS NULL OR valid_from_key <= ?) AND (valid_to_key IS NULL OR valid_to_key > ?)"


@dataclass(frozen=True)
class Entity:
    """A resolved entity: its canonical name and every name (alias) currently pointing at it."""

    canonical: Ref
    names: list[Ref]


def _now_key() -> str:
    return utc_key(datetime.now(UTC))


def _dedupe(refs: list[Ref]) -> list[Ref]:
    unique: dict[tuple[str | None, str], Ref] = {}
    for ref in refs:
        unique.setdefault(ref.key, ref)
    return list(unique.values())


def alias_targets(conn: sqlite3.Connection, cfg: Config, actor: str, scope: str, ref: Ref) -> list[Ref]:
    """What ``ref`` is directly an alias of, from the alias facts the scope can see (positive, currently valid)."""
    vis, vparams = visible(scope, actor)
    match, mparams = match_refs("subject", [ref])
    now = _now_key()
    rows = conn.execute(
        f"SELECT object, object_kind FROM facts WHERE {vis} AND action_f = ? AND confidence > 0 AND {match} "  # nosec B608
        f"AND {_VALID_NOW} ORDER BY rowid",
        [*vparams, fold(cfg.alias_action), *mparams, now, now],
    ).fetchall()
    return _dedupe([Ref(r["object_kind"], r["object"]) for r in rows])


def _ambiguity(ref: Ref, candidates: list[Ref], want_kind: str | None) -> AmbiguousEntityError:
    """The error for a name that several entities answer to, with advice that matches what would actually work."""
    kinds = [candidate.kind for candidate in candidates]
    if want_kind is None and None not in kinds and len(set(kinds)) == len(kinds):
        hint = f"Add a kind prefix (for example '{kinds[0]}:{ref.name}') to pick one, or use one of those full names."
    elif want_kind is not None and not any(kind == want_kind for kind in kinds):
        hint = f"None of them is of kind {want_kind!r}; use one of those full names."
    else:
        hint = "Use one of those full names."
    return AmbiguousEntityError(str(ref), [str(candidate) for candidate in candidates], hint)


def resolve(
    conn: sqlite3.Connection,
    cfg: Config,
    actor: str,
    scope: str,
    ref: Ref,
    *,
    budget: int | None = None,
    path: frozenset[tuple[str | None, str]] = frozenset(),
    want_kind: str | None = None,
) -> Ref:
    """Follow alias facts to the canonical name. Depth-capped and cycle-safe.

    A name with several alias targets is fine as long as they all lead to the same canonical entity. When they do
    not, ``want_kind`` (the kind given as a prefix or a ``*_kind`` filter) picks the one candidate of that kind;
    if that still leaves no single candidate, ``AmbiguousEntityError`` lists them. Nothing is ever guessed.
    """
    budget = cfg.max_alias_depth if budget is None else budget
    here = path | {ref.key}
    targets = [t for t in alias_targets(conn, cfg, actor, scope, ref) if t.key not in here]
    if not targets or budget <= 0:
        return ref
    finals: dict[tuple[str | None, str], Ref] = {}
    for target in targets:
        final = resolve(conn, cfg, actor, scope, target, budget=budget - 1, path=here, want_kind=want_kind)
        finals.setdefault(final.key, final)
    if len(finals) > 1:
        candidates = list(finals.values())
        of_kind = [candidate for candidate in candidates if want_kind is not None and candidate.kind == want_kind]
        if len(of_kind) == 1:
            return of_kind[0]
        raise _ambiguity(ref, of_kind or candidates, want_kind)
    return next(iter(finals.values()))


def reaches(conn: sqlite3.Connection, cfg: Config, actor: str, start: Ref, goal: Ref) -> bool:
    """Whether following alias facts from ``start`` can arrive at ``goal`` (used to refuse alias cycles)."""
    seen = {start.key}
    frontier = [start]
    for _ in range(cfg.max_alias_depth):
        nxt: list[Ref] = []
        for ref in frontier:
            for target in alias_targets(conn, cfg, actor, "all", ref):
                if target.key == goal.key:
                    return True
                if target.key not in seen:
                    seen.add(target.key)
                    nxt.append(target)
        frontier = nxt
        if not frontier:
            break
    return False


def entity_names(conn: sqlite3.Connection, cfg: Config, actor: str, scope: str, canonical: Ref) -> list[Ref]:
    """The canonical name plus every name that is, transitively, an alias of it (depth- and size-capped)."""
    vis, vparams = visible(scope, actor)
    names: dict[tuple[str | None, str], Ref] = {canonical.key: canonical}
    frontier = [canonical]
    now = _now_key()
    for _ in range(cfg.max_alias_depth):
        if not frontier or len(names) >= cfg.max_entity_names:
            break
        match, mparams = match_refs("object", frontier)
        rows = conn.execute(
            f"SELECT subject, subject_kind FROM facts WHERE {vis} AND action_f = ? AND confidence > 0 AND {match} "  # nosec B608
            f"AND {_VALID_NOW} ORDER BY rowid",
            [*vparams, fold(cfg.alias_action), *mparams, now, now],
        ).fetchall()
        frontier = []
        for row in rows:
            ref = Ref(row["subject_kind"], row["subject"])
            if ref.key not in names and len(names) < cfg.max_entity_names:
                names[ref.key] = ref
                frontier.append(ref)
    return list(names.values())


def self_binding(conn: sqlite3.Connection, cfg: Config, actor: str) -> sqlite3.Row | None:
    """The actor's own binding fact (``actor:<actor>`` alias of an entity), if there is one."""
    now = _now_key()
    return conn.execute(
        f"SELECT * FROM facts WHERE created_by = ? AND subject_kind = ? AND subject_f = ? AND action_f = ? "  # nosec B608
        f"AND confidence > 0 AND {_VALID_NOW} ORDER BY rowid DESC LIMIT 1",
        [actor, cfg.actor_kind, actor, fold(cfg.alias_action), now, now],
    ).fetchone()


def is_self_token(cfg: Config, ref: Ref) -> bool:
    return ref.kind is None and ref.f in cfg.self_tokens


def canonical_ref(
    conn: sqlite3.Connection,
    cfg: Config,
    actor: str,
    scope: str,
    text: str,
    label: str,
    kind_hint: str | None = None,
) -> Ref:
    """Parse a name and resolve it: 'me' to the actor's own entity, anything else through alias facts.

    A kind prefix on the name (or ``kind_hint``, from a ``*_kind`` filter) says what kind of entity is meant, which
    settles an alias that several entities answer to.
    """
    ref = parse_ref(label, text, cfg)
    if ref.kind in cfg.value_kinds:  # a date, number or text is a value, not an entity: nothing to resolve
        return ref
    if is_self_token(cfg, ref):
        binding = self_binding(conn, cfg, actor)
        if binding is None:
            raise NoSelfBindingError(
                f"{text!r} means you, but you have not said who you are. Bind yourself first with set_self "
                "(for example set_self('person:Your Name'))."
            )
        ref = Ref(binding["object_kind"], binding["object"])
    return resolve(conn, cfg, actor, scope, ref, want_kind=ref.kind or kind_hint)


def entity(
    conn: sqlite3.Connection,
    cfg: Config,
    actor: str,
    scope: str,
    text: str,
    label: str = "name",
    kind_hint: str | None = None,
) -> Entity:
    canonical = canonical_ref(conn, cfg, actor, scope, text, label, kind_hint)
    if canonical.kind in cfg.value_kinds:
        return Entity(canonical, [canonical])
    return Entity(canonical, entity_names(conn, cfg, actor, scope, canonical))


def instances_of(conn: sqlite3.Connection, cfg: Config, actor: str, scope: str, type_name: str) -> set[str]:
    """Folded names of everything that is, transitively, an instance of ``type_name`` (cycle-safe, depth-capped)."""
    vis, vparams = visible(scope, actor)
    found: set[str] = set()
    frontier = {fold(type_name)}
    for _ in range(cfg.max_type_depth):
        if not frontier:
            break
        marks = ",".join("?" * len(frontier))
        rows = conn.execute(
            f"SELECT DISTINCT subject_f FROM facts WHERE {vis} AND action_f = ? AND confidence > 0 "  # nosec B608
            f"AND object_f IN ({marks})",
            [*vparams, fold(cfg.type_action), *frontier],
        ).fetchall()
        frontier = {r["subject_f"] for r in rows} - found
        found |= frontier
    return found


def types_of(
    conn: sqlite3.Connection, cfg: Config, actor: str, scope: str, names: list[Ref]
) -> tuple[list[str], list[str]]:
    """(direct types, inherited types) of an entity following type facts, cycle-safe and depth-capped."""
    vis, vparams = visible(scope, actor)
    direct: dict[str, str] = {}
    inherited: dict[str, str] = {}
    start = {name.f for name in names}
    seen = set(start)
    frontier = sorted(start)
    for depth in range(cfg.max_type_depth):
        if not frontier:
            break
        marks = ",".join("?" * len(frontier))
        rows = conn.execute(
            f"SELECT object, object_f FROM facts WHERE {vis} AND action_f = ? AND confidence > 0 "  # nosec B608
            f"AND subject_f IN ({marks}) ORDER BY rowid",
            [*vparams, fold(cfg.type_action), *frontier],
        ).fetchall()
        frontier = []
        for row in rows:
            if row["object_f"] in seen:
                continue
            seen.add(row["object_f"])
            (direct if depth == 0 else inherited)[row["object_f"]] = row["object"]
            frontier.append(row["object_f"])
    return list(direct.values()), list(inherited.values())
