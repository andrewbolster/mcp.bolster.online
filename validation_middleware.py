"""
validation_middleware.py — Rewrite tool-call argument validation errors into
messages a small tool-calling model can actually act on.

FastMCP validates incoming tool-call arguments against the tool's function
signature using a pydantic ``TypeAdapter`` (see ``FunctionTool.run`` in
fastmcp's ``tools/function_tool.py``). When a client passes an argument that
doesn't exist on the tool, the resulting ``pydantic.ValidationError`` — a
multi-line dump ending in a pydantic.dev docs URL — is what gets sent back to
the client as the tool-call error message, unmodified.

That's fine for a human debugging a script, but useless as feedback for a
model deciding what to try next. Observed live: granite-4.0-h-micro invented
a `latest` kwarg on a bolster CLI tool and, given only the raw pydantic
trace, repeated the identical failing call five times in one conversation —
even after independently fetching the tool's own documentation, which
correctly listed the real argument names. See issue #19.

``ToolValidationErrorMiddleware`` intercepts exactly this case at the
``on_call_tool`` hook (which wraps the whole tool dispatch, including the
pydantic validation step) and replaces "unexpected keyword argument" errors
with a plain sentence naming the bad argument(s) and the tool's actual valid
argument names. Other validation failures (missing required argument, wrong
type) get a still-improved but more generic message, since those are rarer
in practice and pydantic's own text for them is closer to actionable already.
"""

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp.types import CallToolRequestParams
from pydantic import ValidationError


class ToolValidationErrorMiddleware(Middleware):
    """Reformat tool-call argument validation errors for small tool-calling models."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, object],
    ) -> object:
        try:
            return await call_next(context)
        except ValidationError as exc:
            raise ValueError(await self._friendly_message(context, exc)) from exc

    async def _friendly_message(self, context: MiddlewareContext[CallToolRequestParams], exc: ValidationError) -> str:
        tool_name = context.message.name

        valid_params: list[str] = []
        if context.fastmcp_context is not None:
            tool = await context.fastmcp_context.fastmcp.get_tool(tool_name)
            if tool is not None and tool.parameters:
                valid_params = list(tool.parameters.get("properties", {}).keys())
        valid_str = ", ".join(valid_params) if valid_params else "(none)"

        errors = exc.errors(include_url=False)
        unknown = [str(e["loc"][-1]) for e in errors if e["type"] == "unexpected_keyword_argument" and e["loc"]]

        if unknown and len(unknown) == len(errors):
            # Every error is an unknown argument -- the common case (a model
            # inventing a kwarg name). Name it directly rather than making
            # the model parse a generic error list.
            named = ", ".join(repr(name) for name in unknown)
            return f"Unknown argument(s) {named} for tool {tool_name!r}. Valid arguments: {valid_str}."

        # Mixed or non-"unknown argument" failures (missing required, wrong
        # type): still name the tool and its valid arguments, but fall back
        # to pydantic's own per-field messages rather than guessing a
        # one-size-fits-all sentence for cases this hasn't been tuned for.
        details = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in errors)
        return f"Invalid arguments for tool {tool_name!r} ({details}). Valid arguments: {valid_str}."
