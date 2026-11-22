"""Value handling shared by every part of the engine: ids, text folding, names with kinds, times, validators."""

import json
import math
import random
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .config import Config
from .errors import ValidationError

WHEN_FORMATS = (
    "YYYY, YYYY-MM, YYYY-MM-DD, or YYYY-MM-DDTHH:MM[:SS[.ffffff]] optionally followed by Z or an offset like "
    "+01:00 (UTC when there is no offset)"
)
DATE_VALUE_FORMATS = "YYYY, YYYY-MM, YYYY-MM-DD, or --MM-DD for a date with no known year"

_YEAR = re.compile(r"^\d{4}$")
_MONTH = re.compile(r"^\d{4}-\d{2}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?$")
_NO_YEAR = re.compile(r"^--(\d{2})-(\d{2})$")
_ATTRIBUTE_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def uuid7(now_ms: int | None = None) -> uuid.UUID:
    """A UUIDv7 (RFC 9562): 48-bit unix-millisecond timestamp, then random bits."""
    millis = (int(time.time() * 1000) if now_ms is None else now_ms) & ((1 << 48) - 1)
    rand = random.SystemRandom().getrandbits(74)
    rand_a, rand_b = rand >> 62, rand & ((1 << 62) - 1)
    value = (millis << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def fold(text: str) -> str:
    """Case- and whitespace-insensitive form, so 'Is a' and ' is   A ' match."""
    return " ".join(text.split()).casefold()


def actor_id(actor: str) -> str:
    """The canonical form of an actor identifier (logins are case-insensitive)."""
    cleaned = fold(actor) if isinstance(actor, str) else ""
    if not cleaned:
        raise ValidationError("actor must be a non-empty string.")
    if len(cleaned) > 100:
        raise ValidationError("actor must be at most 100 characters.")
    return cleaned


def iso(moment: datetime) -> str:
    """Audit timestamps: UTC, millisecond precision, trailing Z. Lexicographic order is chronological order."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def now_iso() -> str:
    return iso(datetime.now(UTC))


def utc_key(moment: datetime) -> str:
    """Sortable key for validity bounds."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")


def parse_when(value: str, *, end: bool = False) -> tuple[str, str]:
    """Validate a strict ISO 8601 time. Returns (the text as given, a sortable UTC key).

    Times with no offset are UTC. A coarse value covers its whole period: as a start (``end=False``) it keys
    to the start of the period, as an end (``end=True``) to the start of the *next* period, so an end bound is
    exclusive and ``valid_to='2015'`` includes all of 2015.
    """
    if not isinstance(value, str):
        raise ValidationError(f"Invalid time {value!r}. Use strict ISO 8601: {WHEN_FORMATS}.")
    text = value.strip()
    try:
        if _YEAR.match(text):
            start = datetime(int(text), 1, 1, tzinfo=UTC)
            following = datetime(int(text) + 1, 1, 1, tzinfo=UTC)
        elif _MONTH.match(text):
            year, month = int(text[:4]), int(text[5:7])
            start = datetime(year, month, 1, tzinfo=UTC)
            following = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=UTC)
        elif _DATE.match(text):
            day = date.fromisoformat(text)
            start = datetime(day.year, day.month, day.day, tzinfo=UTC)
            following = start + timedelta(days=1)
        elif _DATETIME.match(text):
            start = following = datetime.fromisoformat(text)
            if start.tzinfo is None:
                start = following = start.replace(tzinfo=UTC)
        else:
            raise ValueError(text)
    except (ValueError, OverflowError):
        raise ValidationError(f"Invalid time {value!r}. Use strict ISO 8601: {WHEN_FORMATS}.") from None
    return text, utc_key(following if end else start)


def parse_instant(value: str) -> datetime:
    """A point in time for filters: the start of the period for coarse values."""
    _, key = parse_when(value)
    return datetime.strptime(key, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=UTC)


def parse_date_value(text: str) -> str:
    """Validate the value of a ``date:`` name. ``--MM-DD`` is a date with no known year (29 February is allowed)."""
    cleaned = text.strip()
    try:
        recurring = _NO_YEAR.match(cleaned)
        if recurring:
            date(2000, int(recurring.group(1)), int(recurring.group(2)))  # 2000 is a leap year
            return cleaned
        if _YEAR.match(cleaned) or _MONTH.match(cleaned) or _DATE.match(cleaned):
            parse_when(cleaned)
            return cleaned
    except (ValueError, ValidationError):
        pass
    raise ValidationError(f"Invalid date {text!r}. Use {DATE_VALUE_FORMATS}.")


@dataclass(frozen=True)
class Ref:
    """A name as stored: an optional kind plus the display name. Matching uses the folded name."""

    kind: str | None
    name: str

    @property
    def f(self) -> str:
        return fold(self.name)

    @property
    def key(self) -> tuple[str | None, str]:
        return (self.kind, self.f)

    def __str__(self) -> str:
        return f"{self.kind}:{self.name}" if self.kind else self.name


def check_text(label: str, value: Any, cfg: Config) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a string.")
    cleaned = value.strip()
    if not cleaned:
        raise ValidationError(f"{label} must not be empty.")
    if len(cleaned) > cfg.max_text:
        raise ValidationError(f"{label} must be at most {cfg.max_text} characters.")
    return cleaned


def parse_ref(label: str, value: Any, cfg: Config) -> Ref:
    """Split a recognised ``kind:`` prefix off a name. Unrecognised prefixes ('Meeting: standup') stay literal."""
    text = check_text(label, value, cfg)
    prefix, sep, rest = text.partition(":")
    if sep and fold(prefix) in cfg.kinds:
        kind = fold(prefix)
        name = check_text(label, rest, cfg)
        if kind == "date":
            name = parse_date_value(name)
        return Ref(kind, name)
    return Ref(None, text)


def check_kind(label: str, value: str | None, cfg: Config) -> str | None:
    if value is None:
        return None
    kind = fold(value)
    if kind not in cfg.kinds:
        raise ValidationError(f"{label} must be one of {sorted(cfg.kinds)}.")
    return kind


def check_confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValidationError("confidence must be a number between -1.0 and 1.0.")
    if not -1.0 <= value <= 1.0:
        raise ValidationError("confidence must be a number between -1.0 and 1.0.")
    return float(value)


def check_references(value: Any, cfg: Config) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValidationError("references must be a list of strings.")
    if len(value) > cfg.max_references:
        raise ValidationError(f"references can hold at most {cfg.max_references} items.")
    cleaned = [item.strip() for item in value]
    if any(not item or len(item) > cfg.max_reference_length for item in cleaned):
        raise ValidationError(f"each reference must be 1 to {cfg.max_reference_length} characters.")
    return cleaned


def check_attributes(value: Any, cfg: Config) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError("attributes must be an object (a JSON dictionary).")
    for key in value:
        if not isinstance(key, str) or not _ATTRIBUTE_KEY.match(key):
            raise ValidationError(f"attribute names must match {_ATTRIBUTE_KEY.pattern}; got {key!r}.")
    try:
        size = len(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())
    except (TypeError, ValueError):
        raise ValidationError("attributes must be JSON-serialisable.") from None
    if size > cfg.max_attributes_bytes:
        raise ValidationError(f"attributes are {size} bytes as JSON; the limit is {cfg.max_attributes_bytes}.")
    return value


def check_attribute_key(key: str) -> str:
    if not isinstance(key, str) or not _ATTRIBUTE_KEY.match(key):
        raise ValidationError(f"attribute names must match {_ATTRIBUTE_KEY.pattern}; got {key!r}.")
    return key


def like(text: str) -> str:
    """A LIKE pattern matching ``text`` anywhere (escape character is a backslash)."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
