"""SQL fragments for ``search_facts``: time filters, date-valued objects, ordering and grouping.

Every function returns SQL text built only from fixed fragments plus ``?`` placeholders, with the values in a
separate list, so nothing a caller supplies is ever spliced into a statement.
"""

import re
from datetime import date
from typing import Any

from .errors import ValidationError
from .values import iso, parse_instant

ORDER_DIRECTIONS = ("asc", "desc")

#: ``order_by`` choices and the column each sorts on. Facts with no value (a missing period, never updated) sort last
#: in either direction. ``valid_from``/``valid_to`` sort on the stored sortable keys, ``object`` on the folded name,
#: which is chronological for ISO dates of the same precision.
ORDER_COLUMNS = {
    "created_at": "created_at",
    "updated_at": "updated_at",
    "confidence": "confidence",
    "valid_from": "valid_from_key",
    "valid_to": "valid_to_key",
    "object": "object_f",
}

#: ``group_by`` choices and the SQL that identifies a group. A name's group is its kind and folded name, so the same
#: name under two kinds is two groups.
GROUP_KEYS = {
    "subject": "COALESCE(subject_kind, '') || char(31) || subject_f",
    "action": "action_f",
    "object": "COALESCE(object_kind, '') || char(31) || object_f",
    "subject_kind": "COALESCE(subject_kind, '')",
    "object_kind": "COALESCE(object_kind, '')",
}

PICKS = ("latest", "oldest", "highest_confidence")

#: A date-kind object in one of the three shapes the store writes (``YYYY``, ``YYYY-MM``, ``YYYY-MM-DD``). A date
#: with no year (``--MM-DD``) has no place on a timeline, so it never matches a range.
DATE_SHAPE = (
    "(object_kind = 'date' AND (object GLOB '[0-9][0-9][0-9][0-9]' "
    "OR object GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]' "
    "OR object GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'))"
)
#: The first and last day a date value covers, padded to ``YYYY-MM-DD`` so plain text comparison orders them. A month
#: ends at ``-31`` whatever its length: no real day of that month sorts after it and none of the next month before it.
DATE_FIRST = "CASE length(object) WHEN 4 THEN object || '-01-01' WHEN 7 THEN object || '-01' ELSE object END"
DATE_LAST = "CASE length(object) WHEN 4 THEN object || '-12-31' WHEN 7 THEN object || '-31' ELSE object END"

#: ``pick_by`` choices for ``group_by``: what ``latest`` and ``oldest`` compare. ``object`` is the date the object
#: holds (facts whose object is not a date rank last).
PICK_BY = {
    "created_at": "created_at",
    "object": f"CASE WHEN {DATE_SHAPE} THEN {DATE_FIRST} END",
    "valid_from": "valid_from_key",
    "valid_to": "valid_to_key",
}

_DATE_FORMS = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def check_choice(label: str, value: Any, choices: Any) -> str | None:
    """``value`` if it is one of ``choices`` (None passes through), else an error that lists the choices."""
    if value is None:
        return None
    if not isinstance(value, str) or value.strip().lower() not in choices:
        raise ValidationError(f"{label} must be one of {', '.join(choices)}; got {value!r}.")
    return value.strip().lower()


def time_clauses(
    *,
    created_since: str | None = None,
    created_before: str | None = None,
    updated_since: str | None = None,
    changed_since: str | None = None,
) -> tuple[list[str], list[Any]]:
    """Filters on when facts were created or last edited (UTC, a coarse value meaning the start of its period).

    ``created_since`` keeps facts created at or after the time, ``created_before`` those created before it,
    ``updated_since`` those edited at or after it (a fact never edited has no update time and is left out), and
    ``changed_since`` those created or edited at or after it.
    """
    where: list[str] = []
    params: list[Any] = []
    if created_since is not None:
        where.append("created_at >= ?")
        params.append(iso(parse_instant(created_since)))
    if created_before is not None:
        where.append("created_at < ?")
        params.append(iso(parse_instant(created_before)))
    if updated_since is not None:
        where.append("(updated_at IS NOT NULL AND updated_at >= ?)")
        params.append(iso(parse_instant(updated_since)))
    if changed_since is not None:
        moment = iso(parse_instant(changed_since))
        where.append("(created_at >= ? OR (updated_at IS NOT NULL AND updated_at >= ?))")
        params.extend([moment, moment])
    return where, params


def date_bound(label: str, value: Any, *, end: bool) -> str:
    """A bound for a date-valued object range as padded ``YYYY-MM-DD`` text (the first day of a start bound, the last
    day of an end bound, so ``object_to='2026-11'`` includes the whole of November)."""
    text = value.strip() if isinstance(value, str) else ""
    if not _DATE_FORMS.match(text):
        raise ValidationError(
            f"{label} must be YYYY, YYYY-MM or YYYY-MM-DD; got {value!r}. A date with no year (--MM-DD) has no place on a timeline."
        )
    try:  # rejects impossible dates such as 2026-02-30, 2026-13 or year 0 (and accepts 9999, a handy "no limit")
        date(int(text[:4]), int(text[5:7] or 1), int(text[8:10] or 1))
    except ValueError:
        raise ValidationError(f"{label} {value!r} is not a calendar date. Use YYYY, YYYY-MM or YYYY-MM-DD.") from None
    if len(text) == 4:
        return text + ("-12-31" if end else "-01-01")
    if len(text) == 7:
        return text + ("-31" if end else "-01")
    return text


def date_clauses(object_from: str | None, object_to: str | None, object_within: bool) -> tuple[list[str], list[Any]]:
    """Filters on facts whose object is a date, within the window ``[object_from, object_to]`` (both inclusive).

    Only date-kind objects of the shapes ``YYYY``, ``YYYY-MM`` and ``YYYY-MM-DD`` can match; every other fact is
    left out, as is a date with no year. A coarse value covers its whole period, so ``2026`` overlaps a window that
    falls in 2026; by default a value matches when its period OVERLAPS the window, and with ``object_within`` only
    when it lies ENTIRELY inside it (so ``2026`` does not match a window that is one month of 2026).
    """
    if object_within and object_from is None and object_to is None:
        raise ValidationError("object_within needs object_from and/or object_to: the window the date must fit.")
    if object_from is None and object_to is None:
        return [], []
    where: list[str] = [DATE_SHAPE]
    params: list[Any] = []
    if object_from is not None:
        low = date_bound("object_from", object_from, end=False)
        where.append(f"({DATE_FIRST if object_within else DATE_LAST}) >= ?")
        params.append(low)
    if object_to is not None:
        high = date_bound("object_to", object_to, end=True)
        where.append(f"({DATE_LAST if object_within else DATE_FIRST}) <= ?")
        params.append(high)
    return where, params


def order_sql(
    order_by: str | None, order: str | None, *, grouped: bool = False, rowid: str = "rowid"
) -> tuple[str, str | None]:
    """An ``ORDER BY`` list (default: newest created first) and the validated ``order_by`` name.

    ``order_by`` is one of ``ORDER_COLUMNS`` (and ``group_count`` for grouped results); ``order`` is ``asc`` or
    ``desc`` (default ``desc``). Ties fall back to newest first, so a page is stable.
    """
    choices = (*ORDER_COLUMNS, "group_count") if grouped else tuple(ORDER_COLUMNS)
    name = check_choice("order_by", order_by, choices)
    direction = (check_choice("order", order, ORDER_DIRECTIONS) or "desc").upper()
    if name is None and order is not None:
        name = "created_at"  # an ``order`` alone reorders the default sort
    if name is None:
        return f"created_at DESC, {rowid} DESC", None
    if name == "created_at":
        return f"created_at {direction}, {rowid} {direction}", name
    column = "group_count" if name == "group_count" else ORDER_COLUMNS[name]
    return f"({column} IS NULL), {column} {direction}, created_at DESC, {rowid} DESC", name


def pick_sql(pick: str, pick_by: str | None, *, rowid: str = "rowid") -> str:
    """The ordering inside each group: the first row is the one that is kept."""
    if pick == "highest_confidence":
        return f"confidence DESC, created_at DESC, {rowid} DESC"
    expression = PICK_BY[pick_by or "created_at"]
    if pick == "latest":
        return f"(({expression}) IS NULL), ({expression}) DESC, created_at DESC, {rowid} DESC"
    return f"(({expression}) IS NULL), ({expression}) ASC, created_at ASC, {rowid} ASC"
