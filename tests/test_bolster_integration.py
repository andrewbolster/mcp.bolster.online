"""Integration tests: introspect the real bolster CLI via click_mcp."""

import pytest
from fastmcp import FastMCP

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
async def test_bolster_tools_registered(bolster_mcp):
    """At least one tool is registered from the bolster CLI."""
    from fastmcp import Client

    async with Client(bolster_mcp) as client:
        tools = await client.list_tools()
    assert len(tools) > 0


@pytest.mark.asyncio
async def test_bolster_tool_names_prefixed(bolster_mcp):
    """All registered tools carry the bolster_ prefix."""
    from fastmcp import Client

    async with Client(bolster_mcp) as client:
        tools = await client.list_tools()
    assert all(t.name.startswith("bolster_") for t in tools)


@pytest.mark.asyncio
async def test_bolster_known_tools_present(bolster_mcp):
    """A sample of expected bolster tools are present."""
    from fastmcp import Client

    async with Client(bolster_mcp) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools}
    for expected in (
        "bolster_nisra_births",
        "bolster_ni_house_prices",
        "bolster_ni_elections",
    ):
        assert expected in names, f"Expected tool {expected!r} not found"


@pytest.mark.asyncio
async def test_bolster_tools_have_descriptions(bolster_mcp):
    """Every registered tool has a non-empty description."""
    from fastmcp import Client

    async with Client(bolster_mcp) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert tool.description, f"Tool {tool.name!r} has no description"
