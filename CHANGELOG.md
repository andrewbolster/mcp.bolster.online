# Changelog

## [0.2.0] - 2026-08-30

- feat: add upgrade-bolster workflow triggered by repository_dispatch (#12)
- fix: set HOME and remove contradictory ReadOnlyPaths in mcp-bolster service
- fix: use string comparison for is-active to match sudoers NOPASSWD rule
- fix: increase post-start sleep to 5s to allow service initialization
- fix: exec stdout to log file at startup to prevent SIGPIPE in child processes
- fix: set HOME=/opt/mcp.bolster.online instead of exposing /var/www/.cache
- fix: add /var/www/.cache to ReadWritePaths for www-data package caches
- fix: write deploy log directly to file to avoid SIGPIPE killing deploy.sh
- fix: add KillMode=process to prevent deploy.sh being killed on webhook restart
- fix: restart mcp-webhook after secret injection to restore hotreload watch
- fix: redirect XDG_CACHE_HOME/PRE_COMMIT_HOME to writable path under ProtectSystem=strict
- fix: increase MemoryMax to 512M to allow uv sync during deployment
- fix: set UV_CACHE_DIR within writable path for www-data under ProtectSystem=strict
- fix: use system uv path accessible to www-data
- fix: remove NoNewPrivileges from webhook service; add EnvironmentFile; guard secret in pre-commit
- fix: use git fetch+reset in deploy.sh; inject webhook secret; remove ggshield hook
- feat: generic Click CLI → MCP introspection harness (#8)
- Revert "feat: bearer token auth for admin tools (#10)"
- feat: bearer token auth for admin tools (#10)
- Bump the uv group across 1 directory with 9 updates (#7)
- feat: modernise to FastMCP 3.3.1 with async tools and structured output (#6)
- 📚 Update deployment documentation for enhanced webhook security
- 🔒 SECURITY: Implement proper webhook secret management
- 🔒 SECURITY: Implement GitHub Secrets for webhook configuration
- Add health check endpoints for monitoring and observability
- Fix critical deployment issues: PATH resolution and webhook security
- Sync deployment config: Fix webhook routing and add HTTPS support
- Fix nginx config: Add HTTPS support for webhook endpoint
- Fix tests: Use structure-based assertions instead of content-based
- Add RSS feed tool and update professional/community resources
- Fix GitHub Actions workflows: Add push triggers, timeouts, and error handling
- fix ports
- Remove ARM64 testing and experimental features for core focus
- Update README badges with accurate GitHub Actions status
- Improve GitHub Actions stability and deployment configuration
- fix deploy to use fastmcp instead of implied app.py
- Add comprehensive deployment configuration files
- Update documentation to reflect current project status
- Remove Windows Server 2025 from test matrix
- Switch to Ruff and set up pre-commit hooks
- 🔍 Fix mypy type checking issues
- 📤 Fix import sorting with isort
- 🎨 Apply Black code formatting
- 🔧 Fix linting issues: remove unused imports and variables
- 🚀 Complete MCP Server Implementation with AI-Powered GitHub Actions
- Initial commit


All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## \[Unreleased\]

### Added

- `get_recent_blog_posts` tool for fetching posts from Andrew Bolster's RSS feed
- `CHANGELOG.md` to track project changes
- Project metadata: classifiers, license, author info in `pyproject.toml`
- `mdformat` pre-commit hook for consistent Markdown formatting
- `for-the-badge` style badges aligned with bolster project

### Changed

- Moved dev/test dependencies (`pre-commit`, `pytest*`) from runtime to `[dependency-groups]`
- Static coverage badge replaced with dynamic Codecov badge
- Static Python version badge replaced with dynamic PyPI badge
- Badge style unified to `for-the-badge` across all shields.io badges
- Tool count corrected from 2 to 3 in README

### Fixed

- README description of available MCP tools (was missing `get_recent_blog_posts`)
- `pyproject.toml` placeholder description updated to accurate project description

## \[0.1.0\] - 2024-01-01

### Added

- Initial MCP server implementation using FastMCP
- 7 MCP resources: personal website, professional profile, Farset Labs, social media, research interests, community involvement, technical blog
- 2 MCP tools: `send_contact_message`, `check_availability` (iCal feed)
- GitHub Actions workflows: test-and-coverage, code-quality, ai-content-review, fun-experiments
- Pre-commit hooks: ruff, mypy, bandit, ggshield, standard file checks
- nginx + webhook deployment configuration
- Multi-platform CI (Ubuntu latest + 22.04, Python 3.11–3.13)
