# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a fully-featured MCP (Model Context Protocol) server providing curated resources and tools about Andrew Bolster, built with FastMCP framework. The project includes comprehensive testing, CI/CD automation, and AI-powered content validation.

## Repository Structure

```
├── app.py                          # Main MCP server implementation
├── test_app.py                     # Comprehensive pytest test suite (92% coverage)
├── pyproject.toml                  # Modern Python project configuration with uv
├── main.py                         # Alternative server entry point
├── README.md                       # Comprehensive project documentation
├── .pre-commit-config.yaml         # Pre-commit hooks for code quality
├── .github/
│   ├── workflows/
│   │   ├── test-and-coverage.yml  # Multi-platform testing (Ubuntu x64/ARM64)
│   │   ├── code-quality.yml       # Ruff linting/formatting, mypy, complexity analysis
│   │   ├── ai-content-review.yml  # AI-powered content validation using GitHub Models
│   │   └── fun-experiments.yml    # Experimental features & weekly stats
│   └── prompts/
│       └── content-review.yml     # Structured AI prompt for content analysis
└── htmlcov/                       # Generated coverage reports
```

## Key Features

### MCP Server Resources (app.py) - 7 Available
- `resource://andrew-bolster/personal-website` - Main website information
- `resource://andrew-bolster/professional-profile` - Current roles and background
- `resource://andrew-bolster/farset-labs` - Belfast hackerspace information
- `resource://andrew-bolster/social-media` - Professional networking profiles
- `resource://andrew-bolster/research-interests` - Academic and technical focus
- `resource://andrew-bolster/community-involvement` - Organizational roles
- `resource://andrew-bolster/technical-blog` - Blog information and topics

### MCP Server Tools (app.py) - 2 Available
- `send_contact_message(message, sender)` - Contact tool with email integration placeholder
- `check_availability(start_date, days_ahead)` - Calendar availability via iCal feed parsing

## Development Commands

### Setup & Dependencies
```bash
# Install dependencies (uses modern uv package manager)
uv sync

# Install pre-commit hooks for automatic code quality
uv run pre-commit install

# Run the MCP server
uv run python app.py
```

### Testing & Quality
```bash
# Run tests with coverage
uv run pytest test_app.py -v
uv run pytest test_app.py --cov=app --cov-report=term-missing

# Generate HTML coverage report
uv run pytest test_app.py --cov=app --cov-report=html

# Code quality checks (same as CI)
uv run ruff check .              # Linting
uv run ruff format --check .     # Format checking
uv run mypy app.py --ignore-missing-imports  # Type checking

# Pre-commit hooks (runs automatically)
uv run pre-commit install        # Setup
uv run pre-commit run --all-files # Manual run

# Current test coverage: 92%
# Missing coverage: iCal parsing edge cases, network error handling
```

## GitHub Actions Automation

### 🧪 Test & Coverage Workflow
- **Multi-platform testing**: Ubuntu (latest, 22.04), ARM64 (24.04)
- **Python versions**: 3.11, 3.12, 3.13
- **Coverage reporting**: Codecov integration with PR comments
- **Security scanning**: Bandit + Safety vulnerability checks
- **Performance benchmarks**: pytest-benchmark integration
- **Artifact preservation**: Test results and coverage reports
- **Removed Windows**: Windows Server 2025 preview had dependency issues

### 🔍 Code Quality Workflow
- **Modern tooling**: Ruff (linting + formatting), mypy (type checking)
- **Pre-commit integration**: Automatic quality checks on every commit
- **Code analysis**: Radon complexity analysis with GitHub Actions summaries
- **Dependency security**: Automated dependency review on PRs
- **Performance**: Single tool (Ruff) replaces Black + isort + flake8 for speed

### 🤖 AI Content Review Workflow
- **GitHub Models integration**: Uses latest AI models (GPT-4o-mini, Llama, Mistral)
- **Content validation**: Automatically reviews MCP resources for accuracy
- **Web verification**: Checks andrewbolster.info for current information
- **Smart scheduling**: Monthly reviews with manual trigger options
- **Issue automation**: Creates GitHub issues when content needs updating
- **Structured prompts**: Professional AI guidance via .github/prompts/

### 🎮 Fun Experiments Workflow
- **ARM64 performance**: Benchmarking on new GitHub ARM runners
- **Dynamic badges**: Real-time project statistics generation
- **Health checks**: MCP server functionality validation
- **Weekly reports**: Automated repository analytics
- **GitHub Models playground**: Experimental AI features

## Architecture Notes

### FastMCP Implementation
- **Server Framework**: Uses FastMCP for modern MCP development
- **Async Support**: Full async/await pattern with proper error handling
- **Resource Pattern**: Structured resource definitions with comprehensive content
- **Tool Pattern**: Type-safe tool implementations with validation

### Testing Strategy
- **In-memory testing**: Direct FastMCP Client-Server connection for speed
- **Mock integration**: unittest.mock for external dependencies (iCal, requests)
- **Coverage targets**: Aiming for 95%+ coverage with meaningful tests
- **Performance testing**: Benchmarking critical paths

### AI Integration
- **Content validation**: Monthly AI-powered reviews of resource accuracy
- **GitHub Models**: Integration with latest GitHub AI features
- **Structured prompts**: Professional prompt engineering in version control
- **Automated maintenance**: Smart issue creation for content updates

## Development Workflow

1. **Local Development**: Use `uv` for fast dependency management and testing
2. **Quality Gates**: Ruff, Black, mypy run automatically on push
3. **Testing**: Comprehensive test suite runs on multiple platforms
4. **AI Review**: Monthly content validation with actionable recommendations
5. **Deployment**: nginx + webhook deployment documentation provided

## Important Files to Understand

- **app.py**: Core MCP server with 7 resources + 2 tools, 92% test coverage
- **test_app.py**: Comprehensive test suite using FastMCP in-memory patterns
- **.github/workflows/ai-content-review.yml**: Cutting-edge AI automation
- **.github/prompts/content-review.yml**: Professional AI content analysis prompt
- **pyproject.toml**: Modern Python project configuration with uv package manager

## Technical Decisions Made

### Code Quality Evolution
- **Switched from Black + isort to Ruff**: Single tool for linting and formatting (faster, simpler)
- **Pre-commit hooks**: Automatic code quality enforcement with comprehensive checks
- **Modern type annotations**: Updated from `Dict`/`Optional` to `dict`/`|` syntax
- **Ruff configuration**: Allows long lines in docstrings/strings for better readability

### Platform Support
- **Removed Windows Server 2025**: Preview OS had dependency installation issues
- **Added ARM64 testing**: Testing on GitHub's new ARM64 runners
- **Ubuntu focus**: Reliable cross-version compatibility (latest, 22.04, 24.04)

## Current Status: Production Ready

This MCP server is fully functional with:
- ✅ Comprehensive resource coverage about Andrew Bolster (7 resources)
- ✅ Working contact and availability tools (2 tools)
- ✅ 92% test coverage with modern testing practices
- ✅ Full CI/CD automation with cutting-edge GitHub features
- ✅ AI-powered content maintenance and validation
- ✅ Modern code quality tooling (Ruff + pre-commit)
- ✅ Professional deployment documentation (nginx + webhooks)
- ✅ Cross-platform compatibility and extensive error handling
