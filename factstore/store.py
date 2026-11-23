"""FactStore: the public engine API. Every call takes the acting ``actor``; the engine knows nothing about auth."""

import json
import sqlite3
from pathlib import Path
from typing import IO, Any

from . import portability, reviews
from .config import Config
from .entities import Entity, canonical_ref, entity, instances_of, is_self_token, reaches, self_binding, types_of
from .errors import FactsError, ValidationError
from .graph import relationships_between
from .rows import fact_dict, fetch_visible, insert_fact, match_refs, visible
from .schema import initialise, session
from .values import (
    Ref,
    actor_id,
    check_attribute_key,
    check_attributes,
    check_confidence,
    check_kind,
    check_offset,
    check_references,
    check_text,
    fold,
    iso,
    kind_prefix_warnings,
    like,
    now_iso,
    page_info,
    page_size,
    parse_instant,
    parse_ref,
    parse_when,
    uuid7,
    with_warnings,
)


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()


class FactStore:
    """A SQLite-backed store of facts: (subject, action, object) plus validity, signed confidence and provenance."""

    def __init__(self, path: str | Path, config: Config | None = None):
        self.path = Path(path)
        self.config = config or Config()
        initialise(self.path)

    # ----------------------------------------------------------------------------------------- writing

    def add_fact(
        self,
        actor: str,
        subject: str,
        action: str,
        object: str,  # noqa: A002
        *,
        confidence: float = 1.0,
        valid_from: str | None = None,
        valid_to: str | None = None,
        public: bool = False,
        attributes: dict[str, Any] | None = None,
        references: list[str] | None = None,
        check_types: bool = False,
    ) -> dict[str, Any]:
        """Store a fact. Names are resolved through alias facts (and 'me') so each entity has one stored name.

        With ``check_types`` the reply also lists, under ``untyped``, the entity names that have no type fact yet.
        A name that looks like a kind prefix the store does not know (``claim:Foo``) is kept as literal text, and
        the reply says so under ``warnings``.
        """
        who = actor_id(actor)
        with session(self.path) as conn:
            stored = self._add(
                conn, who, subject, action, object, confidence, valid_from, valid_to, public, attributes, references,
                check_types,
            )  # fmt: skip
        return with_warnings(stored, kind_prefix_warnings(self.config, {"subject": subject, "object": object}))

    def add_many(self, actor: str, facts: list[dict[str, Any]]) -> dict[str, Any]:
        """Store up to ``Config.max_batch`` facts in one transaction: all of them are written, or none are.

        Each item is a dict with ``subject``, ``action`` and ``object`` and optionally ``confidence``,
        ``valid_from``, ``valid_to``, ``public``, ``attributes`` and ``references``. Items are written in order and
        later items can use aliases created by earlier ones. Returns ``{count, ids}`` with the ids in item order
        (an alias that already existed reports the existing fact's id). A bad item fails the whole batch with an
        error that names its position.
        """
        who = actor_id(actor)
        cfg = self.config
        if not isinstance(facts, list) or not facts:
            raise ValidationError("facts must be a non-empty list of fact objects.")
        if len(facts) > cfg.max_batch:
            raise ValidationError(
                f"A batch holds at most {cfg.max_batch} facts; got {len(facts)}. Send it in several calls."
            )
        required, optional = ("subject", "action", "object"), (
            "confidence", "valid_from", "valid_to", "public", "attributes", "references",
        )  # fmt: skip
        for index, item in enumerate(facts):
            if not isinstance(item, dict):
                raise ValidationError(f"Item {index}: each fact must be an object.")
            missing = [name for name in required if name not in item]
            unknown = sorted(set(item) - set(required) - set(optional))
            if missing or unknown:
                raise ValidationError(
                    f"Item {index}: " + (f"missing {', '.join(missing)}. " if missing else "")
                    + (f"unknown field(s) {', '.join(unknown)}. " if unknown else "")
                    + f"Allowed fields: {', '.join((*required, *optional))}."
                )  # fmt: skip
        ids: list[str] = []
        with session(self.path) as conn:  # any exception rolls the whole batch back
            for index, item in enumerate(facts):
                try:
                    stored = self._add(
                        conn, who, item["subject"], item["action"], item["object"],
                        item.get("confidence", 1.0), item.get("valid_from"), item.get("valid_to"),
                        item.get("public", False), item.get("attributes"), item.get("references"), False,
                    )  # fmt: skip
                except FactsError as error:
                    error.args = (f"Item {index}: {error}",)
                    raise
                ids.append(stored["id"])
        notes = [
            f"Item {index}: {warning}"
            for index, item in enumerate(facts)
            for warning in kind_prefix_warnings(cfg, {"subject": item["subject"], "object": item["object"]})
        ]
        return with_warnings({"count": len(ids), "ids": ids}, notes)

    def _add(
        self,
        conn: sqlite3.Connection,
        who: str,
        subject: str,
        action: str,
        obj: str,
        confidence: float | None,
        valid_from: str | None,
        valid_to: str | None,
        public: bool,
        attributes: dict[str, Any] | None,
        references: list[str] | None,
        check_types: bool,
    ) -> dict[str, Any]:
        cfg = self.config
        action_text = check_text("action", action, cfg)
        alias = fold(action_text) == fold(cfg.alias_action)
        s_ref, o_ref = self._resolve_names(conn, who, subject, action_text, obj)
        if alias:
            found = self._existing_alias(conn, who, s_ref, o_ref)
            if found is not None:
                return {**fact_dict(found), "already_exists": True}
        record = self._record(
            who, s_ref, action_text, o_ref, confidence, valid_from, valid_to, public, attributes, references
        )
        insert_fact(conn, record)
        stored = fact_dict(fetch_visible(conn, who, record["id"], "mine"))
        if check_types and not alias and fold(action_text) != fold(cfg.type_action):
            stored["untyped"] = self._untyped(conn, who, [s_ref, o_ref])
        return stored

    def update_fact(
        self,
        actor: str,
        fact_id: str,
        *,
        subject: str = UNSET,
        action: str = UNSET,
        object: str = UNSET,  # noqa: A002
        confidence: float = UNSET,
        valid_from: str | None = UNSET,
        valid_to: str | None = UNSET,
        public: bool = UNSET,
        attributes: dict[str, Any] | None = UNSET,
        references: list[str] | None = UNSET,
    ) -> dict[str, Any]:
        """Change fields of one of the actor's own facts. Omitted fields stay; ``None`` clears a validity bound."""
        who = actor_id(actor)
        cfg = self.config
        with session(self.path) as conn:
            row = fetch_visible(conn, who, fact_id, "all")
            reviews.require_owner(row, who)
            action_text = row["action"] if action is UNSET else check_text("action", action, cfg)
            s_ref = Ref(row["subject_kind"], row["subject"])
            o_ref = Ref(row["object_kind"], row["object"])
            if subject is not UNSET or object is not UNSET or action is not UNSET:
                s_ref, o_ref = self._resolve_names(
                    conn,
                    who,
                    str(s_ref) if subject is UNSET else subject,
                    action_text,
                    str(o_ref) if object is UNSET else object,
                )
            from_text, from_key = (row["valid_from"], row["valid_from_key"]) if valid_from is UNSET else (None, None)
            to_text, to_key = (row["valid_to"], row["valid_to_key"]) if valid_to is UNSET else (None, None)
            if valid_from is not UNSET and valid_from is not None:
                from_text, from_key = parse_when(valid_from)
            if valid_to is not UNSET and valid_to is not None:
                to_text, to_key = parse_when(valid_to, end=True)
            self._check_interval(from_key, to_key)
            attrs = row["attributes"] if attributes is UNSET else json.dumps(check_attributes(attributes, cfg))
            refs = row["refs"] if references is UNSET else json.dumps(check_references(references, cfg))
            conn.execute(
                "UPDATE facts SET subject = ?, subject_f = ?, subject_kind = ?, action = ?, action_f = ?, "
                "object = ?, object_f = ?, object_kind = ?, confidence = ?, valid_from = ?, valid_from_key = ?, "
                "valid_to = ?, valid_to_key = ?, public = ?, attributes = ?, refs = ?, updated_by = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    s_ref.name, s_ref.f, s_ref.kind, action_text, fold(action_text), o_ref.name, o_ref.f, o_ref.kind,
                    row["confidence"] if confidence is UNSET else check_confidence(confidence),
                    from_text, from_key, to_text, to_key,
                    row["public"] if public is UNSET else int(bool(public)),
                    attrs, refs, who, now_iso(), row["id"],
                ),
            )  # fmt: skip
            updated = fact_dict(fetch_visible(conn, who, row["id"], "mine"))
        renamed = {label: value for label, value in (("subject", subject), ("object", object)) if value is not UNSET}
        return with_warnings(updated, kind_prefix_warnings(cfg, renamed))

    def delete_fact(self, actor: str, fact_id: str) -> dict[str, Any]:
        """Delete one of the actor's own facts, with the review requests and reviews that point at it."""
        who = actor_id(actor)
        with session(self.path) as conn:
            row = fetch_visible(conn, who, fact_id, "all")
            reviews.require_owner(row, who)
            conn.execute("DELETE FROM reviews WHERE fact_id = ?", (row["id"],))
            conn.execute("DELETE FROM review_requests WHERE fact_id = ?", (row["id"],))
            conn.execute("DELETE FROM facts WHERE id = ?", (row["id"],))
            return {"deleted": row["id"]}

    def add_alias(self, actor: str, alias: str, canonical: str, *, public: bool = False) -> dict[str, Any]:
        """Say that ``alias`` is another name for ``canonical`` (stored as an ordinary alias fact)."""
        return self.add_fact(actor, alias, self.config.alias_action, canonical, public=public)

    def set_self(self, actor: str, name: str) -> dict[str, Any]:
        """Bind the actor to an entity, so that 'me' and 'self' resolve to it. Replaces an earlier binding."""
        who = actor_id(actor)
        cfg = self.config
        with session(self.path) as conn:
            target = parse_ref("name", name, cfg)
            if is_self_token(cfg, target) or target.kind in cfg.value_kinds or target.kind == cfg.actor_kind:
                raise ValidationError("Bind yourself to a named entity such as 'person:Ada Example'.")
            target = canonical_ref(conn, cfg, who, "all", name, "name")
            subject = Ref(cfg.actor_kind, who)
            existing = self_binding(conn, cfg, who)
            now = now_iso()
            if existing is None:
                record = self._record(who, subject, cfg.alias_action, target, 1.0, None, None, False, None, None)
                insert_fact(conn, record)
                fact_id = record["id"]
            else:
                conn.execute(
                    "UPDATE facts SET object = ?, object_f = ?, object_kind = ?, updated_by = ?, updated_at = ? "
                    "WHERE id = ?",
                    (target.name, target.f, target.kind, who, now, existing["id"]),
                )
                fact_id = existing["id"]
            bound = fact_dict(fetch_visible(conn, who, fact_id, "mine"))
        return with_warnings(bound, kind_prefix_warnings(cfg, {"name": name}))

    # ----------------------------------------------------------------------------------------- reading

    def get_fact(self, actor: str, fact_id: str) -> dict[str, Any]:
        """One fact the actor can see, with its ``reviews``: all of them for the fact's owner, only the actor's
        own entries for anyone else."""
        who = actor_id(actor)
        with session(self.path) as conn:
            row = fetch_visible(conn, who, fact_id, "all")
            return {**fact_dict(row), "reviews": reviews.reviews_for(conn, self.config, who, row)}

    def search_facts(
        self,
        actor: str,
        *,
        scope: str = "mine",
        subject: str | None = None,
        action: str | None = None,
        object: str | None = None,  # noqa: A002
        subject_kind: str | None = None,
        object_kind: str | None = None,
        subject_type: str | None = None,
        object_type: str | None = None,
        min_confidence: float | None = None,
        include_negative: bool = False,
        valid_at: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        q: str | None = None,
        attribute_key: str | None = None,
        attribute_value: str | None = None,
        reviewed_before: str | None = None,
        include_never_reviewed: bool = False,
        reviewed: bool | None = None,
        has_period: bool | None = None,
        valid_within: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search the facts a scope can see, newest first, one page at a time.

        Names in ``subject``/``object`` are resolved through aliases, so any alias finds the entity's facts; a kind
        prefix (or ``subject_kind``/``object_kind``) settles an alias that several entities answer to. Only
        positive-confidence facts are returned unless ``include_negative`` is set. The reply carries ``total`` (all
        matches), ``offset``, ``limit`` and ``truncated`` (true when more matches follow this page).

        Validity: ``valid_at`` keeps facts valid at an instant. ``valid_from``/``valid_to`` keep facts whose period
        OVERLAPS that window (a bound a fact leaves open counts as reaching it), or, with ``valid_within=True``,
        only facts whose period lies ENTIRELY inside the window (so a fact with no period, or an open bound where
        the window has one, is excluded). ``has_period`` keeps facts that have a valid_from or valid_to (True) or
        neither (False).

        Review state: ``reviewed_before`` keeps facts last REVIEWED before a time (never-reviewed facts are not
        included unless ``include_never_reviewed``, which treats creation as the baseline); ``reviewed`` keeps facts
        that have been reviewed (True) or never have (False).

        ``q`` matches every word (any order, ignoring case and accents) in the subject, object, action, attribute
        names and values, and references.
        """
        who = actor_id(actor)
        cfg = self.config
        vis, vparams = visible(scope, who)
        where, params = [vis], list(vparams)
        size, skip = page_size(cfg, limit), check_offset(offset)
        with session(self.path) as conn:
            for column, text, kind in (("subject", subject, subject_kind), ("object", object, object_kind)):
                if text is not None:
                    hint = check_kind(f"{column}_kind", kind, cfg)
                    clause, cparams = match_refs(column, entity(conn, cfg, who, scope, text, column, hint).names)
                    where.append(clause)
                    params.extend(cparams)
            if action is not None:
                where.append("action_f = ?")
                params.append(fold(check_text("action", action, cfg)))
            if action is None or fold(action) != fold(cfg.alias_action):
                # alias facts are plumbing: they show up in describe_entity, or when asked for by action
                where.append("action_f != ?")
                params.append(fold(cfg.alias_action))
            for column, kind in (("subject_kind", subject_kind), ("object_kind", object_kind)):
                if kind is not None:
                    where.append(f"{column} = ?")
                    params.append(check_kind(column, kind, cfg))
            for column, type_name in (("subject_f", subject_type), ("object_f", object_type)):
                if type_name is not None:
                    members = sorted(instances_of(conn, cfg, who, scope, type_name))
                    where.append(f"{column} IN ({','.join('?' * len(members)) or 'NULL'})")  # nosec B608
                    params.extend(members)
            if not include_negative:
                where.append("confidence > 0")
            if min_confidence is not None:
                where.append("confidence >= ?")
                params.append(check_confidence(min_confidence))
            if valid_at is not None:
                _, key = parse_when(valid_at)
                where.append(
                    "(valid_from_key IS NULL OR valid_from_key <= ?) AND (valid_to_key IS NULL OR valid_to_key > ?)"
                )
                params.extend([key, key])
            if valid_within and valid_from is None and valid_to is None:
                raise ValidationError("valid_within needs valid_from and/or valid_to: the window the period must fit.")
            if valid_to is not None:
                _, key = parse_when(valid_to, end=True)
                if valid_within:  # the fact ends no later than the window does
                    where.append("(valid_to_key IS NOT NULL AND valid_to_key <= ?)")
                else:  # overlap with [valid_from, valid_to]
                    where.append("(valid_from_key IS NULL OR valid_from_key < ?)")
                params.append(key)
            if valid_from is not None:
                _, key = parse_when(valid_from)
                if valid_within:  # the fact starts no earlier than the window does
                    where.append("(valid_from_key IS NOT NULL AND valid_from_key >= ?)")
                else:
                    where.append("(valid_to_key IS NULL OR valid_to_key > ?)")
                params.append(key)
            if has_period is True:
                where.append("(valid_from_key IS NOT NULL OR valid_to_key IS NOT NULL)")
            elif has_period is False:
                where.append("(valid_from_key IS NULL AND valid_to_key IS NULL)")
            for term in fold(q or "").split():  # every word must appear, in any order
                where.append(
                    "(subject_f || ' ' || object_f || ' ' || action_f || ' ' || fact_extras(attributes, refs)) "
                    "LIKE ? ESCAPE '\\'"
                )
                params.append(like(term))
            if attribute_key is not None:
                path = f'$."{check_attribute_key(attribute_key)}"'
                if attribute_value is None:
                    where.append("json_extract(attributes, ?) IS NOT NULL")
                    params.append(path)
                else:
                    where.append("CAST(json_extract(attributes, ?) AS TEXT) = ?")
                    params.extend([path, str(attribute_value)])
            elif attribute_value is not None:
                raise ValidationError("attribute_value needs attribute_key.")
            if reviewed is False and reviewed_before is not None and not include_never_reviewed:
                raise ValidationError(
                    "reviewed=False (never reviewed) cannot be combined with reviewed_before unless "
                    "include_never_reviewed is set: reviewed_before only matches facts that have been reviewed."
                )
            if reviewed_before is not None:
                if include_never_reviewed:
                    where.append("COALESCE(reviewed_at, created_at) < ?")
                else:
                    where.append("(reviewed_at IS NOT NULL AND reviewed_at < ?)")
                params.append(iso(parse_instant(reviewed_before)))
            if reviewed is True:
                where.append("reviewed_at IS NOT NULL")
            elif reviewed is False:
                where.append("reviewed_at IS NULL")
            clause = " AND ".join(where)
            total = conn.execute(f"SELECT COUNT(*) FROM facts WHERE {clause}", params).fetchone()[0]  # nosec B608
            rows = conn.execute(
                f"SELECT * FROM facts WHERE {clause} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",  # nosec B608
                [*params, size, skip],
            ).fetchall()
            found = {
                **page_info(limit=size, offset=skip, count=len(rows), total=total),
                "facts": [fact_dict(row) for row in rows],
            }
        return with_warnings(found, kind_prefix_warnings(cfg, {"subject": subject, "object": object}))

    def describe_entity(self, actor: str, name: str, *, scope: str = "mine") -> dict[str, Any]:
        """Canonical name, aliases, types (direct and inherited), fact counts and when it was last reviewed.

        ``exists`` is true when any fact the scope can see mentions the entity (under any of its names, whatever the
        action or confidence), so an unknown name is distinguishable from a known entity with nothing counted.
        """
        who = actor_id(actor)
        cfg = self.config
        vis, vparams = visible(scope, who)
        with session(self.path) as conn:
            ent: Entity = entity(conn, cfg, who, scope, name)
            counts: dict[str, int] = {}
            for role in ("subject", "object"):
                clause, cparams = match_refs(role, ent.names)
                counts[role] = conn.execute(
                    f"SELECT COUNT(*) FROM facts WHERE {vis} AND confidence > 0 AND action_f != ? AND {clause}",  # nosec B608
                    [*vparams, fold(cfg.alias_action), *cparams],
                ).fetchone()[0]
            s_clause, s_params = match_refs("subject", ent.names)
            o_clause, o_params = match_refs("object", ent.names)
            last = conn.execute(
                f"SELECT MAX(reviewed_at) FROM facts WHERE {vis} AND confidence > 0 AND ({s_clause} OR {o_clause})",  # nosec B608
                [*vparams, *s_params, *o_params],
            ).fetchone()[0]
            exists = (
                conn.execute(
                    f"SELECT 1 FROM facts WHERE {vis} AND ({s_clause} OR {o_clause}) LIMIT 1",  # nosec B608
                    [*vparams, *s_params, *o_params],
                ).fetchone()
                is not None
            )
            direct, inherited = types_of(conn, cfg, who, scope, ent.names)
            described = {
                "name": ent.canonical.name,
                "kind": ent.canonical.kind,
                "ref": str(ent.canonical),
                "exists": exists,
                "aliases": [str(n) for n in ent.names if n.key != ent.canonical.key],
                "types": direct,
                "inherited_types": inherited,
                "facts_as_subject": counts["subject"],
                "facts_as_object": counts["object"],
                "last_reviewed": last,
            }
        return with_warnings(described, kind_prefix_warnings(cfg, {"name": name}))

    def relationships_between(
        self, actor: str, a: str, b: str, *, scope: str = "mine", max_depth: int = 1
    ) -> dict[str, Any]:
        who = actor_id(actor)
        with session(self.path) as conn:
            found = relationships_between(conn, self.config, who, a, b, scope=scope, max_depth=max_depth)
        return with_warnings(found, kind_prefix_warnings(self.config, {"a": a, "b": b}))

    # ----------------------------------------------------------------------------------------- reviews

    def request_review(self, actor: str, fact_id: str, of_actor: str, note: str | None = None) -> dict[str, Any]:
        who = actor_id(actor)
        with session(self.path) as conn:
            return reviews.request_review(conn, self.config, who, fact_id, of_actor, note)

    def mark_reviewed(
        self, actor: str, fact_id: str, outcome: str, note: str | None = None, confidence: float | None = None
    ) -> dict[str, Any]:
        """Record a review. A reviewer's dispute creates their own counter-fact with the opposite sign of the
        disputed one (``confidence`` states a graded dispute, with that opposite sign)."""
        who = actor_id(actor)
        with session(self.path) as conn:
            return reviews.mark_reviewed(conn, self.config, who, fact_id, outcome, note, confidence)

    def pending_reviews(
        self, actor: str, direction: str = "received", limit: int | None = None, offset: int = 0
    ) -> dict[str, Any]:
        who = actor_id(actor)
        with session(self.path) as conn:
            return reviews.pending_reviews(conn, self.config, who, direction, limit, offset)

    def due_for_review(
        self,
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
        who = actor_id(actor)
        with session(self.path) as conn:
            return reviews.due_for_review(
                conn, self.config, who, before, limit,
                offset=offset, action=action, subject=subject, object_kind=object_kind,
                created_before=created_before, order=order,
            )  # fmt: skip

    def review_outcomes(
        self,
        actor: str,
        since: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        role: str = "owner",
    ) -> dict[str, Any]:
        """Review entries (confirmed, disputed, unsure), newest first.

        ``role='owner'`` (default) lists what anyone has said about the actor's own facts; ``'reviewer'`` lists the
        reviews the actor wrote themselves, on any fact; ``'all'`` lists both. A reviewer sees only their own
        entries on someone else's fact, and the fact's wording only while they can still read it.
        """
        who = actor_id(actor)
        with session(self.path) as conn:
            return reviews.review_outcomes(conn, self.config, who, since, limit, offset, role)

    # ----------------------------------------------------------------------------------------- portability

    def export_jsonl(self, out: IO[str], actor: str | None = None) -> int:
        """Write the actor's facts (or every fact when ``actor`` is None) as JSON lines. Returns the fact count."""
        who = actor_id(actor) if actor is not None else None
        with session(self.path) as conn:
            return portability.export_jsonl(conn, out, who)

    def import_jsonl(self, source: IO[str]) -> dict[str, int]:
        """Load JSON lines written by ``export_jsonl``. Ids and created_at are kept; existing ids are skipped."""
        with session(self.path) as conn:
            return portability.import_jsonl(conn, self.config, source)

    # ----------------------------------------------------------------------------------------- internals

    def _resolve_names(
        self,
        conn: sqlite3.Connection,
        who: str,
        subject: str,
        action_text: str,
        obj: str,
    ) -> tuple[Ref, Ref]:
        """Canonicalise the subject and object of a fact about to be written."""
        cfg = self.config
        alias = fold(action_text) == fold(cfg.alias_action)
        s_raw = parse_ref("subject", subject, cfg)
        if s_raw.kind == cfg.actor_kind and s_raw.f != fold(who):
            raise ValidationError(f"{cfg.actor_kind}: names can only refer to yourself ({cfg.actor_kind}:{who}).")
        if alias:
            if is_self_token(cfg, s_raw):
                raise ValidationError("'me' cannot be an alias: it always means you. Use set_self to say who you are.")
            subject_ref = s_raw
        else:
            subject_ref = canonical_ref(conn, cfg, who, "all", subject, "subject")
        object_ref = canonical_ref(conn, cfg, who, "all", obj, "object")
        if alias:
            if s_raw.kind in cfg.value_kinds or object_ref.kind in cfg.value_kinds:
                raise ValidationError("Aliases are between entities, not values.")
            if s_raw.key == parse_ref("object", obj, cfg).key:
                raise ValidationError(f"{s_raw} cannot be an alias of itself.")
            if s_raw.key == object_ref.key or reaches(conn, cfg, who, object_ref, s_raw):
                raise ValidationError(f"{obj!r} already resolves to {s_raw}; this alias would make a cycle.")
        return subject_ref, object_ref

    def _existing_alias(self, conn: sqlite3.Connection, who: str, s_ref: Ref, o_ref: Ref) -> sqlite3.Row | None:
        subject_match, subject_params = match_refs("subject", [s_ref])
        object_match, object_params = match_refs("object", [o_ref])
        return conn.execute(
            f"SELECT * FROM facts WHERE created_by = ? AND action_f = ? AND confidence > 0 AND {subject_match} "  # nosec B608
            f"AND {object_match} ORDER BY rowid LIMIT 1",
            [who, fold(self.config.alias_action), *subject_params, *object_params],
        ).fetchone()

    def _check_interval(self, from_key: str | None, to_key: str | None) -> None:
        if from_key is not None and to_key is not None and to_key < from_key:
            raise ValidationError("valid_to must not be before valid_from.")

    def _record(
        self,
        who: str,
        s_ref: Ref,
        action_text: str,
        o_ref: Ref,
        confidence: float | None,
        valid_from: str | None,
        valid_to: str | None,
        public: bool,
        attributes: dict[str, Any] | None,
        references: list[str] | None,
    ) -> dict[str, Any]:
        cfg = self.config
        from_text, from_key = parse_when(valid_from) if valid_from is not None else (None, None)
        to_text, to_key = parse_when(valid_to, end=True) if valid_to is not None else (None, None)
        self._check_interval(from_key, to_key)
        return {
            "id": str(uuid7()),
            "subject": s_ref.name, "subject_f": s_ref.f, "subject_kind": s_ref.kind,
            "action": action_text, "action_f": fold(action_text),
            "object": o_ref.name, "object_f": o_ref.f, "object_kind": o_ref.kind,
            "confidence": check_confidence(1.0 if confidence is None else confidence),
            "valid_from": from_text, "valid_from_key": from_key, "valid_to": to_text, "valid_to_key": to_key,
            "public": int(bool(public)),
            "attributes": json.dumps(check_attributes(attributes, cfg)),
            "refs": json.dumps(check_references(references, cfg)),
            "created_by": who, "created_at": now_iso(),
        }  # fmt: skip

    def _untyped(self, conn: sqlite3.Connection, who: str, refs: list[Ref]) -> list[str]:
        """Entity names with no visible type fact of their own yet."""
        cfg = self.config
        vis, vparams = visible("all", who)
        missing: list[str] = []
        for ref in refs:
            if ref.kind in cfg.value_kinds or ref.kind == cfg.actor_kind or str(ref) in missing:
                continue
            clause, cparams = match_refs("subject", [ref])
            found = conn.execute(
                f"SELECT 1 FROM facts WHERE {vis} AND action_f = ? AND confidence > 0 AND {clause} LIMIT 1",  # nosec B608
                [*vparams, fold(cfg.type_action), *cparams],
            ).fetchone()
            if found is None:
                missing.append(str(ref))
        return missing
