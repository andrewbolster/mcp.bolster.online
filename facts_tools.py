"""MCP adapter for the fact store: thin tool wrappers over ``factstore``.

All behaviour lives in the ``factstore`` package, which knows nothing about MCP. This module only supplies the
actor (the verified GitHub login from the token), the database location, and turns engine errors into tool errors.
"""

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from mcp.types import ToolAnnotations

from factstore import FactsError, FactStore
from factstore.config import Config
from factstore.values import WHEN_FORMATS

Scope = Literal["mine", "public", "all"]
CFG = Config()
_stores: dict[Path, FactStore] = {}


def data_dir() -> Path:
    """Where the database lives: ``MCP_DATA_DIR`` if set, otherwise ``data/`` next to the app (git-ignored)."""
    return Path(os.environ.get("MCP_DATA_DIR") or Path(__file__).resolve().parent / "data")


def get_store() -> FactStore:
    path = data_dir() / "facts.sqlite3"
    if path not in _stores:
        _stores[path] = FactStore(path, CFG)
    return _stores[path]


def _login() -> str:
    token = get_access_token()
    login = token.claims.get("login") if token else None
    if not login:
        raise ToolError("Not authenticated: sign in at /auth/mcp to use facts.")
    return str(login)


async def _run(call: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run an engine call off the event loop, mapping engine errors to tool errors."""
    try:
        return await asyncio.to_thread(call, *args, **kwargs)
    except FactsError as error:
        raise ToolError(str(error)) from error


def register_fact_tools(server: FastMCP) -> None:
    """Register the fact tools on ``server`` (the authenticated server only)."""

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def add_fact(
        subject: Annotated[str, "Who or what the fact is about, e.g. 'Ada Example'. 'me' means you."],
        action: Annotated[str, "The relationship or attribute, e.g. 'Has birthday', 'Partner', 'Is a'"],
        object: Annotated[str, "The other entity or the value, e.g. 'person:Bo Sample' or 'date:1988-05-17'"],  # noqa: A002
        confidence: Annotated[float, "How sure, from -1.0 (known false) to 1.0 (certain); default 1.0"] = 1.0,
        valid_from: Annotated[str | None, f"When it became true (optional): {WHEN_FORMATS}"] = None,
        valid_to: Annotated[
            str | None, "When it stopped being true (optional, same formats; inclusive of the period)"
        ] = None,
        public: Annotated[bool, "Let every authenticated user read this fact (default false: private)"] = False,
        attributes: Annotated[dict[str, Any] | None, "Optional extra key/value details, up to 4 KB"] = None,
        references: Annotated[list[str] | None, "Sources or links supporting the fact"] = None,
        check_types: Annotated[
            bool, "Also list in the reply the entity names that have no 'Is a' fact yet (default false)"
        ] = False,
    ) -> dict[str, Any]:
        """Remember a fact: (subject, action, object) with optional validity, confidence and attributes.

        Names may carry a kind prefix: person:, place:, org:, date:, number:, text: (other prefixes stay part of
        the name). Dates as values use date: with YYYY, YYYY-MM, YYYY-MM-DD or --MM-DD (no known year).
        Aliases are resolved, so using any known alias stores the fact under the entity's canonical name; an
        ambiguous alias is an error that lists the candidates. 'me' needs set_self first.
        Facts are private unless public=true; only you can change or delete your own.
        Example: subject='me', action='Has birthday', object='date:1988-05-17'.
        Example: subject='me', action='Partner', object='person:Bo Sample', valid_from='2012', valid_to='2015'.
        With check_types=true the reply lists `untyped` entity names that have no 'Is a' fact yet.
        The reply carries subject_ref and object_ref: the names with their kind prefix, safe to pass back in.
        To write many facts at once use add_facts.
        """
        return await _run(
            get_store().add_fact,
            _login(), subject, action, object,
            confidence=confidence, valid_from=valid_from, valid_to=valid_to, public=public,
            attributes=attributes, references=references, check_types=check_types,
        )  # fmt: skip

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def add_facts(
        facts: Annotated[
            list[dict[str, Any]],
            "Up to 100 facts, each an object with subject, action and object, and optionally confidence, valid_from, "
            "valid_to, public, attributes and references (the same meaning as in add_fact)",
        ],
    ) -> dict[str, Any]:
        """Write many facts in one transaction: every fact is stored, or none is. Returns {count, ids} in input order.

        Facts are written in order, so a later fact can use an alias added earlier in the same call. A bad fact
        fails the whole call with an error that names its position ("Item 2: ...").
        Example: facts=[{"subject": "A. Example", "action": "Alias of", "object": "person:Ada Example"},
        {"subject": "A. Example", "action": "Likes", "object": "Tea"}].
        """
        return await _run(get_store().add_many, _login(), facts)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_fact(id: Annotated[str, "The fact's id, as returned by add_fact or search_facts"]) -> dict[str, Any]:  # noqa: A002
        """Read one fact by id: yours, a public one, or one you have been asked to review.

        The reply includes `reviews` (newest first): on your own fact, everyone's outcome (reviewer, outcome, note,
        time); on anyone else's, only your own entries. Example: id='0198f6d2-7c3e-7a41-9b0e-2f5d8a1c4e90'.
        """
        return await _run(get_store().get_fact, _login(), id)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def search_facts(
        scope: Annotated[
            Scope,
            "'mine' (default): facts you created. 'public': public facts from anyone. "
            "'all': yours, public, and facts you were asked to review.",
        ] = "mine",
        subject: Annotated[str | None, "Facts about this entity; any of its aliases works, and 'me' means you"] = None,
        action: Annotated[str | None, "Match this action (case-insensitive, exact)"] = None,
        object: Annotated[str | None, "Facts whose object is this entity or value (aliases resolved)"] = None,  # noqa: A002
        subject_kind: Annotated[
            str | None, "Only subjects of this kind (person, place, org, date, number, text)"
        ] = None,
        object_kind: Annotated[str | None, "Only objects of this kind"] = None,
        subject_type: Annotated[str | None, "Only subjects that are an instance of this type (via 'Is a')"] = None,
        object_type: Annotated[str | None, "Only objects that are an instance of this type (via 'Is a')"] = None,
        min_confidence: Annotated[float | None, "Only facts with at least this confidence"] = None,
        include_negative: Annotated[bool, "Also return facts with confidence 0 or below (falsifications)"] = False,
        valid_at: Annotated[str | None, "Only facts valid at this instant; open-ended bounds count as valid"] = None,
        valid_from: Annotated[str | None, "Start of a validity window: facts whose period overlaps it"] = None,
        valid_to: Annotated[str | None, "End of the validity window (inclusive of its period)"] = None,
        valid_within: Annotated[
            bool, "With valid_from and/or valid_to: only facts whose period lies ENTIRELY inside the window"
        ] = False,
        has_period: Annotated[
            bool | None, "true: only facts with a valid_from or valid_to; false: only facts with neither"
        ] = None,
        q: Annotated[
            str | None,
            "Free text: every word must appear (any order, ignoring case and accents) in the subject, object, "
            "action, attribute names and values, or references",
        ] = None,
        attribute_key: Annotated[str | None, "Only facts that have this attribute"] = None,
        attribute_value: Annotated[str | None, "With attribute_key: the attribute must equal this"] = None,
        reviewed_before: Annotated[
            str | None, "Only facts whose last review was before this time (never-reviewed facts are excluded)"
        ] = None,
        include_never_reviewed: Annotated[
            bool, "With reviewed_before: also include never-reviewed facts, counting creation as the baseline"
        ] = False,
        reviewed: Annotated[
            bool | None, "true: only facts that have been reviewed; false: only those never reviewed"
        ] = None,
        created_since: Annotated[str | None, f"Only facts created at or after this time. {WHEN_FORMATS}"] = None,
        created_before: Annotated[str | None, "Only facts created before this time"] = None,
        updated_since: Annotated[str | None, "Only facts edited at or after this time (never-edited ones: no)"] = None,
        changed_since: Annotated[str | None, "Only facts created OR edited at or after this time"] = None,
        object_from: Annotated[
            str | None, "Only facts whose object is a date on or after this (YYYY, YYYY-MM or YYYY-MM-DD)"
        ] = None,
        object_to: Annotated[str | None, "Only facts whose object is a date on or before this (inclusive)"] = None,
        object_within: Annotated[
            bool, "With object_from/object_to: a coarse date (2026) must lie ENTIRELY inside the window"
        ] = False,
        order_by: Annotated[
            Literal["created_at", "updated_at", "confidence", "valid_from", "valid_to", "object", "group_count"] | None,
            "Sort the page by this (default newest created first); facts with no value come last. "
            "group_count only with group_by.",
        ] = None,
        order: Annotated[Literal["asc", "desc"] | None, "Sort direction (default desc)"] = None,
        group_by: Annotated[
            Literal["subject", "action", "object", "subject_kind", "object_kind"] | None,
            "Return one fact per group, with group_count",
        ] = None,
        pick: Annotated[
            Literal["latest", "oldest", "highest_confidence"] | None,
            "With group_by: which fact represents each group (default latest)",
        ] = None,
        pick_by: Annotated[
            Literal["created_at", "object", "valid_from", "valid_to"] | None,
            "With group_by and pick latest/oldest: what to compare (default created_at; object = the date the "
            "object holds)",
        ] = None,
        count_only: Annotated[
            bool, "Return only counts: the number of matches, and with group_by each group's size (largest first)"
        ] = False,
        fields: Annotated[
            list[str] | None, "Return only these fields (e.g. ['subject_ref','action','object_ref'])"
        ] = None,
        format: Annotated[  # noqa: A002
            Literal["full", "compact"],
            "'compact' returns columns + rows (lists) without attributes/references unless named in fields: "
            "several times smaller",
        ] = "full",
        limit: Annotated[int, "Maximum facts to return (default 50, max 200)"] = CFG.default_limit,
        offset: Annotated[int, "How many matches to skip, to read the next page (default 0)"] = 0,
    ) -> dict[str, Any]:
        """Search facts, newest first, one page at a time. Alias facts are hidden unless action='Alias of'.

        Returns {count, total, offset, limit, truncated, facts}: `total` is every match, and `truncated` is true
        when more follow this page (repeat with offset=offset+count). A kind prefix on a name ('org:PPS') or
        subject_kind/object_kind settles an alias that several entities answer to.
        Only positive-confidence facts are returned unless include_negative=true.
        valid_from/valid_to match facts whose period OVERLAPS the window (facts with no period or an open bound
        match too); valid_within=true keeps only facts that fit entirely inside it, and has_period=true drops
        facts with no period. A reply may carry `warnings`, e.g. about a name like 'claim:Foo' whose prefix is not
        a configured kind and so is matched as literal text.
        To keep replies small, use format='compact' (columns + rows) and/or fields=[...].
        group_by returns one fact per group (chosen by pick/pick_by) with `group_count`; `total` then counts
        groups. count_only=true returns just counts ({total}, or with group_by each group's size).
        Example (a partner's facts): first search subject='me', action='Partner' to find the entity, then
        search subject=<that entity>.
        Example (who was my partner in 2013): subject='me', action='Partner', valid_at='2013-05-17'.
        Example (facts that start and end within 2020-2023): valid_from='2020', valid_to='2023', valid_within=true.
        Example (what changed since 1 Nov): changed_since='2026-11-01', format='compact'.
        Example (releases published in Nov 2026): action='Published on', object_from='2026-11', object_to='2026-11'.
        Example (latest period per dataset): action='Refers to', group_by='object', pick='latest', pick_by='valid_to'.
        """
        return await _run(
            get_store().search_facts,
            _login(),
            scope=scope, subject=subject, action=action, object=object, subject_kind=subject_kind,
            object_kind=object_kind, subject_type=subject_type, object_type=object_type,
            min_confidence=min_confidence, include_negative=include_negative, valid_at=valid_at,
            valid_from=valid_from, valid_to=valid_to, valid_within=valid_within, has_period=has_period, q=q,
            attribute_key=attribute_key, attribute_value=attribute_value, reviewed_before=reviewed_before,
            include_never_reviewed=include_never_reviewed, reviewed=reviewed,
            created_since=created_since, created_before=created_before, updated_since=updated_since,
            changed_since=changed_since, object_from=object_from, object_to=object_to,
            object_within=object_within, order_by=order_by, order=order, group_by=group_by, pick=pick,
            pick_by=pick_by, count_only=count_only, fields=fields, format=format, limit=limit, offset=offset,
        )  # fmt: skip

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True))
    async def update_fact(
        id: Annotated[str, "The id of the fact to change (must be one you created)"],  # noqa: A002
        subject: Annotated[str | None, "New subject"] = None,
        action: Annotated[str | None, "New action"] = None,
        object: Annotated[str | None, "New object"] = None,  # noqa: A002
        confidence: Annotated[float | None, "New confidence, -1.0 to 1.0"] = None,
        valid_from: Annotated[str | None, "New start of validity; '' clears it"] = None,
        valid_to: Annotated[str | None, "New end of validity; '' clears it"] = None,
        public: Annotated[bool | None, "true to publish, false to make private again"] = None,
        attributes: Annotated[dict[str, Any] | None, "Replacement attributes; {} clears them"] = None,
        references: Annotated[list[str] | None, "Replacement references; [] clears them"] = None,
    ) -> dict[str, Any]:
        """Change fields of one of your facts. Only the fields you supply change. Returns the updated fact.

        Only the creator can update a fact, including public ones. To record that a fact stopped being true, set
        valid_to instead of deleting it. Example: id='0198f6d2-…', valid_to='2015-06'.
        """
        changes: dict[str, Any] = {
            name: value
            for name, value in (
                ("subject", subject), ("action", action), ("object", object), ("confidence", confidence),
                ("public", public), ("attributes", attributes), ("references", references),
            )
            if value is not None
        }  # fmt: skip
        for name, value in (("valid_from", valid_from), ("valid_to", valid_to)):
            if value is not None:
                changes[name] = value or None
        return await _run(get_store().update_fact, _login(), id, **changes)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    async def delete_fact(
        id: Annotated[str, "The id of the fact to delete (must be one you created)"],
    ) -> dict[str, Any]:  # noqa: A002
        """Permanently delete one of your facts, including its review requests and reviews.

        Use this for facts that were wrong. For facts that are no longer true, set valid_to with update_fact.
        """
        return await _run(get_store().delete_fact, _login(), id)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def describe_entity(
        name: Annotated[str, "The entity to describe, e.g. 'Ada Example' or 'me'"],
        scope: Annotated[Scope, "'mine' (default), 'public' or 'all', as for search_facts"] = "mine",
    ) -> dict[str, Any]:
        """Describe an entity: canonical name, `kind` and `ref` (the name as it is written in the facts, with its
        kind prefix), aliases, types (from 'Is a' facts, direct and inherited), how many visible facts mention it
        as subject and as object, and when any of them was last reviewed. `exists` is true only for a real entity:
        it is false for a name no visible fact mentions, and for one that only ever appears as a value such as
        'text:Quarterly' (`mentioned_as_value_in` counts those uses). A name stored under several kinds is not
        guessed: it comes back as typed with a warning listing the kinds.

        Example: name='me'.
        """
        return await _run(get_store().describe_entity, _login(), name, scope=scope)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def add_alias(
        alias: Annotated[str, "Another name for the entity, e.g. 'bolster'"],
        canonical: Annotated[str, "The entity's canonical name, e.g. 'person:Ada Example'"],
        public: Annotated[bool, "Let every authenticated user use this alias (default false: private)"] = False,
    ) -> dict[str, Any]:
        """Say that one name is another name for an entity. Stored as an ordinary fact with the action 'Alias of'.

        Searches and new facts that use the alias then resolve to the canonical entity. Cycles and aliasing a name
        to itself are refused. Example: alias='A. Example', canonical='person:Ada Example'.
        """
        return await _run(get_store().add_alias, _login(), alias, canonical, public=public)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True))
    async def set_self(name: Annotated[str, "Who you are, e.g. 'person:Ada Example'"]) -> dict[str, Any]:
        """Say which entity you are, so that 'me' and 'self' mean it in every tool. Replaces an earlier binding.

        Example: name='person:Ada Example'.
        """
        return await _run(get_store().set_self, _login(), name)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def relationships_between(
        a: Annotated[str, "The first entity (aliases and 'me' work)"],
        b: Annotated[str, "The second entity"],
        scope: Annotated[Scope, "'mine' (default), 'public' or 'all'"] = "mine",
        max_depth: Annotated[int, "1: facts directly linking them. 2: also paths through one intermediary entity"] = 1,
        fields: Annotated[
            list[str] | None, "Return only these fact fields ('direction' applies to direct facts)"
        ] = None,
        format: Annotated[  # noqa: A002
            Literal["full", "compact"], "'compact': tables of lists instead of fact dicts (see the reply notes)"
        ] = "full",
    ) -> dict[str, Any]:
        """The facts connecting two entities, in either direction.

        Returns {a, b, direct, direct_truncated, indirect, indirect_truncated}. Each direct fact carries direction
        'a_to_b' or 'b_to_a'. With max_depth=2, `indirect` lists paths a - via - b. The truncated flags are true when
        more exist than were returned (200 direct facts, 100 paths).
        With format='compact', `direct` is {columns, rows} and `indirect` is {fact_columns, columns: ['via','facts'],
        rows}, each path's facts being rows of fact_columns.
        Example: a='me', b='person:Bo Sample'.
        """
        return await _run(
            get_store().relationships_between,
            _login(), a, b,
            scope=scope, max_depth=max_depth, fields=fields, format=format,
        )  # fmt: skip

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def dependents(
        entity: Annotated[
            str, "The entity to start from (aliases and 'me' work), e.g. 'source:Labour Market Statistics'"
        ],
        via: Annotated[
            list[str] | None, "Only follow facts with these actions (default: any action except aliases)"
        ] = None,
        depth: Annotated[int, "How many hops to follow, 1 to 3 (default 1)"] = 1,
        direction: Annotated[
            Literal["in", "out", "both"],
            "'in' (default): facts pointing AT the entity (what depends on it). 'out': facts starting from it. "
            "'both': either way.",
        ] = "in",
        scope: Annotated[Scope, "'mine' (default), 'public' or 'all'"] = "mine",
        include_negative: Annotated[bool, "Also follow facts with confidence 0 or below"] = False,
        result_kind: Annotated[
            str | None, "Only return entities of this kind (the walk still passes through the others)"
        ] = None,
        fields: Annotated[
            list[str] | None,
            "Return only these fields: entity, name, kind, depth, via, fact_ids, confidence, valid_from, valid_to, "
            "attributes, references (the last four describe the last fact on the path)",
        ] = None,
        format: Annotated[  # noqa: A002
            Literal["full", "compact"], "'compact': columns + rows (entity, depth, via, fact_ids unless fields given)"
        ] = "full",
        limit: Annotated[int, "Maximum entities to return (default 50, max 200)"] = CFG.default_limit,
        offset: Annotated[int, "How many entities to skip, to read the next page (default 0)"] = 0,
    ) -> dict[str, Any]:
        """The entities connected to an entity by chains of facts, nearest first, each reported once by its shortest
        path: what depends on a dataset (direction 'in', the default), what a fact points at ('out'), or both.

        Returns {start, direction, depth, via, capped, count, total, offset, limit, truncated, dependents}. Each
        dependent has its `entity` (with kind prefix), `depth`, the `via` actions along the path and the `fact_ids`
        it passes through. Values (dates, numbers, text) are not entities and are never returned. `capped` is true
        if the walk stopped at 1000 entities. After the first hop entities are matched by their stored name and kind.
        Example (claims derived from a dataset): entity='source:Labour Market Statistics', via=['Derived from'].
        Example (claims affected by an event): entity='event:<name>', via=['Affects','Derived from'], depth=2,
        direction='both', result_kind='claim'.
        """
        return await _run(
            get_store().dependents,
            _login(), entity,
            via=via, depth=depth, direction=direction, scope=scope, include_negative=include_negative,
            result_kind=result_kind, fields=fields, format=format, limit=limit, offset=offset,
        )  # fmt: skip

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def request_review(
        id: Annotated[str, "The fact to be reviewed (must be one you created)"],  # noqa: A002
        reviewer: Annotated[str, "The login of the person to ask"],
        note: Annotated[str | None, "Optional message for the reviewer"] = None,
    ) -> dict[str, Any]:
        """Ask another user to review one of your facts. While the request is open they can read that one fact.

        Example: id='0198f6d2-…', reviewer='bob'.
        """
        return await _run(get_store().request_review, _login(), id, reviewer, note)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def mark_reviewed(
        id: Annotated[str, "The fact to review (yours, public, or one you were asked to review)"],  # noqa: A002
        outcome: Annotated[Literal["confirmed", "disputed", "unsure"], "Your verdict"],
        note: Annotated[str | None, "Optional comment"] = None,
        confidence: Annotated[
            float | None,
            "Disputes only: how strongly you dispute it, with the opposite sign of the disputed fact "
            "(default -1.0 for a believed fact, +1.0 for a falsification)",
        ] = None,
    ) -> dict[str, Any]:
        """Record a review. 'confirmed' stamps the fact as reviewed now. 'disputed' creates your own private fact on
        the same triple with the opposite sign of the disputed fact (-1.0 for a believed fact, +1.0 for one already
        marked false, or the graded `confidence` you state) that references the disputed one; the disputed fact is
        untouched, and its owner sees only that a dispute exists. You cannot dispute your own fact: use update_fact
        (lower its confidence, or set valid_to). Any outcome closes your open review requests on the fact.

        Example: id='0198f6d2-…', outcome='confirmed'. Example: outcome='disputed', confidence=-0.4.
        """
        return await _run(get_store().mark_reviewed, _login(), id, outcome, note, confidence)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def review_outcomes(
        since: Annotated[str | None, f"Only entries at or after this time. {WHEN_FORMATS}"] = None,
        limit: Annotated[int, "Maximum entries to return (default 50, max 200)"] = CFG.default_limit,
        offset: Annotated[int, "How many entries to skip, to read the next page (default 0)"] = 0,
        role: Annotated[
            Literal["owner", "reviewer", "all"],
            "'owner' (default): what people said about YOUR facts. 'reviewer': the reviews YOU wrote on any fact, "
            "confirmed ones included. 'all': both.",
        ] = "owner",
        fields: Annotated[
            list[str] | None,
            "Return only these fields: review_id, fact_id, role, reviewer, outcome, note, at, subject_ref, action, "
            "object_ref",
        ] = None,
        format: Annotated[  # noqa: A002
            Literal["full", "compact"], "'compact': columns + rows, without review_id and note unless named in fields"
        ] = "full",
    ) -> dict[str, Any]:
        """Recent reviews (confirmed, disputed, unsure), newest first.

        Returns {count, total, offset, limit, truncated, outcomes}; each entry has the fact (id, and subject_ref,
        action, object_ref while you can still read it), the reviewer, the outcome, the note, the time and your
        `role` in it ('owner' or 'reviewer'). On someone else's fact you see only your own entry. A dispute shows as
        'disputed': the reviewer's own counter-fact stays private to them.
        Example: since='2026-01-01'. Example: role='reviewer' to list what you reviewed.
        """
        return await _run(get_store().review_outcomes, _login(), since, limit, offset, role, fields, format)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def pending_reviews(
        direction: Annotated[
            Literal["received", "sent"], "'received': asked of you (default). 'sent': asked by you"
        ] = "received",
        limit: Annotated[int, "Maximum requests to return (default 50, max 200)"] = CFG.default_limit,
        offset: Annotated[int, "How many requests to skip, to read the next page (default 0)"] = 0,
        fields: Annotated[
            list[str] | None,
            "Return only these fields, flattening request and fact into one row: id, fact_id, requested_by, "
            "requested_of, note, requested_at, status, resolved_at, subject_ref, action, object_ref, confidence, "
            "valid_from, valid_to",
        ] = None,
        format: Annotated[  # noqa: A002
            Literal["full", "compact"], "'compact': columns + rows, one flat row per request"
        ] = "full",
    ) -> dict[str, Any]:
        """List open review requests, oldest first, each with its fact.

        Returns {count, total, offset, limit, truncated, requests}.
        """
        return await _run(get_store().pending_reviews, _login(), direction, limit, offset, fields=fields, format=format)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def due_for_review(
        before: Annotated[
            str | None, f"Facts last reviewed (or created) before this time; default 90 days ago. {WHEN_FORMATS}"
        ] = None,
        limit: Annotated[int, "Maximum facts to return (default 50, max 200)"] = CFG.default_limit,
        offset: Annotated[int, "How many facts to skip, to read the next page (default 0)"] = 0,
        action: Annotated[str | None, "Only facts with this action (case-insensitive, exact)"] = None,
        subject: Annotated[str | None, "Only facts about this entity (aliases resolved; 'me' works)"] = None,
        object_kind: Annotated[str | None, "Only facts whose object is of this kind"] = None,
        created_before: Annotated[str | None, f"Only facts created before this time. {WHEN_FORMATS}"] = None,
        order: Annotated[
            Literal["oldest_reviewed", "lowest_confidence", "newest"],
            "'oldest_reviewed' (default), 'lowest_confidence' (then oldest), or 'newest' (by creation)",
        ] = "oldest_reviewed",
        reviewed: Annotated[
            bool | None, "true: only facts that have been reviewed before; false: only facts never reviewed"
        ] = None,
        include_never_reviewed: Annotated[
            bool, "false: skip never-reviewed facts, so only facts whose last review is old are listed (default true)"
        ] = True,
        created_since: Annotated[str | None, f"Only facts created at or after this time. {WHEN_FORMATS}"] = None,
        updated_since: Annotated[str | None, "Only facts edited at or after this time"] = None,
        fields: Annotated[list[str] | None, "Return only these fact fields"] = None,
        format: Annotated[  # noqa: A002
            Literal["full", "compact"], "'compact': columns + rows without attributes/references"
        ] = "full",
    ) -> dict[str, Any]:
        """Your own facts that have not been reviewed since `before`.

        Returns {before, order, count, total, offset, limit, truncated, facts}. A fact that was never reviewed counts
        as reviewed when it was created, unless include_never_reviewed is false. Example: before='2026-01-01',
        action='Has geography', order='newest'; reviewed=false lists only facts nobody has reviewed yet.
        """
        return await _run(
            get_store().due_for_review,
            _login(), before, limit,
            offset=offset, action=action, subject=subject, object_kind=object_kind,
            created_before=created_before, order=order, reviewed=reviewed,
            include_never_reviewed=include_never_reviewed,
            created_since=created_since, updated_since=updated_since, fields=fields, format=format,
        )  # fmt: skip
