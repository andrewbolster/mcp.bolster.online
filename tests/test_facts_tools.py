"""The MCP adapter over the fact store: registration, auth wiring, error mapping and end-to-end flows."""

import contextlib

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.auth import AccessToken
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

import facts_tools
from app import mcp, mcp_auth

FACT_TOOLS = {
    "add_fact", "get_fact", "search_facts", "update_fact", "delete_fact", "describe_entity", "add_alias", "set_self",
    "relationships_between", "request_review", "mark_reviewed", "pending_reviews", "due_for_review",
    "add_facts", "review_outcomes",
}  # fmt: skip
READ_ONLY = {
    "get_fact",
    "search_facts",
    "describe_entity",
    "relationships_between",
    "pending_reviews",
    "due_for_review",
    "review_outcomes",
}


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "alice,bob")
    return tmp_path


def fake_login(login: str) -> AuthenticatedUser:
    return AuthenticatedUser(AccessToken(token="test-token", client_id="123", scopes=[], claims={"login": login}))


@contextlib.asynccontextmanager
async def signed_in(login: str):
    token = auth_context_var.set(fake_login(login))
    try:
        async with Client(mcp_auth) as client:
            yield client
    finally:
        auth_context_var.reset(token)


async def call(client: Client, tool: str, **args):
    return (await client.call_tool(tool, args)).structured_content


class TestRegistration:
    async def test_the_authenticated_server_has_every_fact_tool(self):
        async with signed_in("alice") as client:
            names = {tool.name for tool in await client.list_tools()}
        assert names >= FACT_TOOLS

    async def test_the_public_server_has_none_of_them(self):
        async with Client(mcp) as client:
            names = {tool.name for tool in await client.list_tools()}
        assert not FACT_TOOLS & names

    async def test_read_only_hints(self):
        async with signed_in("alice") as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
        assert {name for name in FACT_TOOLS if tools[name].annotations.readOnlyHint} == READ_ONLY
        assert tools["delete_fact"].annotations.destructiveHint is True

    async def test_the_database_lives_where_the_environment_says(self, data_dir):
        assert facts_tools.data_dir() == data_dir
        async with signed_in("alice") as client:
            await call(client, "add_fact", subject="A", action="Is a", object="B")
        assert (data_dir / "facts.sqlite3").exists()


class TestAuth:
    def test_no_token_means_no_facts(self):
        with pytest.raises(ToolError, match="Not authenticated"):
            facts_tools._login()

    async def test_the_actor_is_the_verified_login(self):
        async with signed_in("alice") as client:
            fact = await call(client, "add_fact", subject="A", action="Is a", object="B")
        assert fact["created_by"] == "alice"


class TestFlows:
    async def test_my_partner_from_a_fresh_start(self):
        """The scenario that motivated the design: 'tell me facts about my partner'."""
        async with signed_in("alice") as client:
            await call(client, "set_self", name="person:Ada Example")
            await call(client, "add_alias", alias="bolster", canonical="person:Ada Example")
            await call(client, "add_fact", subject="me", action="Has birthday", object="date:1988-05-17")
            await call(
                client, "add_fact", subject="bolster", action="Partner", object="person:Bo Sample", valid_from="2012"
            )
            await call(client, "add_fact", subject="Bo Sample", action="Has birthday", object="date:1990-02-03")
            await call(client, "add_fact", subject="Bo Sample", action="Likes", object="Tea")

            partner = await call(client, "search_facts", subject="me", action="Partner")
            assert [f["object"] for f in partner["facts"]] == ["Bo Sample"]
            facts = await call(client, "search_facts", subject=partner["facts"][0]["object"])
            assert sorted(f["action"] for f in facts["facts"]) == ["Has birthday", "Likes"]
            between = await call(client, "relationships_between", a="me", b="Bo Sample")
            assert [f["action"] for f in between["direct"]] == ["Partner"]
            described = await call(client, "describe_entity", name="bolster")
            assert (described["name"], "bolster" in described["aliases"]) == ("Ada Example", True)

    async def test_date_values_validity_and_negatives(self):
        async with signed_in("alice") as client:
            await call(client, "set_self", name="person:Ada Example")
            await call(
                client,
                "add_fact",
                subject="me",
                action="Partner",
                object="person:Bo Sample",
                valid_from="2012",
                valid_to="2015",
            )
            then = await call(client, "search_facts", subject="me", action="Partner", valid_at="2013-05-17")
            now = await call(client, "search_facts", subject="me", action="Partner", valid_at="2020-01-01")
            assert (then["count"], now["count"]) == (1, 0)
            await call(client, "add_fact", subject="me", action="Sibling of", object="person:Bo Sample", confidence=-1)
            assert (await call(client, "search_facts", action="Sibling of"))["count"] == 0
            assert (await call(client, "search_facts", action="Sibling of", include_negative=True))["count"] == 1

    async def test_update_can_clear_a_validity_bound_with_an_empty_string(self):
        async with signed_in("alice") as client:
            fact = await call(
                client, "add_fact", subject="A", action="Is a", object="B", valid_from="2012", valid_to="2015"
            )
            cleared = await call(client, "update_fact", id=fact["id"], valid_to="")
            assert (cleared["valid_from"], cleared["valid_to"]) == ("2012", None)
            kept = await call(client, "update_fact", id=fact["id"], confidence=0.5)
            assert (kept["valid_from"], kept["confidence"]) == ("2012", 0.5)

    async def test_delete(self):
        async with signed_in("alice") as client:
            fact = await call(client, "add_fact", subject="A", action="Is a", object="B")
            assert await call(client, "delete_fact", id=fact["id"]) == {"deleted": fact["id"]}
            with pytest.raises(ToolError, match="No fact"):
                await call(client, "get_fact", id=fact["id"])


class TestErrors:
    async def test_engine_errors_become_tool_errors_that_say_what_to_do(self):
        async with signed_in("alice") as client:
            with pytest.raises(ToolError, match="set_self"):
                await call(client, "add_fact", subject="me", action="Likes", object="Tea")
            with pytest.raises(ToolError, match="strict ISO 8601"):
                await call(client, "add_fact", subject="A", action="Is a", object="B", valid_from="last year")
            with pytest.raises(ToolError, match="between -1.0 and 1.0"):
                await call(client, "add_fact", subject="A", action="Is a", object="B", confidence=2)
            with pytest.raises(ToolError, match="scope"):
                await call(client, "search_facts", scope="everyone")

    async def test_an_ambiguous_alias_lists_the_candidates(self):
        async with signed_in("alice") as client:
            await call(client, "add_alias", alias="Sam", canonical="person:Sam Sample")
            await call(client, "add_alias", alias="Sam", canonical="person:Sam Placeholder")
            with pytest.raises(ToolError) as caught:
                await call(client, "search_facts", subject="Sam")
        assert "person:Sam Sample" in str(caught.value)
        assert "person:Sam Placeholder" in str(caught.value)

    async def test_bad_argument_types_get_the_friendly_message(self):
        async with signed_in("alice") as client:
            with pytest.raises(ToolError, match="confidence"):
                await call(client, "add_fact", subject="A", action="Is a", object="B", confidence="very")


class TestReviewsAcrossUsers:
    async def test_alice_asks_bob_who_confirms(self):
        async with signed_in("alice") as alice:
            fact = await call(alice, "add_fact", subject="Ada Example", action="Has birthday", object="date:1988-05-17")
            request = await call(alice, "request_review", id=fact["id"], reviewer="Bob", note="still right?")
            assert request["requested_of"] == "bob"
            assert (await call(alice, "pending_reviews", direction="sent"))["count"] == 1
        async with signed_in("bob") as bob:
            assert (await call(bob, "search_facts"))["count"] == 0  # not bob's
            pending = await call(bob, "pending_reviews")
            assert [r["fact"]["id"] for r in pending["requests"]] == [fact["id"]]
            assert (await call(bob, "get_fact", id=fact["id"]))["object"] == "1988-05-17"
            reviewed = await call(bob, "mark_reviewed", id=fact["id"], outcome="confirmed", note="yes")
            assert reviewed["fact"]["reviewed_by"] == "bob"
            assert (await call(bob, "pending_reviews"))["count"] == 0
            with pytest.raises(ToolError, match="No fact"):
                await call(bob, "get_fact", id=fact["id"])  # the grant ended with the review

    async def test_a_dispute_becomes_bobs_own_negative_fact(self):
        async with signed_in("alice") as alice:
            fact = await call(alice, "add_fact", subject="Ada Example", action="Likes", object="Coffee")
            await call(alice, "request_review", id=fact["id"], reviewer="bob")
        async with signed_in("bob") as bob:
            result = await call(bob, "mark_reviewed", id=fact["id"], outcome="disputed")
            assert (result["counter_fact"]["confidence"], result["counter_fact"]["created_by"]) == (-1.0, "bob")
        async with signed_in("alice") as alice:
            assert (await call(alice, "get_fact", id=fact["id"]))["confidence"] == 1.0

    async def test_due_for_review_lists_the_callers_stale_facts(self):
        async with signed_in("alice") as alice:
            await call(alice, "add_fact", subject="A", action="Is a", object="B")
            assert (await call(alice, "due_for_review"))["count"] == 0
            due = await call(alice, "due_for_review", before="2100-01-01")
            assert due["count"] == 1
        async with signed_in("bob") as bob:
            assert (await call(bob, "due_for_review", before="2100-01-01"))["count"] == 0

    async def test_private_facts_are_invisible_across_users_through_the_tools(self):
        async with signed_in("alice") as alice:
            fact = await call(alice, "add_fact", subject="Ada Example", action="Likes", object="Coffee")
        async with signed_in("bob") as bob:
            for scope in ("mine", "public", "all"):
                assert (await call(bob, "search_facts", scope=scope, q="coffee"))["count"] == 0
            with pytest.raises(ToolError, match="No fact"):
                await call(bob, "update_fact", id=fact["id"], confidence=0.1)
            with pytest.raises(ToolError, match="No fact"):
                await call(bob, "delete_fact", id=fact["id"])
