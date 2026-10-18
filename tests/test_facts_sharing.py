"""Public facts, timeless facts and Is-a types for the facts tools."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import facts
from tests.test_facts import data_dir, search, signed_in  # noqa: F401  (data_dir is an autouse fixture)


async def put(client: Client, subject: str, object: str, action: str = "Is a", **extra) -> dict:  # noqa: A002
    args = {"subject": subject, "object": object, "action": action, **extra}
    return (await client.call_tool("add_fact", args)).structured_content


async def describe(client: Client, name: str, **extra) -> dict:
    return (await client.call_tool("describe_entity", {"name": name, **extra})).structured_content


def subjects(found: dict) -> set[str]:
    return {f["subject"] for f in found["facts"]}


class TestPublicFacts:
    async def test_private_by_default_and_public_shows_creator(self):
        async with signed_in("alice") as alice:
            private = await put(alice, "Mine", "Thing", "Has")
            public = await put(alice, "Shared", "Thing", "Has", public=True)
        assert private["public"] is False
        assert public["public"] is True
        assert public["created_by"] == "alice"

    async def test_scope_default_is_mine_and_others_public_needs_scope(self):
        async with signed_in("alice") as alice:
            await put(alice, "A-private", "x", "Has")
            await put(alice, "A-public", "x", "Has", public=True)
        async with signed_in("bob") as bob:
            await put(bob, "B-private", "x", "Has")
            await put(bob, "B-public", "x", "Has", public=True)
            assert subjects(await search(bob)) == {"B-private", "B-public"}
            assert subjects(await search(bob, scope="mine")) == {"B-private", "B-public"}
            assert subjects(await search(bob, scope="public")) == {"A-public", "B-public"}
            assert subjects(await search(bob, scope="all")) == {"A-public", "B-private", "B-public"}

    async def test_no_scope_ever_exposes_another_users_private_fact(self):
        async with signed_in("alice") as alice:
            secret = await put(alice, "Secret", "x", "Has")
            await put(alice, "Secret", "Spy", "Is a")
        async with signed_in("bob") as bob:
            for scope in ("mine", "public", "all"):
                assert subjects(await search(bob, scope=scope)) == set()
                assert subjects(await search(bob, scope=scope, q="secret")) == set()
                assert subjects(await search(bob, scope=scope, subject_type="Spy")) == set()
                described = await describe(bob, "Secret", scope=scope)
                assert described["types"] == []
                assert described["facts_as_subject"] == 0
            with pytest.raises(ToolError, match="No fact with id"):
                await bob.call_tool("get_fact", {"id": secret["id"]})
            with pytest.raises(ToolError, match="No fact with id"):
                await bob.call_tool("update_fact", {"id": secret["id"], "public": True})
            with pytest.raises(ToolError, match="No fact with id"):
                await bob.call_tool("delete_fact", {"id": secret["id"]})

    async def test_public_fact_is_readable_but_not_editable_or_deletable_by_others(self):
        async with signed_in("alice") as alice:
            shared = await put(alice, "Shared", "x", "Has", public=True)
        async with signed_in("bob") as bob:
            seen = (await bob.call_tool("get_fact", {"id": shared["id"]})).structured_content
            assert seen["created_by"] == "alice"
            assert seen["public"] is True
            with pytest.raises(ToolError, match="only its creator"):
                await bob.call_tool("update_fact", {"id": shared["id"], "subject": "hijacked"})
            with pytest.raises(ToolError, match="only its creator"):
                await bob.call_tool("update_fact", {"id": shared["id"], "public": False})
            with pytest.raises(ToolError, match="only its creator"):
                await bob.call_tool("delete_fact", {"id": shared["id"]})
        async with signed_in("alice") as alice:
            intact = (await alice.call_tool("get_fact", {"id": shared["id"]})).structured_content
        assert intact["subject"] == "Shared"

    async def test_creator_can_unpublish(self):
        async with signed_in("alice") as alice:
            shared = await put(alice, "Shared", "x", "Has", public=True)
            updated = (await alice.call_tool("update_fact", {"id": shared["id"], "public": False})).structured_content
        assert updated["public"] is False
        async with signed_in("bob") as bob:
            assert subjects(await search(bob, scope="public")) == set()
            with pytest.raises(ToolError, match="No fact with id"):
                await bob.call_tool("get_fact", {"id": shared["id"]})

    async def test_creator_can_publish_later(self):
        async with signed_in("alice") as alice:
            later = await put(alice, "Later", "x", "Has")
            await alice.call_tool("update_fact", {"id": later["id"], "public": True})
        async with signed_in("bob") as bob:
            assert subjects(await search(bob, scope="public")) == {"Later"}

    async def test_bad_scope_is_rejected(self):
        async with signed_in("alice") as alice:
            with pytest.raises(ToolError):
                await search(alice, scope="everyone")


class TestTimelessFacts:
    async def test_time_is_optional_and_stays_null(self):
        async with signed_in("alice") as client:
            timeless = await put(client, "Sky", "Blue", "Is")
            fetched = (await client.call_tool("get_fact", {"id": timeless["id"]})).structured_content
        assert timeless["time"] is None
        assert fetched["time"] is None

    async def test_time_still_strict_when_given(self):
        async with signed_in("alice") as client:
            with pytest.raises(ToolError, match="strict ISO 8601"):
                await put(client, "Sky", "Blue", "Is", time="whenever")

    async def test_ranges_exclude_timeless_facts_but_exact_time_still_works(self):
        async with signed_in("alice") as client:
            await put(client, "timeless", "x", "Has")
            await put(client, "dated", "x", "Has", time="2026-05-01")
            assert subjects(await search(client, time_from="2000")) == {"dated"}
            assert subjects(await search(client, time_to="2100")) == {"dated"}
            assert subjects(await search(client, time="2026-05-01")) == {"dated"}
            assert subjects(await search(client)) == {"timeless", "dated"}

    async def test_a_time_can_be_added_to_a_timeless_fact(self):
        async with signed_in("alice") as client:
            timeless = await put(client, "Sky", "Blue", "Is")
            updated = (await client.call_tool("update_fact", {"id": timeless["id"], "time": "2026"})).structured_content
        assert updated["time"] == "2026"


class TestIsA:
    async def test_action_is_case_and_whitespace_folded(self):
        async with signed_in("alice") as client:
            await put(client, "Szilvia Mandic", "Person", "Is a")
            await put(client, "Rex", "Dog", " is   A ")
            assert subjects(await search(client, action="IS A")) == {"Szilvia Mandic", "Rex"}
            assert (await describe(client, "Rex"))["types"] == ["Dog"]

    async def test_describe_entity_direct_inherited_and_counts(self):
        async with signed_in("alice") as client:
            await put(client, "Szilvia Mandic", "Person")
            await put(client, "Person", "Agent")
            await put(client, "Agent", "Thing")
            await put(client, "Szilvia Mandic", "Birthday", "Has")
            await put(client, "Fan Club", "Szilvia Mandic", "Admires")
            described = await describe(client, "szilvia mandic")
        assert described["name"] == "szilvia mandic"
        assert described["types"] == ["Person"]
        assert described["inherited_types"] == ["Agent", "Thing"]
        assert described["facts_as_subject"] == 2
        assert described["facts_as_object"] == 1

    async def test_describe_entity_survives_cycles_and_caps_depth(self):
        async with signed_in("alice") as client:
            await put(client, "A", "B")
            await put(client, "B", "C")
            await put(client, "C", "A")
            cyclic = await describe(client, "A")
            for step in range(15):
                await put(client, f"L{step}", f"L{step + 1}")
            chain = await describe(client, "L0")
        assert cyclic["types"] == ["B"]
        assert cyclic["inherited_types"] == ["C"]
        assert len(chain["types"]) + len(chain["inherited_types"]) == facts.MAX_TYPE_DEPTH

    async def test_describe_entity_respects_scope(self):
        async with signed_in("alice") as alice:
            await put(alice, "Birthday", "Annual event", public=True)
            await put(alice, "Birthday", "Private note")
        async with signed_in("bob") as bob:
            await put(bob, "Birthday", "Bob's idea")
            assert (await describe(bob, "Birthday"))["types"] == ["Bob's idea"]
            assert (await describe(bob, "Birthday", scope="public"))["types"] == ["Annual event"]
            assert (await describe(bob, "Birthday", scope="all"))["types"] == ["Annual event", "Bob's idea"]

    async def test_subject_type_and_object_type_filters_are_transitive(self):
        async with signed_in("alice") as client:
            await put(client, "Szilvia Mandic", "Person")
            await put(client, "Person", "Agent")
            await put(client, "Birthday", "Annual event")
            await put(client, "Szilvia Mandic", "Birthday", "Has")
            await put(client, "Rex", "Dog")
            await put(client, "Rex", "Bone", "Has")
            assert subjects(await search(client, subject_type="Person", action="Has")) == {"Szilvia Mandic"}
            assert subjects(await search(client, subject_type="agent", action="Has")) == {"Szilvia Mandic"}
            assert subjects(await search(client, object_type="Annual event")) == {"Szilvia Mandic"}
            both = await search(client, subject_type="Person", object_type="Annual event")
            assert subjects(both) == {"Szilvia Mandic"}
            assert subjects(await search(client, subject_type="Cat")) == set()

    async def test_type_filters_survive_cycles(self):
        async with signed_in("alice") as client:
            await put(client, "A", "B")
            await put(client, "B", "A")
            await put(client, "A", "x", "Has")
            assert subjects(await search(client, subject_type="B", action="Has")) == {"A"}

    async def test_type_filters_respect_scope(self):
        async with signed_in("alice") as alice:
            await put(alice, "Birthday", "Annual event", public=True)
            await put(alice, "Wedding", "Annual event")
            await put(alice, "Birthday", "Cake", "Has", public=True)
            await put(alice, "Wedding", "Cake", "Has", public=True)
        async with signed_in("bob") as bob:
            public = await search(bob, scope="public", subject_type="Annual event", action="Has")
            assert subjects(public) == {"Birthday"}
            assert subjects(await search(bob, scope="all", subject_type="Annual event", action="Has")) == {"Birthday"}
            assert subjects(await search(bob, scope="mine", subject_type="Annual event")) == set()

    async def test_untyped_hint(self):
        async with signed_in("alice") as client:
            first = await put(client, "Szilvia Mandic", "Birthday", "Has")
            await put(client, "Szilvia Mandic", "Person")
            second = await put(client, "Szilvia Mandic", "Pie", "Likes")
            type_fact = await put(client, "Pie", "Food")
        async with signed_in("bob") as bob:
            await put(bob, "Birthday", "Annual event", public=True)
            third = await put(bob, "Szilvia Mandic", "Birthday", "Has")
        assert first["untyped"] == ["Szilvia Mandic", "Birthday"]
        assert second["untyped"] == ["Pie"]
        assert "untyped" not in type_fact
        assert third["untyped"] == ["Szilvia Mandic"]

    async def test_untyped_hint_ignores_another_users_private_types(self):
        async with signed_in("alice") as alice:
            await put(alice, "Szilvia Mandic", "Person")
        async with signed_in("bob") as bob:
            added = await put(bob, "Szilvia Mandic", "Birthday", "Has")
        assert "Szilvia Mandic" in added["untyped"]
