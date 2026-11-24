"""The query-ergonomics features through the MCP adapter: compact and projected results, time and date filters,
grouping and counts, and the ``dependents`` tool."""

import json

import pytest
from fastmcp.exceptions import ToolError

from tests.test_facts_tools import call, data_dir, signed_in  # noqa: F401  (data_dir is an autouse fixture)


async def seed(client):
    for subject, source, end in [
        ("Release A", "source:X", "2026-03"),
        ("Release B", "source:X", "2026-06"),
        ("Release C", "source:Y", "2026-01"),
    ]:
        await call(client, "add_fact", subject=subject, action="Refers to", object=source, valid_to=end)
    for subject, when in [
        ("Release A", "date:2026-11-03"),
        ("Release B", "date:2026-11-17"),
        ("Release C", "date:2025-12-31"),
    ]:
        await call(client, "add_fact", subject=subject, action="Published on", object=when)
    await call(client, "add_fact", subject="Claim 1", action="Derived from", object="source:X")
    await call(client, "add_fact", subject="Claim 2", action="Derived from", object="Claim 1")


class TestSearchThroughTheTool:
    async def test_compact_and_projected_results(self):
        async with signed_in("alice") as client:
            await seed(client)
            compact = await call(client, "search_facts", action="Refers to", format="compact", limit=2)
            assert compact["columns"][:4] == ["id", "subject_ref", "action", "object_ref"]
            assert (compact["count"], compact["total"], compact["truncated"]) == (2, 3, True)
            trimmed = await call(client, "search_facts", action="Refers to", fields=["subject_ref", "valid_to"])
            assert {tuple(f.items()) for f in trimmed["facts"]} == {
                (("subject_ref", "Release A"), ("valid_to", "2026-03")),
                (("subject_ref", "Release B"), ("valid_to", "2026-06")),
                (("subject_ref", "Release C"), ("valid_to", "2026-01")),
            }

    async def test_an_unknown_field_is_a_tool_error_that_lists_the_valid_ones(self):
        async with signed_in("alice") as client:
            with pytest.raises(ToolError, match="Unknown field 'colour'.*Valid fields: id, subject"):
                await call(client, "search_facts", fields=["colour"])
            with pytest.raises(ToolError):
                await call(client, "search_facts", format="table")  # not one of full, compact

    async def test_time_and_date_filters_ordering_and_grouping(self):
        async with signed_in("alice") as client:
            await seed(client)
            nov = await call(
                client, "search_facts", action="Published on", object_from="2026-11", object_to="2026-11",
                order_by="object", order="asc", fields=["subject_ref", "object"],
            )  # fmt: skip
            assert [(f["subject_ref"], f["object"]) for f in nov["facts"]] == [
                ("Release A", "2026-11-03"), ("Release B", "2026-11-17"),
            ]  # fmt: skip
            recent = await call(client, "search_facts", created_since="2000", count_only=True)
            assert recent == {"total": 8}
            latest = await call(
                client, "search_facts", action="Refers to", group_by="object", pick="latest", pick_by="valid_to",
                fields=["object_ref", "subject_ref", "group_count"], order_by="group_count", order="desc",
            )  # fmt: skip
            assert latest["facts"] == [
                {"object_ref": "source:X", "subject_ref": "Release B", "group_count": 2},
                {"object_ref": "source:Y", "subject_ref": "Release C", "group_count": 1},
            ]
            counts = await call(client, "search_facts", group_by="action", count_only=True, format="compact")
            assert {tuple(row) for row in counts["rows"]} == {
                ("Published on", 3),
                ("Refers to", 3),
                ("Derived from", 2),
            }
            assert (
                counts["rows"][-1] == ["Derived from", 2] and counts["facts_total"] == 8
            )  # largest first, ties by name

    async def test_bad_combinations_are_tool_errors(self):
        async with signed_in("alice") as client:
            with pytest.raises(ToolError, match="pick and pick_by need group_by"):
                await call(client, "search_facts", pick="latest")
            with pytest.raises(ToolError, match="object_within needs object_from"):
                await call(client, "search_facts", object_within=True)
            with pytest.raises(ToolError, match="Invalid time"):
                await call(client, "search_facts", created_since="last week")


class TestDependentsThroughTheTool:
    async def test_it_lists_what_points_at_an_entity(self):
        async with signed_in("alice") as client:
            await seed(client)
            found = await call(client, "dependents", entity="source:X", via=["Derived from"], depth=2)
            assert [(d["entity"], d["depth"]) for d in found["dependents"]] == [("Claim 1", 1), ("Claim 2", 2)]
            assert found["dependents"][1]["via"] == ["Derived from", "Derived from"]
            assert (found["start"], found["direction"], found["capped"]) == ("source:X", "in", False)

    async def test_compact_fields_and_directions(self):
        async with signed_in("alice") as client:
            await seed(client)
            compact = await call(client, "dependents", entity="Claim 2", direction="out", depth=2, format="compact")
            assert compact["columns"] == ["entity", "depth", "via", "fact_ids"]
            assert [row[:2] for row in compact["rows"]] == [["Claim 1", 1], ["source:X", 2]]
            both = await call(client, "dependents", entity="Claim 1", direction="both", fields=["entity", "confidence"])
            assert {d["entity"] for d in both["dependents"]} == {"Claim 2", "source:X"}

    async def test_errors_say_what_is_valid_and_nothing_leaks_between_users(self):
        async with signed_in("alice") as client:
            await seed(client)
            with pytest.raises(ToolError, match="depth must be 1 to 3"):
                await call(client, "dependents", entity="source:X", depth=9)
            with pytest.raises(ToolError, match="is a value, not an entity"):
                await call(client, "dependents", entity="date:2026-11-03")
        async with signed_in("bob") as client:
            found = await call(client, "dependents", entity="source:X", depth=3, direction="both", scope="all")
            assert (found["total"], found["dependents"]) == (0, [])

    async def test_the_schema_offers_the_new_arguments(self):
        async with signed_in("alice") as client:
            tools = {t.name: t for t in await client.list_tools()}
        props = tools["dependents"].inputSchema["properties"]
        assert {"entity", "via", "depth", "direction", "scope", "result_kind", "fields", "format"} <= set(props)
        assert tools["dependents"].annotations.readOnlyHint is True
        search = tools["search_facts"].inputSchema["properties"]
        assert {
            "created_since",
            "object_from",
            "order_by",
            "group_by",
            "pick_by",
            "count_only",
            "fields",
            "format",
        } <= set(search)
        assert json.dumps(search["format"])  # an enum the client can show
