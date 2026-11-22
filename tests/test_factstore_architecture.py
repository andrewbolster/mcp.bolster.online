"""The engine must stay extractable: it may not depend on MCP, a web framework or this application."""

import ast
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "factstore"
FORBIDDEN = {
    "fastmcp",
    "mcp",
    "starlette",
    "uvicorn",
    "httpx",
    "click",
    "app",
    "facts_tools",
    "availability",
    "click_mcp",
}


def imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("module", sorted(ENGINE.glob("*.py")), ids=lambda p: p.name)
def test_engine_modules_import_nothing_from_mcp_or_the_app(module):
    assert not imported_roots(module) & FORBIDDEN


def test_the_engine_uses_only_the_standard_library_and_itself():
    import sys

    allowed = set(sys.stdlib_module_names) | {"factstore"}
    for module in ENGINE.glob("*.py"):
        assert imported_roots(module) <= allowed, (module.name, imported_roots(module) - allowed)


def test_the_engine_package_is_found_where_the_tests_expect_it():
    assert (ENGINE / "store.py").exists()
    assert len(list(ENGINE.glob("*.py"))) >= 8
