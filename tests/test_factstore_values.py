"""Value handling: ids, times, kind prefixes and field validators (no database involved)."""

import uuid
from typing import Any

import pytest

from factstore import ValidationError, parse_date_value, parse_when, uuid7
from factstore.config import Config
from factstore.values import (
    check_attributes,
    check_confidence,
    check_references,
    fold,
    parse_ref,
)

CFG = Config()


class TestUuid7:
    def test_version_variant_and_timestamp(self):
        value = uuid7(now_ms=1_760_000_000_123)
        assert value.version == 7
        assert value.variant == uuid.RFC_4122
        assert value.int >> 80 == 1_760_000_000_123

    def test_orders_by_time(self):
        assert str(uuid7(now_ms=1_000)) < str(uuid7(now_ms=2_000))

    def test_random_bits_differ(self):
        assert uuid7(now_ms=5) != uuid7(now_ms=5)


class TestFold:
    def test_case_and_whitespace_insensitive(self):
        assert fold("  Is   A ") == fold("is a")

    def test_unicode_casefold(self):
        assert fold("STRASSE") == fold("straße")


class TestParseWhen:
    @pytest.mark.parametrize(
        ("value", "key"),
        [
            ("2026", "2026-01-01T00:00:00.000000"),
            ("2026-10", "2026-10-01T00:00:00.000000"),
            ("2026-10-18", "2026-10-18T00:00:00.000000"),
            ("2026-10-18T09:30", "2026-10-18T09:30:00.000000"),  # no offset: UTC
            ("2026-10-18T09:30:15Z", "2026-10-18T09:30:15.000000"),
            ("2026-10-18T09:30:15+02:00", "2026-10-18T07:30:15.000000"),
            ("2026-10-18T09:30:15.5-01:00", "2026-10-18T10:30:15.500000"),
        ],
    )
    def test_start_keys_are_utc(self, value, key):
        assert parse_when(value) == (value, key)

    @pytest.mark.parametrize(
        ("value", "end_key"),
        [
            ("2015", "2016-01-01T00:00:00.000000"),
            ("2015-12", "2016-01-01T00:00:00.000000"),
            ("2015-02", "2015-03-01T00:00:00.000000"),
            ("2015-12-31", "2016-01-01T00:00:00.000000"),
            ("2015-12-31T23:59:59Z", "2015-12-31T23:59:59.000000"),  # an instant is its own end
        ],
    )
    def test_end_keys_are_exclusive_upper_bounds(self, value, end_key):
        assert parse_when(value, end=True)[1] == end_key

    @pytest.mark.parametrize(
        "value",
        ["", "--10-18", "18/10/2026", "2026-13", "2026-02-30", "20261018", "2026-10-18 09:30", "yesterday", "26"],
    )
    def test_rejects_anything_not_strict_iso(self, value):
        with pytest.raises(ValidationError, match="strict ISO 8601"):
            parse_when(value)

    def test_rejects_non_strings(self):
        not_a_string: Any = 2026
        with pytest.raises(ValidationError):
            parse_when(not_a_string)


class TestParseDateValue:
    @pytest.mark.parametrize("value", ["1988", "1988-05", "1988-05-17", "--05-17", "--02-29"])
    def test_accepts(self, value):
        assert parse_date_value(value) == value

    @pytest.mark.parametrize("value", ["17/05/1988", "--13-01", "--02-30", "1988-05-17T10:00Z", "May 17"])
    def test_rejects(self, value):
        with pytest.raises(ValidationError, match="Invalid date"):
            parse_date_value(value)


class TestParseRef:
    @pytest.mark.parametrize("kind", ["person", "place", "org", "date", "number", "text", "actor"])
    def test_recognised_prefix_becomes_the_kind(self, kind):
        value = "1988-05-17" if kind == "date" else "Something"
        ref = parse_ref("subject", f"{kind}:{value}", CFG)
        assert (ref.kind, ref.name) == (kind, value)

    def test_prefix_is_case_insensitive_and_name_is_trimmed(self):
        ref = parse_ref("subject", "PERSON:  Ada Example ", CFG)
        assert (ref.kind, ref.name, ref.f) == ("person", "Ada Example", "ada example")

    @pytest.mark.parametrize("text", ["Meeting: standup", "Re: lunch", "http://example.org", "10:30 call"])
    def test_unrecognised_prefix_stays_literal(self, text):
        ref = parse_ref("subject", text, CFG)
        assert (ref.kind, ref.name) == (None, text)

    def test_recognised_prefix_with_nothing_after_it_is_an_error(self):
        with pytest.raises(ValidationError, match="must not be empty"):
            parse_ref("subject", "person:  ", CFG)

    def test_date_kind_is_validated(self):
        with pytest.raises(ValidationError, match="Invalid date"):
            parse_ref("object", "date:soon", CFG)

    def test_empty_and_overlong_names_are_errors(self):
        with pytest.raises(ValidationError):
            parse_ref("subject", "   ", CFG)
        with pytest.raises(ValidationError, match="at most 200"):
            parse_ref("subject", "x" * 201, CFG)

    def test_kinds_are_configurable(self):
        cfg = Config(kinds=frozenset({"thing"}))
        assert parse_ref("subject", "thing:Widget", cfg).kind == "thing"
        assert parse_ref("subject", "person:Ada", cfg).kind is None


class TestValidators:
    @pytest.mark.parametrize("value", [-1, -1.0, -0.5, 0, 0.0, 0.25, 1, 1.0])
    def test_confidence_accepts_the_signed_range(self, value):
        assert check_confidence(value) == float(value)

    @pytest.mark.parametrize("value", [1.01, -1.01, float("nan"), float("inf"), "0.5", None, True])
    def test_confidence_rejects_the_rest(self, value):
        with pytest.raises(ValidationError, match="between -1.0 and 1.0"):
            check_confidence(value)

    def test_references(self):
        assert check_references(None, CFG) == []
        assert check_references([" a ", "b"], CFG) == ["a", "b"]
        with pytest.raises(ValidationError):
            check_references(["x"] * 21, CFG)
        with pytest.raises(ValidationError):
            check_references(["  "], CFG)
        with pytest.raises(ValidationError):
            check_references("not a list", CFG)

    def test_attributes(self):
        assert check_attributes(None, CFG) == {}
        assert check_attributes({"unit": "kg", "n": 3, "tags": ["a"]}, CFG) == {"unit": "kg", "n": 3, "tags": ["a"]}
        with pytest.raises(ValidationError, match="attribute names"):
            check_attributes({"bad key": 1}, CFG)
        with pytest.raises(ValidationError, match="limit"):
            check_attributes({"blob": "x" * 5000}, CFG)
        with pytest.raises(ValidationError, match="JSON-serialisable"):
            check_attributes({"when": object()}, CFG)
        with pytest.raises(ValidationError, match="object"):
            check_attributes(["not", "a", "dict"], CFG)
