"""Tests for the click_mcp introspection harness using the fake CLI fixture."""

import asyncio
import json

import click
import pytest
from fastmcp import Client, FastMCP

from click_mcp import register_click_commands
from tests.fixtures.fake_cli.cli import cli as fake_cli


@pytest.fixture
def mcp():
    server = FastMCP(name="test")
    register_click_commands(server, fake_cli, prefix="fake")
    return server


@pytest.fixture
def mcp_no_prefix():
    server = FastMCP(name="test")
    register_click_commands(server, fake_cli)
    return server


@pytest.mark.asyncio
async def test_registers_expected_tools(mcp):
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
    assert names == {"fake_greet", "fake_data_fetch", "fake_data_summary"}


@pytest.mark.asyncio
async def test_registers_tools_without_prefix(mcp_no_prefix):
    async with Client(mcp_no_prefix) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
    assert names == {"greet", "data_fetch", "data_summary"}


@pytest.mark.asyncio
async def test_tool_schema_required_param(mcp):
    async with Client(mcp) as client:
        tools = await client.list_tools()
        greet = next(t for t in tools if t.name == "fake_greet")
    schema = greet.inputSchema
    # name is required
    assert "name" in schema.get("required", [])
    # count and shout are optional (not in required)
    assert "count" not in schema.get("required", [])
    assert "shout" not in schema.get("required", [])


@pytest.mark.asyncio
async def test_tool_schema_types(mcp):
    async with Client(mcp) as client:
        tools = await client.list_tools()
        greet = next(t for t in tools if t.name == "fake_greet")
    props = greet.inputSchema["properties"]
    assert props["name"]["type"] == "string"
    # count is int | None → anyOf
    count_schema = props["count"]
    types = {s.get("type") for s in count_schema.get("anyOf", [])}
    assert "integer" in types


@pytest.mark.asyncio
async def test_tool_schema_bool_flag(mcp):
    async with Client(mcp) as client:
        tools = await client.list_tools()
        greet = next(t for t in tools if t.name == "fake_greet")
    props = greet.inputSchema["properties"]
    shout_schema = props["shout"]
    # bool | None
    types = {s.get("type") for s in shout_schema.get("anyOf", [])}
    assert "boolean" in types


@pytest.mark.asyncio
async def test_greet_required_param(mcp):
    async with Client(mcp) as client:
        result = await client.call_tool("fake_greet", {"name": "World"})
    assert result.content[0].text == "Hello, World!"


@pytest.mark.asyncio
async def test_greet_with_count(mcp):
    async with Client(mcp) as client:
        result = await client.call_tool("fake_greet", {"name": "Bob", "count": 3})
    assert result.content[0].text == "Hello, Bob!" * 3


@pytest.mark.asyncio
async def test_greet_with_flag(mcp):
    async with Client(mcp) as client:
        result = await client.call_tool("fake_greet", {"name": "Bob", "shout": True})
    assert result.content[0].text == "HELLO, BOB!"


@pytest.mark.asyncio
async def test_data_fetch_defaults(mcp):
    async with Client(mcp) as client:
        result = await client.call_tool("fake_data_fetch", {})
    lines = result.content[0].text.strip().splitlines()
    assert len(lines) == 10  # default limit=10


@pytest.mark.asyncio
async def test_data_fetch_with_limit(mcp):
    async with Client(mcp) as client:
        result = await client.call_tool("fake_data_fetch", {"limit": 3})
    lines = result.content[0].text.strip().splitlines()
    assert len(lines) == 3


@pytest.mark.asyncio
async def test_data_fetch_skips_output_format(mcp):
    """output_format is an internal param and should not appear in schema."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
        fetch = next(t for t in tools if t.name == "fake_data_fetch")
    assert "output_format" not in fetch.inputSchema.get("properties", {})


@pytest.mark.asyncio
async def test_data_summary_no_params(mcp):
    async with Client(mcp) as client:
        result = await client.call_tool("fake_data_summary", {})
    assert "42 records" in result.content[0].text


@pytest.mark.asyncio
async def test_data_summary_verbose(mcp):
    async with Client(mcp) as client:
        result = await client.call_tool("fake_data_summary", {"verbose": True})
    assert "fake_source" in result.content[0].text


@pytest.mark.asyncio
async def test_docstring_from_command_help(mcp):
    async with Client(mcp) as client:
        tools = await client.list_tools()
        greet = next(t for t in tools if t.name == "fake_greet")
    assert "Greet someone" in greet.description


@pytest.mark.asyncio
async def test_exclude_top_level_command():
    server = FastMCP(name="test")
    register_click_commands(server, fake_cli, prefix="fake", exclude={"greet"})
    async with Client(server) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
    assert "fake_greet" not in names
    assert "fake_data_fetch" in names


@pytest.mark.asyncio
async def test_positional_argument_handling():
    """Commands with click.Argument params should pass values positionally."""

    @click.group()
    def root():
        pass

    @root.command()
    @click.argument("target")
    @click.option("--count", default=1, type=int)
    def ping(target, count):
        """Ping a target."""
        click.echo(f"ping {target} x{count}")

    server = FastMCP(name="test")
    register_click_commands(server, root)
    async with Client(server) as client:
        result = await client.call_tool("ping", {"target": "localhost", "count": 2})
    assert result.content[0].text == "ping localhost x2"
