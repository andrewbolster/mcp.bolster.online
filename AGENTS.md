# mcp.bolster.online

A FastMCP server exposing curated information about Andrew Bolster (resources and tools) plus the [`bolster`](https://github.com/andrewbolster/bolster) data-source CLI, served over streamable HTTP. README.md covers configuration, secrets and deployment; this file is for anyone (human or agent) changing the code.

## Layout

```
app.py                  # Everything user-facing: resources, tools, both servers, ASGI app
click_mcp.py            # Turns a Click command tree into MCP tools (used for the bolster CLI)
validation_middleware.py# Friendly errors for bad tool arguments
availability.py         # Multi-calendar ICS free/busy merge behind check_availability
main.py                 # Stub — not a server entry point; run `python app.py`
test_app.py             # Resources, tools and server wiring (in-memory FastMCP Client)
tests/
├── test_click_mcp.py           # click_mcp against a fake CLI
├── test_bolster_integration.py # the real bolster CLI exposed as tools
└── fixtures/fake_cli/          # small Click app used by the click_mcp tests
deployment/             # nginx / systemd / webhook config (see README)
```

For the current resource and tool list, read `app.py`: `@mcp.resource(...)` and `@mcp.tool()` are the source of truth. Don't maintain a second list here.

## Architecture

- **Two servers, one tool set.** `mcp` is the public server (`/mcp`, no auth). `mcp_auth` (`/auth/mcp`, GitHub OAuth restricted to `GITHUB_ALLOWED_LOGINS`) `mount()`s `mcp` with no namespace, so it exposes the same tools live and adds `whoami`. Register tools on `mcp` only.
- **Mounting runs the mounted server's middleware chain.** A tool called through `mcp_auth` passes through both servers' middleware. `check_availability` decides its response tier from `get_access_token()`: a non-None token means `AuthMiddleware` already confirmed the login is allowlisted, so it returns full detail; anonymous callers on `/mcp` get free/busy only.
- **bolster tools are generated.** `register_click_commands(mcp, _bolster_cli, prefix="bolster", exclude={"list-sources"})` walks the Click tree and registers one tool per command (`bolster_<group>_<command>`), building wrappers with `exec()`. The registration sits in a `try/except ImportError`, so if `bolster` isn't installed the `bolster_*` tools silently disappear rather than failing startup — check `tests/test_bolster_integration.py` if a tool is missing.
- **Argument errors are rewritten.** `ToolValidationErrorMiddleware` catches pydantic `ValidationError` on tool calls and re-raises `ValueError` naming the bad argument and listing the valid ones, because small tool-calling models can't act on a raw pydantic trace. It is installed on both `mcp` and `mcp_auth`. `Client.call_tool` surfaces it as `ToolError`.
- **Dependency updates are automated.** `upgrade-bolster.yml` runs on the `bolster-release` repository dispatch and opens a lockfile-bump PR whenever `bolster` publishes.

## Commands

```bash
uv sync
uv run pytest -q                 # all tests (test_app.py + tests/); pytest-asyncio in auto mode
uv run pytest tests/test_click_mcp.py -q
uv run pre-commit run --all-files   # ruff, mypy, bandit
make test                        # lint + typecheck + security + pytest with coverage
uv run python app.py             # run the server
```

Tests use FastMCP's in-memory `Client(server)`; mock only external network (calendars, RSS, page fetches).

## Git workflow

Never commit to `main`; use a branch and a PR. Use `gh pr update-branch` to bring a PR up to date rather than rebasing or force-pushing it. Stage specific files (`git add <paths>`, not `-A`) — `.claude/worktrees/` can otherwise sneak in as gitlinks. Don't bypass hooks with `--no-verify`.

## Releases

`auto-release.yml` calls bolster's reusable `release-logic.yml` (conventional-commit prefixes → patch/minor; `docs:`/`ci:`/`chore:`/`style:`/`test:` don't release; `version:*` labels override, read from the newest commit's PR only). Here `block_major: false`, so a `type!:` commit *can* release a major. Manual `workflow_dispatch` with an explicit `version_bump` bypasses the analysis. The `chore: bump version` PR only syncs `pyproject.toml` back to `main` after the tag is pushed. See bolster's `AGENTS.md` for the release gotchas.

## CI

`test-and-coverage.yml` uses a two-tier concurrency design (keep it):

- A near-instant `queue` job holds one shared group (`cancel-in-progress: false`), which serialises runs across refs.
- The `test` matrix is `needs: queue` and has its own per-ref-per-matrix-cell group (`cancel-in-progress: true`), so a stale run for an old commit is cancelled once it's running.

A single shared group is not enough: GitHub cancels a ref's *own* queued entry when the same ref is pushed again, so a branch that is repeatedly rebased never reaches the front. Bolster's `pytest.yml` uses the same pattern.
