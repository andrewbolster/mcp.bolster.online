"""The fixes for the defects the catalogue experiment found, through the tools an LLM client actually calls."""

import pytest
from fastmcp.exceptions import ToolError

from tests.test_facts_tools import call, signed_in


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """A fresh database per test, and three allowed logins so one fact can have two reviewers."""
    monkeypatch.setenv("MCP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "alice,bob,carol")


class TestKindsAndExistence:
    async def test_a_kind_prefix_settles_an_ambiguous_alias(self):
        async with signed_in("alice") as client:
            await call(client, "add_alias", alias="Sam", canonical="person:Sam Sample")
            await call(client, "add_alias", alias="Sam", canonical="org:Sam Corp")
            await call(client, "add_fact", subject="org:Sam Corp", action="Based in", object="place:Belfast")
            with pytest.raises(ToolError, match="kind prefix"):
                await call(client, "search_facts", subject="Sam")
            found = await call(client, "search_facts", subject="org:Sam")
            by_filter = await call(client, "search_facts", subject="Sam", subject_kind="org")
        assert [f["action"] for f in found["facts"]] == ["Based in"] == [f["action"] for f in by_filter["facts"]]

    async def test_returned_names_carry_their_kind_and_go_straight_back_in(self):
        async with signed_in("alice") as client:
            await call(client, "add_alias", alias="Sam", canonical="org:Sam Corp")
            await call(client, "add_alias", alias="Sam", canonical="person:Sam Sample")
            stored = await call(client, "add_fact", subject="org:Sam", action="Employs", object="Bo Sample")
            assert (stored["subject_kind"], stored["subject_ref"]) == ("org", "org:Sam Corp")
            again = await call(client, "search_facts", subject=stored["subject_ref"], action="Employs")
            described = await call(client, "describe_entity", name=stored["subject_ref"])
        assert again["total"] == 1
        assert (described["ref"], described["exists"]) == ("org:Sam Corp", True)

    async def test_describe_entity_says_when_a_name_is_unknown(self):
        async with signed_in("alice") as client:
            assert (await call(client, "describe_entity", name="Totally Unknown Dataset"))["exists"] is False


class TestPagingAndBatches:
    async def test_search_pages_and_says_when_it_is_cut_off(self):
        async with signed_in("alice") as client:
            facts = [{"subject": f"Item {n}", "action": "Is in", "object": "place:Belfast"} for n in range(120)]
            assert (await call(client, "add_facts", facts=facts[:100]))["count"] == 100
            assert (await call(client, "add_facts", facts=facts[100:]))["count"] == 20
            first = await call(client, "search_facts", limit=100)
            rest = await call(client, "search_facts", limit=100, offset=100)
        assert (first["count"], first["total"], first["truncated"]) == (100, 120, True)
        assert (rest["count"], rest["total"], rest["truncated"], rest["offset"]) == (20, 120, False, 100)

    async def test_add_facts_is_all_or_nothing_and_names_the_bad_item(self):
        async with signed_in("alice") as client:
            with pytest.raises(ToolError, match=r"Item 1: .*between -1.0 and 1.0"):
                await call(
                    client,
                    "add_facts",
                    facts=[
                        {"subject": "A", "action": "Likes", "object": "B"},
                        {"subject": "C", "action": "Likes", "object": "D", "confidence": 9},
                    ],
                )
            assert (await call(client, "search_facts"))["total"] == 0
            with pytest.raises(ToolError, match="at most 100"):
                await call(client, "add_facts", facts=[{"subject": "A", "action": "B", "object": "C"}] * 101)

    async def test_the_type_hint_is_off_by_default_and_on_request(self):
        async with signed_in("alice") as client:
            plain = await call(client, "add_fact", subject="Ada Example", action="Partner", object="person:Bo Sample")
            hinted = await call(
                client, "add_fact", subject="Ada Example", action="Partner", object="person:Bo Sample", check_types=True
            )
        assert "untyped" not in plain
        assert hinted["untyped"] == ["Ada Example", "person:Bo Sample"]


class TestReviews:
    async def test_the_owner_sees_review_outcomes_and_a_disputer_sees_only_their_own(self):
        async with signed_in("alice") as alice:
            fact = await call(
                alice, "add_fact", subject="Ada Example", action="Partner", object="person:Bo Sample", public=True
            )  # public, so a reviewer can still read it (and their own entries) after their request is closed
            await call(alice, "request_review", id=fact["id"], reviewer="bob")
            await call(alice, "request_review", id=fact["id"], reviewer="carol")
        async with signed_in("bob") as bob:
            confirmed = await call(bob, "mark_reviewed", id=fact["id"], outcome="confirmed", note="yes")
            assert confirmed["counter_fact"] is None
        async with signed_in("carol") as carol:
            disputed = await call(carol, "mark_reviewed", id=fact["id"], outcome="disputed", confidence=-0.5)
            assert disputed["counter_fact"]["confidence"] == -0.5
            assert [r["reviewer"] for r in (await call(carol, "get_fact", id=fact["id"]))["reviews"]] == ["carol"]
            assert (await call(carol, "review_outcomes"))["total"] == 0
        async with signed_in("alice") as alice:
            mine = await call(alice, "get_fact", id=fact["id"])
            outcomes = await call(alice, "review_outcomes")
        assert disputed["counter_fact"]["id"] not in str(mine) + str(outcomes)
        assert {r["reviewer"]: r["outcome"] for r in mine["reviews"]} == {"bob": "confirmed", "carol": "disputed"}
        assert outcomes["total"] == 2
        assert {o["reviewer"] for o in outcomes["outcomes"]} == {"bob", "carol"}

    async def test_the_wrong_sign_dispute_is_refused(self):
        async with signed_in("alice") as alice:
            fact = await call(alice, "add_fact", subject="A", action="Likes", object="B")
            await call(alice, "request_review", id=fact["id"], reviewer="bob")
        async with signed_in("bob") as bob:
            with pytest.raises(ToolError, match="opposite"):
                await call(bob, "mark_reviewed", id=fact["id"], outcome="disputed", confidence=0.5)

    async def test_due_for_review_filters_orders_and_pages(self):
        async with signed_in("alice") as client:
            await call(client, "add_fact", subject="A", action="Likes", object="date:1988-05-17", confidence=0.9)
            await call(client, "add_fact", subject="A", action="Knows", object="person:Bo Sample", confidence=0.2)
            by_action = await call(client, "due_for_review", before="2100-01-01", action="knows")
            lowest = await call(client, "due_for_review", before="2100-01-01", order="lowest_confidence", limit=1)
            by_kind = await call(client, "due_for_review", before="2100-01-01", object_kind="date")
            with pytest.raises(ToolError, match="order"):
                await call(client, "due_for_review", order="random")
        assert [f["action"] for f in by_action["facts"]] == ["Knows"]
        assert (lowest["facts"][0]["action"], lowest["total"], lowest["truncated"]) == ("Knows", 2, True)
        assert [f["action"] for f in by_kind["facts"]] == ["Likes"]
