"""The fixes for the claims experiment's defects, through the tools an LLM client actually calls."""

import pytest
from fastmcp.exceptions import ToolError

from tests.test_facts_tools import call, signed_in


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "alice,bob,carol")


class TestWarnings:
    async def test_an_unknown_kind_prefix_is_flagged_in_the_reply(self):
        async with signed_in("alice") as client:
            stored = await call(client, "add_fact", subject="claim:Foo", action="Is a", object="Claim")
            batch = await call(
                client,
                "add_facts",
                facts=[
                    {"subject": "A", "action": "Likes", "object": "B"},
                    {"subject": "event:C", "action": "x", "object": "y"},
                ],
            )
            found = await call(client, "search_facts", subject="claim:Foo")
            quiet = await call(client, "search_facts", subject="Foo")
        assert stored["subject"] == "claim:Foo" and "claim" in stored["warnings"][0]
        assert batch["warnings"][0].startswith("Item 1:")
        assert found["total"] == 1 and "warnings" in found
        assert "warnings" not in quiet

    async def test_a_well_formed_call_carries_no_warnings_key(self):
        async with signed_in("alice") as client:
            stored = await call(client, "add_fact", subject="person:Ada Example", action="Likes", object="Tea")
        assert "warnings" not in stored


class TestFiltersThroughTheTool:
    async def test_validity_review_and_text_filters(self):
        async with signed_in("alice") as client:
            await call(
                client, "add_fact", subject="A", action="Is", object="Inside", valid_from="2021", valid_to="2022"
            )
            await call(client, "add_fact", subject="B", action="Is", object="Wider", valid_from="2019", valid_to="2024")
            await call(
                client, "add_fact", subject="C", action="Is", object="NoPeriod", attributes={"note": "Café ordered"}
            )
            within = await call(client, "search_facts", valid_from="2020", valid_to="2023", valid_within=True)
            dated = await call(client, "search_facts", has_period=True)
            undated = await call(client, "search_facts", has_period=False)
            text = await call(client, "search_facts", q="CAFE")
            never = await call(client, "search_facts", reviewed=False)
            reviewed_before = await call(client, "search_facts", reviewed_before="2100-01-01")
            baseline = await call(client, "search_facts", reviewed_before="2100-01-01", include_never_reviewed=True)
        assert [f["subject"] for f in within["facts"]] == ["A"]
        assert (dated["total"], undated["total"]) == (2, 1)
        assert [f["subject"] for f in text["facts"]] == ["C"]
        assert never["total"] == 3
        assert reviewed_before["total"] == 0  # nothing has been reviewed yet
        assert baseline["total"] == 3

    async def test_valid_within_without_a_window_is_a_clear_error(self):
        async with signed_in("alice") as client:
            with pytest.raises(ToolError, match="valid_within needs"):
                await call(client, "search_facts", valid_within=True)

    async def test_accents_do_not_matter_when_searching_by_name(self):
        async with signed_in("alice") as client:
            await call(client, "add_alias", alias="Zoë", canonical="person:Zoe Example")
            await call(client, "add_fact", subject="Zoë", action="Likes", object="Tea")
            found = await call(client, "search_facts", subject="ZOE")
        assert found["total"] == 1


class TestReviewsThroughTheTools:
    async def test_an_owner_cannot_dispute_their_own_fact(self):
        async with signed_in("alice") as client:
            fact = await call(client, "add_fact", subject="Ada Example", action="Likes", object="Tea")
            with pytest.raises(ToolError, match="update_fact"):
                await call(client, "mark_reviewed", id=fact["id"], outcome="disputed")

    async def test_a_reviewer_can_list_what_they_reviewed(self):
        async with signed_in("alice") as alice:
            fact = await call(alice, "add_fact", subject="Ada Example", action="Likes", object="Tea")
            await call(alice, "request_review", id=fact["id"], reviewer="bob")
        async with signed_in("bob") as bob:
            await call(bob, "mark_reviewed", id=fact["id"], outcome="confirmed", note="yes")
            default = await call(bob, "review_outcomes")
            mine = await call(bob, "review_outcomes", role="reviewer")
            both = await call(bob, "review_outcomes", role="all")
            with pytest.raises(ToolError):
                await call(bob, "review_outcomes", role="everyone")
        assert default["total"] == 0
        assert mine["total"] == both["total"] == 1
        entry = mine["outcomes"][0]
        assert (entry["role"], entry["outcome"], entry["note"], entry["fact_id"]) == (
            "reviewer",
            "confirmed",
            "yes",
            fact["id"],
        )
        assert "object_ref" not in entry  # the request is closed, so the fact's wording is no longer his to read
        async with signed_in("alice") as alice:
            owner_view = await call(alice, "review_outcomes")
        assert owner_view["outcomes"][0]["role"] == "owner" and owner_view["outcomes"][0]["object_ref"] == "Tea"
