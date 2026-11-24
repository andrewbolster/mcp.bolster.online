"""Result shaping shared by every list call: field projection and the compact tabular format.

A list call returns its rows as dicts (``format="full"``, the default and unchanged) or as ``columns`` plus ``rows``
of plain lists (``format="compact"``), which is several times smaller for a client that reads the reply as text. In
both formats ``fields`` names the fields to return; without it, full returns everything and compact returns a short
default set (no attributes or references unless they are named).
"""

from collections.abc import Iterable, Sequence
from typing import Any

from .errors import ValidationError

FORMATS = ("full", "compact")

#: Every field of a fact as returned by the engine (the order a ``fields`` list may use).
FACT_FIELDS = (
    "id",
    "subject",
    "subject_kind",
    "subject_ref",
    "action",
    "object",
    "object_kind",
    "object_ref",
    "confidence",
    "valid_from",
    "valid_to",
    "public",
    "attributes",
    "references",
    "created_by",
    "created_at",
    "updated_by",
    "updated_at",
    "reviewed_by",
    "reviewed_at",
)

#: The columns of a compact fact list when ``fields`` is not given: the triple, how sure, and when it holds.
COMPACT_FACT_FIELDS = ("id", "subject_ref", "action", "object_ref", "confidence", "valid_from", "valid_to")

#: Added to a fact's fields when it stands for a group of facts (``group_by``).
GROUP_FIELD = "group_count"


def check_format(value: Any) -> str:
    """``full`` or ``compact`` (None means ``full``)."""
    if value is None:
        return "full"
    if not isinstance(value, str) or value.strip().lower() not in FORMATS:
        raise ValidationError(f"format must be one of {', '.join(FORMATS)}; got {value!r}.")
    return value.strip().lower()


def check_fields(value: Any, allowed: Sequence[str], label: str = "fields") -> tuple[str, ...] | None:
    """The requested fields in the order given, or None when none were requested.

    A single comma-separated string is accepted as a list. A name that is not in ``allowed`` is an error that lists
    the valid ones, so a caller can fix the request without guessing.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, list | tuple) or not value or not all(isinstance(item, str) for item in value):
        raise ValidationError(f"{label} must be a non-empty list of field names. Valid fields: {', '.join(allowed)}.")
    chosen: list[str] = []
    for item in value:
        name = item.strip()
        if name not in allowed:
            raise ValidationError(f"Unknown field {name!r} in {label}. Valid fields: {', '.join(allowed)}.")
        if name not in chosen:
            chosen.append(name)
    return tuple(chosen)


def shape_rows(
    rows: Iterable[dict[str, Any]],
    *,
    key: str,
    fmt: str,
    fields: tuple[str, ...] | None,
    compact_default: Sequence[str],
) -> dict[str, Any]:
    """The part of a reply that holds the rows: ``{key: [dict, ...]}`` or ``{columns: [...], rows: [[...], ...]}``.

    ``rows`` are full dicts. In ``full`` format ``fields`` (if given) trims each dict to those fields, in that order.
    In ``compact`` format the columns are ``fields`` or ``compact_default``, and each row is a list in column order.
    """
    if fmt == "compact":
        columns = list(fields or compact_default)
        return {"columns": columns, "rows": [[row.get(column) for column in columns] for row in rows]}
    if fields is None:
        return {key: list(rows)}
    return {key: [{name: row.get(name) for name in fields} for row in rows]}
