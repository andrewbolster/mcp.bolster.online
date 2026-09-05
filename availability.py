"""Merged free/busy availability across multiple private ICS calendar feeds.

Calendar URLs are never stored in this repo. They're read from the
CALENDARS_CONFIG_JSON_B64 environment variable — base64-encoded, not raw
JSON. systemd's `Environment=` directive applies shell-like quote parsing
to its values and strips any `"` character it finds *anywhere* in the
string, not just at the edges — which silently corrupts raw JSON (all of
it, since every `"key":"value"` pair looks like a quoted token to it).
Base64's alphabet contains no `"`, `%`, or whitespace, so it round-trips
through `Environment=` (and its `%`-specifier expansion) intact. See
README.md's "Configuration & Secrets" section for the schema and how to
set it.

The fetch/merge/format logic itself lives in bolster.utils.calendars —
this module owns only the secret loading (CALENDARS_CONFIG_JSON_B64 is
specific to this deployment, not something a shared library should know
about) and the sync-to-async bridge, since bolster's function is
synchronous (requests-based) while MCP tools are async.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from asyncio import to_thread

from bolster.utils.calendars import get_merged_availability

CALENDARS_ENV_VAR = "CALENDARS_CONFIG_JSON_B64"


class AvailabilityNotConfiguredError(Exception):
    """CALENDARS_CONFIG_JSON_B64 is unset or empty on this deployment."""


def load_calendars() -> list[dict[str, str]]:
    """Load calendar name/url pairs from CALENDARS_CONFIG_JSON_B64.

    Raises:
        AvailabilityNotConfiguredError: if the env var is unset, empty, not
            valid base64, or doesn't decode to the expected
            {"calendars": [...]} shape.
    """
    raw = os.environ.get(CALENDARS_ENV_VAR, "")
    if not raw.strip():
        raise AvailabilityNotConfiguredError(f"{CALENDARS_ENV_VAR} is not set")
    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8")
        data = json.loads(decoded)
        calendars = data["calendars"]
        if not calendars:
            raise ValueError("calendars list is empty")
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        raise AvailabilityNotConfiguredError(f"{CALENDARS_ENV_VAR} is malformed: {e}") from e
    return calendars


async def get_availability(
    *,
    start_date: str | None,
    days_ahead: int,
    detailed: bool,
    tz_name: str = "Europe/London",
) -> str:
    """Top-level entry point used by the check_availability MCP tool."""
    calendars = load_calendars()
    return await to_thread(
        get_merged_availability,
        calendars,
        start_date=start_date,
        days_ahead=days_ahead,
        detailed=detailed,
        tz_name=tz_name,
    )
