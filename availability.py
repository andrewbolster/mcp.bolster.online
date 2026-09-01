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
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import recurring_ical_events
from icalendar import Calendar

CALENDARS_ENV_VAR = "CALENDARS_CONFIG_JSON_B64"

# Severity order: higher wins when calendars overlap for the same time slot.
FREE, TENTATIVE, BUSY = 0, 1, 2
SEVERITY_LABEL = {FREE: "free", TENTATIVE: "tentative", BUSY: "busy"}


class AvailabilityNotConfiguredError(Exception):
    """CALENDARS_CONFIG_JSON_B64 is unset or empty on this deployment."""


@dataclass
class Interval:
    start: datetime
    end: datetime
    severity: int
    calendar: str
    summary: str


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


async def fetch_ics(name: str, url: str, client: httpx.AsyncClient) -> Calendar | None:
    try:
        resp = await client.get(url, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        return Calendar.from_ical(resp.content)
    except Exception:  # noqa: BLE001 — one calendar failing shouldn't sink the whole request
        return None


def event_severity(component) -> int:  # noqa: ANN001 — icalendar's Event type isn't meaningfully more specific
    """Classify a VEVENT as busy / tentative / free."""
    transp = str(component.get("TRANSP", "")).upper()
    if transp == "TRANSPARENT":
        return FREE

    # Outlook/Exchange-specific busy status, most authoritative when present.
    ms_status = str(component.get("X-MICROSOFT-CDO-BUSYSTATUS", "")).upper()
    if ms_status == "FREE":
        return FREE
    if ms_status == "TENTATIVE":
        return TENTATIVE
    if ms_status in ("BUSY", "OOF"):
        return BUSY

    status = str(component.get("STATUS", "")).upper()
    if status == "CANCELLED":
        return FREE
    if status == "TENTATIVE":
        return TENTATIVE

    # Fall back to the calendar owner's own PARTSTAT among attendees, if present.
    attendees = component.get("ATTENDEE")
    if attendees:
        if not isinstance(attendees, list):
            attendees = [attendees]
        for att in attendees:
            partstat = str(att.params.get("PARTSTAT", "")).upper()
            if partstat == "TENTATIVE":
                return TENTATIVE
            if partstat == "DECLINED":
                return FREE

    return BUSY  # default: an untransparent, unconfirmed-otherwise event blocks time


def _to_aware(dt: date | datetime, tz: ZoneInfo) -> datetime:
    """Normalise a date/datetime (icalendar gives naive dates for all-day events) to aware datetime."""
    if isinstance(dt, datetime):
        return dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)
    return datetime.combine(dt, time.min, tzinfo=tz)


async def collect_intervals(
    calendars: list[dict[str, str]],
    window_start: datetime,
    window_end: datetime,
    tz: ZoneInfo,
    client: httpx.AsyncClient,
) -> list[Interval]:
    intervals: list[Interval] = []
    for cal in calendars:
        name, url = cal["name"], cal["url"]
        ical = await fetch_ics(name, url, client)
        if ical is None:
            continue
        for component in recurring_ical_events.of(ical).between(window_start, window_end):
            severity = event_severity(component)
            if severity == FREE:
                continue
            start = _to_aware(component["DTSTART"].dt, tz)
            end_prop = component.get("DTEND")
            end = _to_aware(end_prop.dt, tz) if end_prop else start + timedelta(hours=1)
            summary = str(component.get("SUMMARY", "(no title)"))
            intervals.append(Interval(start, end, severity, name, summary))
    return intervals


def merge_timeline(intervals: list[Interval], window_start: datetime, window_end: datetime) -> list[Interval]:
    """Sweep-line merge: at every point, keep the highest severity active, tag with contributing calendars."""
    if not intervals:
        return []

    boundaries = sorted({i.start for i in intervals} | {i.end for i in intervals} | {window_start, window_end})
    boundaries = [b for b in boundaries if window_start <= b <= window_end]

    segments: list[Interval] = []
    for seg_start, seg_end in zip(boundaries, boundaries[1:], strict=False):
        if seg_start >= seg_end:
            continue
        mid = seg_start + (seg_end - seg_start) / 2
        active = [i for i in intervals if i.start <= mid < i.end]
        if not active:
            continue
        top_severity = max(i.severity for i in active)
        contributors = sorted({i.calendar for i in active if i.severity == top_severity})
        summaries = sorted({i.summary for i in active if i.severity == top_severity})
        segments.append(Interval(seg_start, seg_end, top_severity, "+".join(contributors), "; ".join(summaries)))

    # Merge adjacent segments with identical severity + contributors.
    merged: list[Interval] = []
    for seg in segments:
        prev = merged[-1] if merged else None
        if prev and prev.end == seg.start and prev.severity == seg.severity and prev.calendar == seg.calendar:
            merged[-1] = Interval(prev.start, seg.end, seg.severity, seg.calendar, prev.summary)
        else:
            merged.append(seg)
    return merged


def format_timeline(
    merged: list[Interval],
    window_start: datetime,
    window_end: datetime,
    *,
    detailed: bool,
) -> str:
    """Render the merged timeline as text.

    detailed=True includes which calendar and the event title — reserved
    for the calendar owner. detailed=False collapses everything to plain
    free/busy/tentative time ranges with no source or content, safe to show
    to anyone.
    """
    header = f"Availability {window_start:%Y-%m-%d %H:%M} to {window_end:%Y-%m-%d %H:%M} ({window_start.tzname()}):"
    if not merged:
        return f"{header}\n\n✅ No busy or tentative time found — fully free."

    lines = [header, ""]
    current_day = None
    for seg in merged:
        day = seg.start.date()
        if day != current_day:
            current_day = day
            lines.append(f"{day.strftime('%A %d %B')}")
        label = SEVERITY_LABEL[seg.severity].upper()
        line = f"  {seg.start.strftime('%H:%M')}-{seg.end.strftime('%H:%M')}  {label}"
        if detailed:
            line += f"  [{seg.calendar}] {seg.summary}"
        lines.append(line)

    if not detailed:
        lines.append("")
        lines.append("Note: showing free/busy only. Calendar source and event details are private.")

    return "\n".join(lines)


async def get_availability(
    *,
    start_date: str | None,
    days_ahead: int,
    detailed: bool,
    tz_name: str = "Europe/London",
) -> str:
    """Top-level entry point used by the check_availability MCP tool."""
    tz = ZoneInfo(tz_name)
    window_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=tz) if start_date else datetime.now(tz)
    window_end = window_start + timedelta(days=days_ahead)

    calendars = load_calendars()

    async with httpx.AsyncClient(headers={"User-Agent": "mcp.bolster.online-availability/1.0"}) as client:
        intervals = await collect_intervals(calendars, window_start, window_end, tz, client)

    merged = merge_timeline(intervals, window_start, window_end)
    return format_timeline(merged, window_start, window_end, detailed=detailed)
