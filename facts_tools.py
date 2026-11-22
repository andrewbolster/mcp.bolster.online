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
    ) -> dict[str, Any]:
        """Remember a fact: (subject, action, object) with optional validity, confidence and attributes.

        Names may carry a kind prefix: person:, place:, org:, date:, number:, text: (other prefixes stay part of
        the name). Dates as values use date: with YYYY, YYYY-MM, YYYY-MM-DD or --MM-DD (no known year).
        Aliases are resolved, so using any known alias stores the fact under the entity's canonical name; an
        ambiguous alias is an error that lists the candidates. 'me' needs set_self first.
        Facts are private unless public=true; only you can change or delete your own.
        Example: subject='me', action='Has birthday', object='date:1988-05-17'.
        Example: subject='me', action='Partner', object='person:Bo Sample', valid_from='2012', valid_to='2015'.
        The reply lists `untyped` entity names that have no 'Is a' fact yet.
        """
        return await _run(
            get_store().add_fact,
            _login(), subject, action, object,
            confidence=confidence, valid_from=valid_from, valid_to=valid_to, public=public,
            attributes=attributes, references=references,
        )  # fmt: skip

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_fact(id: Annotated[str, "The fact's id, as returned by add_fact or search_facts"]) -> dict[str, Any]:  # noqa: A002
        """Read one fact by id: yours, a public one, or one you have been asked to review.

        Example: id='0198f6d2-7c3e-7a41-9b0e-2f5d8a1c4e90'.
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
        valid_from: Annotated[str | None, "With valid_to: only facts whose validity overlaps this range"] = None,
        valid_to: Annotated[str | None, "Upper end of the validity range to overlap"] = None,
        q: Annotated[str | None, "Free text matched within subject, object and action"] = None,
        attribute_key: Annotated[str | None, "Only facts that have this attribute"] = None,
        attribute_value: Annotated[str | None, "With attribute_key: the attribute must equal this"] = None,
        reviewed_before: Annotated[
            str | None, "Only facts last reviewed (or, if never, created) before this time"
        ] = None,
        limit: Annotated[int, "Maximum facts to return (default 50, max 200)"] = CFG.default_limit,
    ) -> dict[str, Any]:
        """Search facts, newest first. Returns {count, facts}. Alias facts are hidden unless action='Alias of'.

        Only positive-confidence facts are returned unless include_negative=true.
        Example (a partner's facts): first search subject='me', action='Partner' to find the entity, then
        search subject=<that entity>.
        Example (who was my partner in 2013): subject='me', action='Partner', valid_at='2013-05-17'.
        """
        return await _run(
            get_store().search_facts,
            _login(),
            scope=scope, subject=subject, action=action, object=object, subject_kind=subject_kind,
            object_kind=object_kind, subject_type=subject_type, object_type=object_type,
            min_confidence=min_confidence, include_negative=include_negative, valid_at=valid_at,
            valid_from=valid_from, valid_to=valid_to, q=q, attribute_key=attribute_key,
            attribute_value=attribute_value, reviewed_before=reviewed_before, limit=limit,
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
        """Describe an entity: canonical name, aliases, types (from 'Is a' facts, direct and inherited), how many
        visible facts mention it as subject and as object, and when any of them was last reviewed.

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
    ) -> dict[str, Any]:
        """The facts connecting two entities, in either direction. Returns {a, b, direct, indirect}.

        Each direct fact carries direction 'a_to_b' or 'b_to_a'. With max_depth=2, `indirect` lists paths a - via - b.
        Example: a='me', b='person:Bo Sample'.
        """
        return await _run(get_store().relationships_between, _login(), a, b, scope=scope, max_depth=max_depth)

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
    ) -> dict[str, Any]:
        """Record a review. 'confirmed' stamps the fact as reviewed now. 'disputed' by someone other than the owner
        creates your own fact with confidence -1 that references the disputed one (the owner's fact is untouched).
        Any outcome closes your open review requests on the fact.

        Example: id='0198f6d2-…', outcome='confirmed'.
        """
        return await _run(get_store().mark_reviewed, _login(), id, outcome, note)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def pending_reviews(
        direction: Annotated[
            Literal["received", "sent"], "'received': asked of you (default). 'sent': asked by you"
        ] = "received",
    ) -> dict[str, Any]:
        """List open review requests, each with its fact. Returns {count, requests}."""
        return await _run(get_store().pending_reviews, _login(), direction)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def due_for_review(
        before: Annotated[
            str | None, f"Facts last reviewed (or created) before this time; default 90 days ago. {WHEN_FORMATS}"
        ] = None,
        limit: Annotated[int, "Maximum facts to return (default 50, max 200)"] = CFG.default_limit,
    ) -> dict[str, Any]:
        """Your own facts that have not been reviewed since `before`, oldest first. Returns {before, count, facts}.

        A fact that was never reviewed counts as reviewed when it was created. Example: before='2026-01-01'.
        """
        return await _run(get_store().due_for_review, _login(), before, limit)
