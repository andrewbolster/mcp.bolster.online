"""Fake CLI that exercises the range of Click patterns we need to handle."""

import click


@click.group()
def cli():
    """Fake CLI for testing MCP introspection harness."""


@cli.command()
@click.option("--name", required=True, help="Name to greet.")
@click.option("--count", default=1, type=int, help="Number of greetings.")
@click.option("--shout", is_flag=True, default=False, help="SHOUT the greeting.")
def greet(name, count, shout):
    """Greet someone by name."""
    msg = f"Hello, {name}!" * count
    click.echo(msg.upper() if shout else msg)


@cli.group()
def data():
    """Data retrieval commands."""


@data.command("fetch")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "csv", "table"]),
    default="table",
    help="Output format.",
)
@click.option("--limit", default=10, type=int, help="Maximum rows to return.")
@click.option("--filter", "filter_str", default=None, help="Filter expression.")
def data_fetch(output_format, limit, filter_str):
    """Fetch data from the fake source."""
    rows = [{"id": i, "value": i * 2} for i in range(limit)]
    if output_format == "json":
        import json

        click.echo(json.dumps(rows))
    else:
        for r in rows:
            click.echo(f"{r['id']}: {r['value']}")


@data.command("summary")
@click.option("--verbose", is_flag=True, default=False, help="Show verbose output.")
def data_summary(verbose):
    """Show a summary of available data."""
    click.echo("Summary: 42 records available.")
    if verbose:
        click.echo("Source: fake_source v1.0")
