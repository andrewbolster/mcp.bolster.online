# Changelog

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
