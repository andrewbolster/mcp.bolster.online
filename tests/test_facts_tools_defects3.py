"""The fixes for the defects the news-and-releases experiment found, through the tools an LLM client calls."""

import pytest
from fastmcp.exceptions import ToolError

from tests.test_facts_tools import call, signed_in

NISRA = "org:Northern Ireland Statistics and Research Agency"
LATE = "2099-01-01"


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """A fresh database per test and two allowed logins."""
    monkeypatch.setenv("MCP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "alice,bob")


class TestDescribeEntityTool:
    async def test_a_typed_name_comes_back_as_the_entity_it_is_stored_as(self):
        async with signed_in("alice") as client:
            await call(client, "add_fact", subject=NISRA, action="Publishes", object="Labour Market Report")
            described = await call(client, "describe_entity", name="northern ireland statistics and research AGENCY")
        assert described["name"] == "Northern Ireland Statistics and Research Agency"
        assert (described["kind"], described["ref"], described["exists"]) == ("org", NISRA, True)

    async def test_an_alias_is_described_as_its_canonical_entity(self):
        async with signed_in("alice") as client:
            await call(client, "add_fact", subject=NISRA, action="Publishes", object="Labour Market Report")
            await call(client, "add_alias", alias="NISRA", canonical=NISRA)
            described = await call(client, "describe_entity", name="NISRA")
        assert described["ref"] == NISRA

    async def test_a_value_is_not_an_entity(self):
        async with signed_in("alice") as client:
            await call(client, "add_fact", subject="org:NISRA", action="Has cadence", object="text:Quarterly")
            described = await call(client, "describe_entity", name="Quarterly")
        assert (described["exists"], described["mentioned_as_value_in"], described["ref"]) == (
            False,
            1,
            "text:Quarterly",
        )

    async def test_a_name_stored_under_several_kinds_warns_instead_of_guessing(self):
        async with signed_in("alice") as client:
            await call(client, "add_fact", subject="org:Mercury", action="Makes", object="Cars")
            await call(client, "add_fact", subject="place:Mercury", action="Is in", object="Space")
            described = await call(client, "describe_entity", name="mercury")
        assert described["kind"] is None
        assert "org:Mercury" in described["warnings"][0] and "place:Mercury" in described["warnings"][0]

    async def test_another_login_does_not_see_the_stored_spelling(self):
        async with signed_in("alice") as client:
            await call(client, "add_fact", subject=NISRA, action="Publishes", object="Labour Market Report")
        async with signed_in("bob") as client:
            described = await call(client, "describe_entity", name="northern ireland statistics and research agency")
        assert (described["kind"], described["exists"]) == (None, False)


class TestPunctuationInsensitiveSearchTool:
    async def test_a_name_with_brackets_is_found_without_them(self):
        async with signed_in("alice") as client:
            await call(
                client, "add_alias", alias="Monthly Births (Northern Ireland)", canonical="org:Births Statistics"
            )
            await call(client, "add_fact", subject="org:Births Statistics", action="Has cadence", object="text:Monthly")
            found = await call(client, "search_facts", subject="Monthly Births Northern Ireland")
        assert [f["action"] for f in found["facts"]] == ["Has cadence"]


class TestDueForReviewTool:
    async def test_the_reviewed_filter_separates_reviewed_from_never_reviewed_facts(self):
        async with signed_in("alice") as client:
            first = await call(client, "add_fact", subject="Subject 1", action="Is a", object="Thing")
            await call(client, "add_fact", subject="Subject 2", action="Is a", object="Thing")
            await call(client, "mark_reviewed", id=first["id"], outcome="confirmed")
            reviewed = await call(client, "due_for_review", before=LATE, reviewed=True)
            never = await call(client, "due_for_review", before=LATE, reviewed=False)
            everything = await call(client, "due_for_review", before=LATE)
        assert [f["id"] for f in reviewed["facts"]] == [first["id"]]
        assert [f["subject"] for f in never["facts"]] == ["Subject 2"]
        assert everything["total"] == 2

    async def test_excluding_never_reviewed_facts_lists_only_old_reviews(self):
        async with signed_in("alice") as client:
            first = await call(client, "add_fact", subject="Subject 1", action="Is a", object="Thing")
            await call(client, "add_fact", subject="Subject 2", action="Is a", object="Thing")
            await call(client, "mark_reviewed", id=first["id"], outcome="confirmed")
            listed = await call(client, "due_for_review", before=LATE, include_never_reviewed=False)
        assert [f["id"] for f in listed["facts"]] == [first["id"]]

    async def test_the_contradictory_combination_is_refused_with_a_clear_message(self):
        async with signed_in("alice") as client:
            with pytest.raises(ToolError, match="include_never_reviewed"):
                await call(client, "due_for_review", before=LATE, reviewed=False, include_never_reviewed=False)
