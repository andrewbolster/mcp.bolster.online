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
├── .github/
│   ├── workflows/
│   │   ├── test-and-coverage.yml  # Multi-platform testing with ARM64 & Windows 2025
│   │   ├── code-quality.yml       # Linting, formatting, security scans
│   │   ├── ai-content-review.yml  # AI-powered content validation using GitHub Models
│   │   └── fun-experiments.yml    # Experimental features & weekly stats
│   └── prompts/
│       └── content-review.yml     # Structured AI prompt for content analysis
└── htmlcov/                       # Generated coverage reports
```

## Key Features

### MCP Server Resources (app.py)
- `resource://andrew-bolster/personal-website` - Main website information
- `resource://andrew-bolster/professional-profile` - Current roles and background  
- `resource://andrew-bolster/farset-labs` - Belfast hackerspace information
- `resource://andrew-bolster/social-media` - Professional networking profiles
- `resource://andrew-bolster/research-interests` - Academic and technical focus
- `resource://andrew-bolster/community-involvement` - Organizational roles
- `resource://andrew-bolster/technical-blog` - Blog information and topics

### MCP Server Tools (app.py)
- `send_contact_message(message, sender)` - Contact tool with email integration placeholder
- `check_availability(start_date, days_ahead)` - Calendar availability via iCal feed parsing

## Development Commands

### Setup & Dependencies
```bash
# Install dependencies (uses modern uv package manager)
uv sync

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

# Current test coverage: 92%
# Missing coverage: iCal parsing edge cases, network error handling
```

## GitHub Actions Automation

### 🧪 Test & Coverage Workflow
- **Multi-platform testing**: Ubuntu, ARM64, Windows Server 2025 (preview)
- **Python versions**: 3.11, 3.12, 3.13
- **Coverage reporting**: Codecov integration with PR comments
- **Security scanning**: Bandit + Safety vulnerability checks
- **Performance benchmarks**: pytest-benchmark integration
- **Artifact preservation**: Test results and coverage reports

### 🔍 Code Quality Workflow  
- **Modern tooling**: Ruff (linting), Black (formatting), isort (imports), mypy (typing)
- **Automated fixes**: Auto-commits formatting to develop branch
- **Code analysis**: Radon complexity analysis with reports
- **Dependency security**: Automated dependency review on PRs

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

- **app.py**: Core MCP server with 6 resources + 2 tools, 92% test coverage
- **test_app.py**: Comprehensive test suite using FastMCP in-memory patterns  
- **.github/workflows/ai-content-review.yml**: Cutting-edge AI automation
- **.github/prompts/content-review.yml**: Professional AI content analysis prompt
- **pyproject.toml**: Modern Python project configuration with uv package manager

## Current Status: Production Ready

This MCP server is fully functional with:
- ✅ Comprehensive resource coverage about Andrew Bolster
- ✅ Working contact and availability tools
- ✅ 92% test coverage with modern testing practices  
- ✅ Full CI/CD automation with latest GitHub features
- ✅ AI-powered content maintenance
- ✅ Professional deployment documentation
- ✅ Extensive error handling and monitoring