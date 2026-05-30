"""Integration tests: introspect the real bolster CLI via click_mcp.

These tests verify that introspection completes without exceptions and that
the resulting tools are well-formed — regardless of what commands bolster
exposes. They are skipped when bolster is not installed (e.g. in CI).
"""

import pytest
from fastmcp import Client, FastMCP

pytest.importorskip("bolster", reason="bolster package not installed")

from bolster.cli import cli as bolster_cli  # noqa: E402

from click_mcp import register_click_commands  # noqa: E402


@pytest.fixture(scope="module")
def bolster_mcp():
    mcp = FastMCP("bolster-integration-test")
    register_click_commands(
        mcp, bolster_cli, prefix="bolster", exclude={"list-sources"}
    )
    return mcp


@pytest.mark.asyncio
async def test_bolster_introspection_yields_tools(bolster_mcp):
    """Introspection completes without exceptions and registers at least one tool."""
    async with Client(bolster_mcp) as client:
        tools = await client.list_tools()
    assert len(tools) > 0


@pytest.mark.asyncio
async def test_bolster_all_tools_have_name_and_description(bolster_mcp):
    """Every tool has a non-empty name and description (schema is complete)."""
    async with Client(bolster_mcp) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert tool.name, f"Tool is missing a name: {tool!r}"
        assert tool.description, f"Tool {tool.name!r} has no description"


@pytest.mark.asyncio
async def test_bolster_all_tools_have_valid_input_schema(bolster_mcp):
    """Every tool exposes a valid JSON Schema object for its inputs."""
    async with Client(bolster_mcp) as client:
        tools = await client.list_tools()
    for tool in tools:
        schema = tool.inputSchema
        assert isinstance(schema, dict), f"Tool {tool.name!r} inputSchema is not a dict"
        assert schema.get("type") == "object", (
            f"Tool {tool.name!r} inputSchema type != object"
        )
