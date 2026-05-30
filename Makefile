.PHONY: test lint fmt typecheck security all

# Full local smoke test — mirrors CI (code-quality + test-and-coverage workflows)
test: lint typecheck security
	uv run pytest test_app.py --cov=app --cov-report=term-missing -q

lint:
	uv run ruff check . --target-version=py311
	uv run ruff format --check --diff .

fmt:
	uv run ruff format .
	uv run ruff check . --fix --target-version=py311

typecheck:
	uv run mypy app.py --ignore-missing-imports

security:
	uv run --with bandit bandit -r app.py -q || true

all: fmt test
