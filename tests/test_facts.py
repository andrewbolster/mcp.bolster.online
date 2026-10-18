"""Per-user facts tools: storage, validation, search, and who may see what."""

import contextlib
import uuid

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.auth import AccessToken
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

import facts
from app import mcp, mcp_auth

BIRTHDAY = {"time": "--10-18", "subject": "Szilvia Mandic", "object": "Birthday", "action": "Has"}


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


async def add(client: Client, **overrides) -> dict:
    result = await client.call_tool("add_fact", {**BIRTHDAY, **overrides})
    return result.structured_content


async def search(client: Client, **args) -> dict:
    return (await client.call_tool("search_facts", args)).structured_content


class TestUuid7:
    def test_version_variant_and_timestamp(self):
        value = facts.uuid7(now_ms=1_760_000_000_123)
        assert value.version == 7
        assert value.variant == uuid.RFC_4122
        assert value.int >> 80 == 1_760_000_000_123

    def test_orders_by_time(self):
        earlier, later = facts.uuid7(now_ms=1_000), facts.uuid7(now_ms=2_000)
        assert str(earlier) < str(later)

    def test_random_bits_differ(self):
        assert facts.uuid7(now_ms=5) != facts.uuid7(now_ms=5)


class TestParseTime:
    @pytest.mark.parametrize(
        "value",
        [
            "2026",
            "2026-10",
            "2026-10-18",
            "2024-02-29",
            "2026-10-18T09:30Z",
            "2026-10-18T09:30:15+01:00",
            "2026-10-18T09:30:15.123456-05:30",
            "--10-18",
            "--02-29",
        ],
    )
    def test_accepts_strict_iso(self, value):
        assert facts.parse_time(value)[0] == value

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "18th October",
            "2026-02-30",
            "2025-02-29",
            "--02-30",
            "--13-01",
            "--10-18Z",
            "2026-13",
            "0000",
            "20261018",
            "2026-W42-1",
            "2026-10-18T09:30",
            "2026-10-18 09:30Z",
            "2026-10-18T25:00Z",
        ],
    )
    def test_rejects_everything_else_and_says_what_is_accepted(self, value):
        with pytest.raises(ToolError, match="strict ISO 8601"):
            facts.parse_time(value)

    def test_datetimes_sort_in_utc(self):
        assert facts.parse_time("2026-10-18T10:00:00+01:00")[1] == facts.parse_time("2026-10-18T09:00:00Z")[1]

    def test_recurring_dates_have_no_sort_key(self):
        assert facts.parse_time("--10-18")[1] is None


class TestAddAndGet:
    async def test_round_trip_with_server_set_fields(self):
        async with signed_in("alice") as client:
            fact = await add(client, confidence=0.9, references=["https://example.com/card"])
            fetched = (await client.call_tool("get_fact", {"id": fact["id"]})).structured_content
        assert fetched == fact
        assert fact["time"] == "--10-18"
        assert (fact["subject"], fact["object"], fact["action"]) == ("Szilvia Mandic", "Birthday", "Has")
        assert fact["confidence"] == 0.9
        assert fact["references"] == ["https://example.com/card"]
        assert uuid.UUID(fact["id"]).version == 7
        assert fact["created"].endswith("Z")
        assert fact["created_by"] == "alice"
        assert fact["updated"] is None and fact["updated_by"] is None

    async def test_optional_fields_default_to_empty(self):
        async with signed_in("alice") as client:
            fact = await add(client)
        assert fact["confidence"] is None
        assert fact["references"] == []

    async def test_creates_the_database_on_demand(self, data_dir):
        assert not (data_dir / "facts.sqlite3").exists()
        async with signed_in("alice") as client:
            await add(client)
        assert (data_dir / "facts.sqlite3").exists()

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"time": "18th October"}, "strict ISO 8601"),
            ({"subject": "   "}, "subject must not be empty"),
            ({"object": "x" * 201}, "at most 200"),
            ({"confidence": 1.5}, "between 0.0 and 1.0"),
            ({"confidence": -0.1}, "between 0.0 and 1.0"),
            ({"references": ["a"] * 21}, "at most 20"),
            ({"references": [""]}, "each reference"),
            ({"references": ["x" * 501]}, "each reference"),
        ],
    )
    async def test_rejects_bad_input_with_a_fixable_message(self, overrides, message):
        async with signed_in("alice") as client:
            with pytest.raises(ToolError, match=message):
                await add(client, **overrides)

    async def test_get_unknown_id(self):
        async with signed_in("alice") as client:
            with pytest.raises(ToolError, match="No fact with id"):
                await client.call_tool("get_fact", {"id": str(facts.uuid7())})

    async def test_unknown_argument_gets_the_friendly_error(self):
        async with signed_in("alice") as client:
            with pytest.raises(ToolError, match="subject"):
                await client.call_tool("add_fact", {**BIRTHDAY, "colour": "blue"})


class TestUpdate:
    async def test_only_supplied_fields_change(self):
        async with signed_in("alice") as client:
            original = await add(client, confidence=0.5, references=["a"])
            updated = (
                await client.call_tool("update_fact", {"id": original["id"], "confidence": 0.9})
            ).structured_content
        assert updated["confidence"] == 0.9
        for untouched in ("id", "time", "subject", "object", "action", "references", "created", "created_by"):
            assert updated[untouched] == original[untouched]
        assert updated["updated_by"] == "alice"
        assert updated["updated"] is not None

    async def test_changes_time_and_text_and_search_follows(self):
        async with signed_in("alice") as client:
            fact = await add(client)
            await client.call_tool("update_fact", {"id": fact["id"], "time": "2027", "subject": "Silvia"})
            assert (await search(client, subject="Szilvia Mandic"))["count"] == 0
            assert (await search(client, subject="silvia", time_from="2027"))["count"] == 1

    async def test_empty_references_clears_them(self):
        async with signed_in("alice") as client:
            fact = await add(client, references=["a", "b"])
            updated = (await client.call_tool("update_fact", {"id": fact["id"], "references": []})).structured_content
        assert updated["references"] == []

    async def test_nothing_to_update(self):
        async with signed_in("alice") as client:
            fact = await add(client)
            with pytest.raises(ToolError, match="Nothing to update"):
                await client.call_tool("update_fact", {"id": fact["id"]})

    async def test_validates_changed_fields(self):
        async with signed_in("alice") as client:
            fact = await add(client)
            with pytest.raises(ToolError, match="strict ISO 8601"):
                await client.call_tool("update_fact", {"id": fact["id"], "time": "soon"})

    async def test_unknown_id(self):
        async with signed_in("alice") as client:
            with pytest.raises(ToolError, match="No fact with id"):
                await client.call_tool("update_fact", {"id": str(facts.uuid7()), "confidence": 0.1})


class TestDelete:
    async def test_delete_then_get(self):
        async with signed_in("alice") as client:
            fact = await add(client)
            deleted = (await client.call_tool("delete_fact", {"id": fact["id"]})).structured_content
            assert deleted == {"deleted": fact["id"]}
            with pytest.raises(ToolError, match="No fact with id"):
                await client.call_tool("get_fact", {"id": fact["id"]})
            with pytest.raises(ToolError, match="No fact with id"):
                await client.call_tool("delete_fact", {"id": fact["id"]})


class TestSearch:
    async def test_matches_are_case_insensitive_and_exact(self):
        async with signed_in("alice") as client:
            await add(client)
            await add(client, subject="Szilvia Smith", object="Allergy", action="Has", time="2026")
            assert (await search(client, subject="szilvia mandic"))["count"] == 1
            assert (await search(client, object="BIRTHDAY"))["count"] == 1
            assert (await search(client, action="has"))["count"] == 2
            assert (await search(client, subject="Szilvia"))["count"] == 0

    async def test_unicode_names_fold(self):
        async with signed_in("alice") as client:
            await add(client, subject="Łukasz Ćwiek")
            assert (await search(client, subject="łukasz ćwiek"))["count"] == 1
            assert (await search(client, subject="ŁUKASZ ĆWIEK"))["count"] == 1

    async def test_free_text(self):
        async with signed_in("alice") as client:
            await add(client)
            await add(client, subject="Bob", object="Cat", action="Owns", time="2026-01-01")
            assert (await search(client, q="mandic"))["count"] == 1
            assert (await search(client, q="owns cat"))["count"] == 1
            assert (await search(client, q="100%"))["count"] == 0

    async def test_exact_time_finds_recurring_facts(self):
        async with signed_in("alice") as client:
            await add(client)
            await add(client, time="2026-10-18")
            found = await search(client, time="--10-18")
        assert found["count"] == 1
        assert found["facts"][0]["time"] == "--10-18"

    async def test_time_range_uses_utc_and_skips_recurring_facts(self):
        async with signed_in("alice") as client:
            await add(client, subject="a", time="2025-06-01")
            await add(client, subject="b", time="2026-03-01T00:30:00+01:00")  # 2026-02-28T23:30Z
            await add(client, subject="c", time="2026-10")
            await add(client, subject="d")  # recurring: never matched by a range
            in_2026 = await search(client, time_from="2026", time_to="2026-12-31")
            march_on = await search(client, time_from="2026-03-01T00:00Z")
        assert {f["subject"] for f in in_2026["facts"]} == {"b", "c"}
        assert {f["subject"] for f in march_on["facts"]} == {"c"}

    async def test_range_bounds_need_a_year(self):
        async with signed_in("alice") as client:
            with pytest.raises(ToolError, match="needs a date with a year"):
                await search(client, time_from="--10-18")

    async def test_min_confidence(self):
        async with signed_in("alice") as client:
            await add(client, subject="sure", confidence=0.9)
            await add(client, subject="unsure", confidence=0.2)
            await add(client, subject="unrated")
            found = await search(client, min_confidence=0.5)
        assert [f["subject"] for f in found["facts"]] == ["sure"]

    async def test_newest_first_and_limit(self):
        async with signed_in("alice") as client:
            for name in ("first", "second", "third"):
                await add(client, subject=name)
            everything = await search(client)
            limited = await search(client, limit=2)
        assert [f["subject"] for f in everything["facts"]] == ["third", "second", "first"]
        assert limited["count"] == 2

    async def test_limit_is_clamped(self):
        async with signed_in("alice") as client:
            await add(client)
            assert (await search(client, limit=0))["count"] == 1
            assert (await search(client, limit=10_000))["count"] == 1


class TestWhoSeesWhat:
    async def test_logins_cannot_read_update_or_delete_each_others_facts(self):
        async with signed_in("alice") as alice:
            mine = await add(alice)
        async with signed_in("bob") as bob:
            assert (await search(bob))["count"] == 0
            assert (await search(bob, subject="Szilvia Mandic"))["count"] == 0
            with pytest.raises(ToolError, match="No fact with id"):
                await bob.call_tool("get_fact", {"id": mine["id"]})
            with pytest.raises(ToolError, match="No fact with id"):
                await bob.call_tool("update_fact", {"id": mine["id"], "subject": "hijacked"})
            with pytest.raises(ToolError, match="No fact with id"):
                await bob.call_tool("delete_fact", {"id": mine["id"]})
        async with signed_in("alice") as alice:
            intact = (await alice.call_tool("get_fact", {"id": mine["id"]})).structured_content
        assert intact == mine

    async def test_each_login_has_its_own_facts_and_authorship(self):
        async with signed_in("alice") as alice:
            await add(alice)
        async with signed_in("bob") as bob:
            theirs = await add(bob)
            found = await search(bob)
        assert found["count"] == 1
        assert theirs["created_by"] == "bob"

    async def test_owner_is_never_a_tool_argument(self):
        async with signed_in("alice") as client:
            tools = {
                t.name: t for t in await client.list_tools() if t.name.endswith("_fact") or t.name == "search_facts"
            }
        assert set(tools) == {"add_fact", "get_fact", "search_facts", "update_fact", "delete_fact"}
        for tool in tools.values():
            assert not {"owner", "login", "user", "created_by"} & set(tool.inputSchema["properties"])

    async def test_signed_out_callers_cannot_use_the_tools(self):
        async with Client(mcp_auth) as client:
            assert await client.list_tools() == []
            with pytest.raises(ToolError):
                await client.call_tool("add_fact", BIRTHDAY)

    async def test_a_login_off_the_allowlist_cannot_use_the_tools(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "alice")
        async with signed_in("bob") as client:
            assert await client.list_tools() == []
            with pytest.raises(ToolError):
                await client.call_tool("search_facts", {})

    def test_no_token_means_not_authenticated(self):
        with pytest.raises(ToolError, match="Not authenticated"):
            facts._login()

    async def test_the_public_server_does_not_have_the_tools(self):
        async with Client(mcp) as public:
            names = {t.name for t in await public.list_tools()}
        assert not names & {"add_fact", "get_fact", "search_facts", "update_fact", "delete_fact"}


class TestStorage:
    def test_data_dir_defaults_next_to_app(self, monkeypatch):
        monkeypatch.delenv("MCP_DATA_DIR")
        assert facts.data_dir() == facts.Path(facts.__file__).resolve().parent / "data"

    async def test_schema_version_is_recorded_once(self, data_dir):
        async with signed_in("alice") as client:
            await add(client)
            await add(client)
        with facts._db() as conn:
            assert [r["version"] for r in conn.execute("SELECT version FROM schema_version")] == [facts.SCHEMA_VERSION]
        assert facts.data_dir() == data_dir
