"""Value handling shared by every part of the engine: ids, text folding, names with kinds, times, validators."""

import json
import math
import random
import re
import time
import unicodedata
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


def fold_case(text: str) -> str:
    """Case- and whitespace-insensitive form. Used where accents are significant, i.e. for actor identifiers."""
    return " ".join(text.split()).casefold()


def fold_accents(text: str) -> str:
    """Case-, whitespace- and accent-insensitive form (the schema version 3 fold). Punctuation is significant."""
    decomposed = unicodedata.normalize("NFKD", text)
    return fold_case("".join(ch for ch in decomposed if not unicodedata.combining(ch)))


#: Characters that carry meaning in a name even though they are not letters or digits ('C++', 'AT&T', 'C#', '50%').
_MEANINGFUL = frozenset("#&%@")


def _keeps(text: str, index: int) -> bool:
    """Whether the non-alphanumeric character at ``index`` stays in a folded name.

    Symbols (Unicode categories S*: '+', '$', '=' and so on) and ``# & % @`` stay, so 'C++' and 'C' remain different
    names. A punctuation mark directly between two digits also stays ('1.500' is not '1,500', '2019/20' is not
    '2019-20', '2026-05-17' stays a date), because dropping it would merge different numbers. Everything else is
    punctuation or spacing and is dropped.
    """
    char = text[index]
    if char in _MEANINGFUL or unicodedata.category(char).startswith("S"):
        return True
    return 0 < index < len(text) - 1 and not char.isspace() and text[index - 1].isdigit() and text[index + 1].isdigit()


def fold(text: str) -> str:
    """The form names, actions and free text are matched in: case-, whitespace-, accent- and punctuation-insensitive,
    so 'Is a' and ' is   A ' match, 'Zoë', 'ZOE' and 'zoe' match, and 'Monthly Births (Northern Ireland)' matches
    'Monthly Births Northern Ireland'.

    Every run of characters that are neither letters, digits nor meaningful symbols (see ``_keeps``) becomes one
    space. A name made only of such characters ('(?)') would fold to nothing, so it falls back to
    ``fold_accents`` and stays distinguishable. Apostrophes and hyphens are punctuation: "O'Brien" is 'o brien'
    and 'OBrien' is 'obrien', which stay different names.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    kept = "".join(ch if ch.isalnum() or _keeps(stripped, i) else " " for i, ch in enumerate(stripped))
    folded = fold_case(kept)
    return folded or fold_accents(text)


def actor_id(actor: str) -> str:
    """The canonical form of an actor identifier. Logins are case-insensitive but accents are significant: 'josé'
    and 'jose' are different actors, so one can never read the other's private facts."""
    cleaned = fold_case(actor) if isinstance(actor, str) else ""
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


def check_offset(value: Any) -> int:
    """How many matches to skip: a non-negative whole number (None means 0)."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError("offset must be a whole number, 0 or more.")
    return value


def page_size(cfg: Config, limit: Any) -> int:
    """The page size for a list call: ``limit`` clamped to 1..max_limit, or the default when it is 0 or missing."""
    return max(1, min(int(limit or cfg.default_limit), cfg.max_limit))


def page_info(*, limit: int, offset: int, count: int, total: int) -> dict[str, Any]:
    """The paging fields every list reply carries. ``truncated`` is true when more matches exist after this page."""
    return {"count": count, "total": total, "offset": offset, "limit": limit, "truncated": offset + count < total}


def check_kind(label: str, value: str | None, cfg: Config) -> str | None:
    if value is None:
        return None
    kind = fold(value)
    if kind not in cfg.kinds:
        raise ValidationError(
            f"{label} {value!r} is not a configured kind. The configured kinds are {', '.join(sorted(cfg.kinds))}. "
            f"A name written '{value}:Something' is not parsed as a kind: it is stored as that literal text."
        )
    return kind


#: ``word:text`` where the text does not start with a space or ``//`` (so 'Meeting: standup' and URLs are left alone).
_KIND_LIKE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?![\s/])\S")


def kind_prefix_warnings(cfg: Config, names: dict[str, Any]) -> list[str]:
    """Advice for names that look like a kind prefix the store does not know.

    An unrecognised prefix stays part of the name (``claim:Foo`` is stored as the literal text 'claim:Foo'), which
    is rarely what a caller meant, so say so. ``names`` maps a label ('subject', 'object', ...) to the value the
    caller supplied; values that are not strings are ignored.
    """
    warnings: list[str] = []
    for label, value in names.items():
        if not isinstance(value, str):
            continue
        text = value.strip()
        found = _KIND_LIKE.match(text)
        if found and fold(found.group(1)) not in cfg.kinds:
            warnings.append(
                f"{label} {text!r} looks like a kind prefix, but {found.group(1)!r} is not a configured kind "
                f"({', '.join(sorted(cfg.kinds))}), so it is stored as the literal text {text!r}. Use a configured "
                "prefix, or ignore this if the colon is part of the name."
            )
    return warnings


def with_warnings(result: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    """``result`` plus a ``warnings`` list, but only when there is something to say."""
    return {**result, "warnings": warnings} if warnings else result


def extras_text(attributes: str | None, refs: str | None) -> str:
    """Folded text of a fact's attributes (keys and values, nested too) and references, for free-text search."""
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                parts.append(str(key))
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)
        elif value is not None:
            parts.append(str(value))

    for raw in (attributes, refs):
        try:
            walk(json.loads(raw) if raw else None)
        except (TypeError, ValueError):
            parts.append(str(raw))
    return fold(" ".join(parts))


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
