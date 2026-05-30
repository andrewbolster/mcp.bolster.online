"""
click_mcp.py — Generic Click-to-FastMCP introspection harness.

Given any Click group, walks the command tree and registers each leaf command
as a FastMCP tool. Parameters are mapped to Python type annotations so FastMCP
can generate proper JSON schemas for LLM clients.

Usage:
    from click_mcp import register_click_commands
    from mypackage.cli import cli as my_cli
    from fastmcp import FastMCP

    mcp = FastMCP(name="My Server")
    register_click_commands(mcp, my_cli, prefix="my")
"""

from typing import Any

import click
from click.testing import CliRunner
from fastmcp import FastMCP


def _click_type_to_python(param: click.Parameter) -> type:
    """Map a Click parameter type to the closest Python type annotation."""
    t = param.type
    if isinstance(t, click.Choice):
        return str
    if isinstance(t, click.types.IntParamType | click.types.IntRange):
        return int
    if isinstance(t, click.types.FloatParamType | click.types.FloatRange):
        return float
    if isinstance(t, click.types.BoolParamType):
        return bool
    # Choice, Path, File, etc. → str
    return str


def _is_flag(param: click.Parameter) -> bool:
    return isinstance(param, click.Option) and getattr(param, "is_flag", False)


def _is_internal(param: click.Parameter) -> bool:
    """Skip params that are implementation details, not useful to an LLM."""
    skip = {"save", "output_format", "table_deprecated"}
    return param.name in skip


def _sentinel_is_unset(value: Any) -> bool:
    """Click uses a Sentinel object for 'not provided' defaults."""
    return type(value).__name__ == "Sentinel"


def _build_tool_fn(
    root_group: click.Group, command_path: list[str], params: list[click.Parameter]
):
    """
    Build a callable that invokes a Click command via CliRunner and returns stdout.
    The callable's __annotations__ are set so FastMCP can generate a proper schema.
    """
    annotations: dict[str, Any] = {}
    defaults: dict[str, Any] = {}

    for p in params:
        if _is_internal(p) or p.name is None:
            continue
        py_type = _click_type_to_python(p)
        if _is_flag(p):
            py_type = bool
        # Optional if not required and has no non-sentinel default
        if not p.required:
            annotations[p.name] = py_type | None
            default = p.default
            defaults[p.name] = None if _sentinel_is_unset(default) else default
        else:
            annotations[p.name] = py_type

    annotations["return"] = str

    def tool_fn(**kwargs):
        args = []
        positional_args = []
        for p in params:
            if _is_internal(p):
                continue
            val = kwargs.get(p.name)
            if val is None:
                continue
            if isinstance(p, click.Argument):
                positional_args.append(str(val))
                continue
            flag_name = f"--{p.name.replace('_', '-')}"
            if _is_flag(p):
                if val:
                    args.append(flag_name)
            else:
                args.extend([flag_name, str(val)])
        args.extend(positional_args)

        runner = CliRunner()
        result = runner.invoke(root_group, command_path + args, catch_exceptions=False)
        output = result.output.strip()
        if result.exit_code != 0:
            err = getattr(result, "stderr", "") or ""
            return f"Error (exit {result.exit_code}):\n{err or output}"
        return output or "(no output)"

    tool_fn.__annotations__ = annotations
    return tool_fn, defaults


def _walk_and_register(
    mcp: FastMCP,
    group: click.Command | click.Group,
    root_group: click.Group,
    path: list[str],
    prefix: str,
):
    """Recursively walk the Click command tree, registering leaf commands as tools."""
    if isinstance(group, click.Group):
        for name, sub in group.commands.items():
            _walk_and_register(mcp, sub, root_group, path + [name], prefix)
        return

    # Leaf command — register as a tool
    cmd = group
    tool_name_parts = ([prefix] if prefix else []) + path
    tool_name = "_".join(p.replace("-", "_") for p in tool_name_parts)

    # Build docstring from command help + param help
    doc_parts = [cmd.help or f"Run the `{' '.join(path)}` command."]
    visible_params = [p for p in cmd.params if not _is_internal(p)]
    if visible_params:
        doc_parts.append("\nParameters:")
        for p in visible_params:
            help_txt = getattr(p, "help", None) or ""
            choices = (
                f" Choices: {p.type.choices}"
                if isinstance(p.type, click.Choice)
                else ""
            )
            default = p.default
            default_str = (
                "" if _sentinel_is_unset(default) else f" Default: {default!r}."
            )
            doc_parts.append(f"  {p.name}: {help_txt}{choices}{default_str}")
    docstring = "\n".join(doc_parts)

    tool_fn, defaults = _build_tool_fn(root_group, path, cmd.params)
    tool_fn.__name__ = tool_name
    tool_fn.__doc__ = docstring

    # Build keyword-argument wrapper so FastMCP sees named params, not **kwargs
    # FastMCP inspects the function signature; we need real named args with defaults.
    sig_params = []
    for p in visible_params:
        if p.name is None:
            continue
        name = p.name
        if name in defaults:
            sig_params.append(f"{name}=defaults['{name}']")
        else:
            sig_params.append(name)

    # Always build a named-param wrapper — FastMCP rejects **kwargs signatures.
    fn_args = ", ".join(sig_params)
    call_args = ", ".join(f"{p.name}={p.name}" for p in visible_params)
    if sig_params:
        wrapper_src = f"def _wrapper({fn_args}):\n    return tool_fn({call_args})\n"
    else:
        wrapper_src = "def _wrapper():\n    return tool_fn()\n"
    ns: dict[str, Any] = {"tool_fn": tool_fn, "defaults": defaults}
    exec(wrapper_src, ns)  # noqa: S102  # nosec B102
    wrapper = ns["_wrapper"]
    wrapper.__name__ = tool_name
    wrapper.__doc__ = docstring
    wrapper.__annotations__ = {
        k: v for k, v in tool_fn.__annotations__.items() if k != "return"
    }
    wrapper.__annotations__["return"] = str
    mcp.tool(name=tool_name)(wrapper)


def register_click_commands(
    mcp: FastMCP,
    root: click.Group,
    *,
    prefix: str = "",
    exclude: set[str] | None = None,
) -> list[str]:
    """
    Walk a Click command group and register every leaf command as an MCP tool.

    Args:
        mcp: The FastMCP server to register tools on.
        root: The root Click group to introspect.
        prefix: Optional prefix for all tool names (e.g. the package name).
        exclude: Set of top-level command names to skip.

    Returns:
        List of registered tool names.
    """
    exclude = exclude or set()
    registered: list[str] = []

    for name, cmd in root.commands.items():
        if name in exclude:
            continue
        _walk_and_register(mcp, cmd, root, [name], prefix)

    return registered
