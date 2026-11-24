"""Search ergonomics: time filters, ordering, date-valued objects, grouping, and compact/projected results."""

import json

import pytest

from factstore import ValidationError
from factstore import store as store_module
from factstore.shape import COMPACT_FACT_FIELDS, FACT_FIELDS

ADA, BOB = "ada", "bob"


@pytest.fixture
def clock(monkeypatch):
    """Set the time the engine stamps on the next writes: ``at('2026-11-02T09:00:00.000Z')``."""
    now = ["2026-11-01T10:00:00.000Z"]
    monkeypatch.setattr(store_module, "now_iso", lambda: now[0])

    def at(stamp: str) -> None:
        now[0] = stamp

    return at


def refs(result):
    return [f["subject_ref"] for f in result["facts"]]


# ------------------------------------------------------------------------------------------------ time filters


class TestTimeFilters:
    @pytest.fixture
    def timeline(self, store, clock):
        clock("2026-11-01T10:00:00.000Z")
        store.add_fact(ADA, "One", "Is a", "Thing")
        clock("2026-11-05T10:00:00.000Z")
        two = store.add_fact(ADA, "Two", "Is a", "Thing")
        clock("2026-11-09T10:00:00.000Z")
        store.add_fact(ADA, "Three", "Is a", "Thing")
        clock("2026-11-12T10:00:00.000Z")
        store.update_fact(ADA, two["id"], confidence=0.5)  # Two is edited later
        return store

    def test_created_since_is_inclusive_and_created_before_is_exclusive(self, timeline):
        assert refs(timeline.search_facts(ADA, created_since="2026-11-05T10:00:00Z")) == ["Three", "Two"]
        assert refs(timeline.search_facts(ADA, created_before="2026-11-05T10:00:00Z")) == ["One"]
        assert refs(timeline.search_facts(ADA, created_since="2026-11-02", created_before="2026-11-09")) == ["Two"]

    def test_a_coarse_time_means_the_start_of_its_period(self, timeline):
        assert timeline.search_facts(ADA, created_since="2026-11")["total"] == 3
        assert timeline.search_facts(ADA, created_since="2026-12")["total"] == 0
        assert timeline.search_facts(ADA, created_before="2027")["total"] == 3

    def test_updated_since_leaves_out_facts_never_edited(self, timeline):
        assert refs(timeline.search_facts(ADA, updated_since="2026-01-01")) == ["Two"]
        assert timeline.search_facts(ADA, updated_since="2026-11-13")["total"] == 0

    def test_changed_since_means_created_or_edited(self, timeline):
        assert refs(timeline.search_facts(ADA, changed_since="2026-11-10")) == ["Two"]  # Three predates it, Two edited
        assert refs(timeline.search_facts(ADA, changed_since="2026-11-09")) == ["Three", "Two"]  # newest created first
        assert timeline.search_facts(ADA, changed_since="2026-11-13")["total"] == 0

    def test_filters_combine_with_the_other_filters(self, timeline):
        found = timeline.search_facts(ADA, created_since="2026-11-04", subject="Two", action="Is a")
        assert refs(found) == ["Two"]

    @pytest.mark.parametrize("name", ["created_since", "created_before", "updated_since", "changed_since"])
    def test_a_bad_time_is_refused_with_the_valid_forms(self, store, name):
        with pytest.raises(ValidationError, match="Invalid time"):
            store.search_facts(ADA, **{name: "yesterday"})

    def test_due_for_review_takes_the_same_time_filters(self, timeline):
        before = "2099-01-01"
        assert [
            f["subject_ref"] for f in timeline.due_for_review(ADA, before, created_since="2026-11-06")["facts"]
        ] == ["Three"]
        assert [
            f["subject_ref"] for f in timeline.due_for_review(ADA, before, updated_since="2026-11-01")["facts"]
        ] == ["Two"]
        assert timeline.due_for_review(ADA, before, created_before="2026-11-02")["total"] == 1


# ------------------------------------------------------------------------------------------------ ordering


class TestOrdering:
    @pytest.fixture
    def ordered(self, store, clock):
        for stamp, name, confidence, start in [
            ("2026-11-01T10:00:00.000Z", "A", 0.2, "2020"),
            ("2026-11-02T10:00:00.000Z", "B", 0.9, None),
            ("2026-11-03T10:00:00.000Z", "C", 0.5, "2010"),
            ("2026-11-04T10:00:00.000Z", "D", 0.7, "2015"),
        ]:
            clock(stamp)
            store.add_fact(ADA, name, "Is", f"Thing {name.lower()}", confidence=confidence, valid_from=start)
        return store

    def test_the_default_is_still_newest_created_first(self, ordered):
        assert refs(ordered.search_facts(ADA)) == ["D", "C", "B", "A"]

    def test_order_alone_reorders_the_default_sort(self, ordered):
        assert refs(ordered.search_facts(ADA, order="asc")) == ["A", "B", "C", "D"]
        assert refs(ordered.search_facts(ADA, order="desc")) == ["D", "C", "B", "A"]

    def test_order_by_confidence_in_both_directions(self, ordered):
        assert refs(ordered.search_facts(ADA, order_by="confidence", order="asc")) == ["A", "C", "D", "B"]
        assert refs(ordered.search_facts(ADA, order_by="confidence")) == ["B", "D", "C", "A"]

    def test_facts_with_no_value_come_last_whichever_way_it_sorts(self, ordered):
        assert refs(ordered.search_facts(ADA, order_by="valid_from", order="asc")) == ["C", "D", "A", "B"]
        assert refs(ordered.search_facts(ADA, order_by="valid_from", order="desc")) == ["A", "D", "C", "B"]
        assert refs(ordered.search_facts(ADA, order_by="updated_at")) == ["D", "C", "B", "A"]  # none edited: all last

    def test_order_by_object_sorts_by_the_folded_object(self, ordered):
        assert refs(ordered.search_facts(ADA, order_by="object", order="desc")) == ["D", "C", "B", "A"]
        assert refs(ordered.search_facts(ADA, order_by="object", order="asc")) == ["A", "B", "C", "D"]

    def test_ties_fall_back_to_newest_first_so_pages_are_stable(self, store, clock):
        clock("2026-11-01T10:00:00.000Z")
        for name in ("A", "B", "C", "D"):
            store.add_fact(ADA, name, "Is", "Same", confidence=0.5)  # one timestamp, one confidence
        pages = [refs(store.search_facts(ADA, order_by="confidence", limit=2, offset=o)) for o in (0, 2)]
        assert pages == [["D", "C"], ["B", "A"]]

    def test_an_unknown_order_lists_the_choices(self, store):
        with pytest.raises(ValidationError, match="order_by must be one of created_at, updated_at, confidence"):
            store.search_facts(ADA, order_by="subject")
        with pytest.raises(ValidationError, match="order must be one of asc, desc"):
            store.search_facts(ADA, order="sideways")

    def test_group_count_ordering_needs_a_grouping(self, store):
        with pytest.raises(ValidationError, match="order_by must be one of"):
            store.search_facts(ADA, order_by="group_count")


# ------------------------------------------------------------------------------------------------ date objects


class TestDateRange:
    @pytest.fixture
    def releases(self, store):
        for title, when in [
            ("R1", "date:2026-11-03"),
            ("R2", "date:2026-11-17"),
            ("R3", "date:2026"),
            ("R4", "date:2025-12-31"),
            ("R5", "date:--05-17"),
            ("R6", "text:2026-11-05"),
            ("R7", "date:2026-11"),
        ]:
            store.add_fact(ADA, title, "Published on", when)
        return store

    def names(self, store, **window):
        return sorted(f["subject_ref"] for f in store.search_facts(ADA, action="Published on", **window)["facts"])

    def test_a_window_matches_every_date_whose_period_overlaps_it(self, releases):
        assert self.names(releases, object_from="2026-11", object_to="2026-11") == ["R1", "R2", "R3", "R7"]

    def test_within_keeps_only_dates_entirely_inside_the_window(self, releases):
        window = {"object_from": "2026-11", "object_to": "2026-11", "object_within": True}
        assert self.names(releases, **window) == ["R1", "R2", "R7"]  # 2026 as a whole is not inside November

    def test_a_single_bound_is_enough(self, releases):
        assert self.names(releases, object_from="2026-11-10") == ["R2", "R3", "R7"]
        assert self.names(releases, object_from="2026-11-10", object_within=True) == ["R2"]
        assert self.names(releases, object_to="2025-12-31") == ["R4"]
        assert self.names(releases, object_to="2025") == ["R4"]
        assert self.names(releases, object_to="2026") == ["R1", "R2", "R3", "R4", "R7"]

    def test_the_bounds_are_inclusive_to_the_day(self, releases):
        assert self.names(releases, object_from="2026-11-03", object_to="2026-11-03") == ["R1", "R3", "R7"]
        assert self.names(releases, object_from="2026-11-04", object_to="2026-11-16") == ["R3", "R7"]
        assert self.names(releases, object_from="2026-11-04", object_to="2026-11-16", object_within=True) == []

    def test_dates_with_no_year_and_non_date_objects_never_match(self, releases):
        everything = self.names(releases, object_from="0001", object_to="9999")
        assert everything == ["R1", "R2", "R3", "R4", "R7"]  # not R5 (--05-17), not R6 (text)

    def test_a_month_bound_covers_the_whole_month(self, store):
        store.add_fact(ADA, "Late", "Published on", "date:2026-02-28")
        store.add_fact(ADA, "Next", "Published on", "date:2026-03-01")
        found = store.search_facts(ADA, object_from="2026-02", object_to="2026-02")
        assert refs(found) == ["Late"]

    @pytest.mark.parametrize("bad", ["--05-17", "2026-02-30", "2026-13", "May 2026", "2026-11-03T10:00", "20261103"])
    def test_a_bound_that_is_not_a_calendar_date_is_refused(self, store, bad):
        with pytest.raises(ValidationError, match="object_from|Invalid time"):
            store.search_facts(ADA, object_from=bad)
        with pytest.raises(ValidationError, match="object_to|Invalid time"):
            store.search_facts(ADA, object_to=bad)

    def test_within_needs_a_window(self, store):
        with pytest.raises(ValidationError, match="object_within needs object_from"):
            store.search_facts(ADA, object_within=True)

    def test_it_combines_with_ordering_and_the_other_filters(self, releases):
        found = releases.search_facts(ADA, object_from="2026-11", order_by="object", order="asc", object_kind="date")
        assert [f["object"] for f in found["facts"]] == ["2026", "2026-11", "2026-11-03", "2026-11-17"]


# ------------------------------------------------------------------------------------------------ grouping


class TestGrouping:
    @pytest.fixture
    def mapped(self, store, clock):
        for stamp, release, source, end, confidence in [
            ("2026-11-01T10:00:00.000Z", "Release A", "source:X", "2026-03", 0.9),
            ("2026-11-02T10:00:00.000Z", "Release B", "source:X", "2026-06", 0.5),
            ("2026-11-03T10:00:00.000Z", "Release C", "source:Y", "2026-01", 0.7),
            ("2026-11-04T10:00:00.000Z", "Release D", "source:X", "2026-02", 0.6),
        ]:
            clock(stamp)
            store.add_fact(ADA, release, "Refers to", source, confidence=confidence, valid_to=end)
        clock("2026-11-05T10:00:00.000Z")
        store.add_fact(ADA, "Release A", "Is a", "Release")
        return store

    def pick(self, store, pick, pick_by=None):
        found = store.search_facts(
            ADA, action="Refers to", group_by="object", pick=pick, pick_by=pick_by, order_by="group_count"
        )
        return {f["object_ref"]: (f["subject_ref"], f["group_count"]) for f in found["facts"]}

    def test_one_fact_per_group_with_the_size_of_the_group(self, mapped):
        found = mapped.search_facts(ADA, action="Refers to", group_by="object")
        assert (found["total"], found["count"]) == (2, 2)
        assert {f["object_ref"]: f["group_count"] for f in found["facts"]} == {"source:X": 3, "source:Y": 1}

    def test_latest_and_oldest_compare_creation_by_default(self, mapped):
        assert self.pick(mapped, "latest") == {"source:Y": ("Release C", 1), "source:X": ("Release D", 3)}
        assert self.pick(mapped, "oldest") == {"source:Y": ("Release C", 1), "source:X": ("Release A", 3)}

    def test_pick_by_valid_to_finds_the_latest_period_covered(self, mapped):
        assert self.pick(mapped, "latest", "valid_to")["source:X"] == ("Release B", 3)
        assert self.pick(mapped, "oldest", "valid_to")["source:X"] == ("Release D", 3)

    def test_highest_confidence_keeps_the_most_certain_fact(self, mapped):
        assert self.pick(mapped, "highest_confidence")["source:X"] == ("Release A", 3)

    def test_pick_by_object_compares_the_date_the_object_holds(self, store, clock):
        for stamp, title, when in [
            ("2026-11-03T10:00:00.000Z", "Old", "date:2026-01-05"),
            ("2026-11-01T10:00:00.000Z", "New", "date:2026-10-30"),
            ("2026-11-02T10:00:00.000Z", "Undated", "text:soon"),
        ]:
            clock(stamp)
            store.add_fact(ADA, title, "Published on", when, attributes={"series": "S"})
        found = store.search_facts(ADA, action="Published on", group_by="action", pick="latest", pick_by="object")
        assert [f["subject_ref"] for f in found["facts"]] == ["New"]  # latest date, though created before 'Old'
        oldest = store.search_facts(ADA, action="Published on", group_by="action", pick="oldest", pick_by="object")
        assert [f["subject_ref"] for f in oldest["facts"]] == ["Old"]

    def test_groups_are_ordered_like_other_results_and_paged_by_group(self, mapped):
        by_size = mapped.search_facts(ADA, action="Refers to", group_by="object", order_by="group_count", order="asc")
        assert [f["group_count"] for f in by_size["facts"]] == [1, 3]
        first = mapped.search_facts(ADA, action="Refers to", group_by="object", limit=1)
        second = mapped.search_facts(ADA, action="Refers to", group_by="object", limit=1, offset=1)
        assert (first["total"], first["truncated"], second["truncated"]) == (2, True, False)
        assert {refs(first)[0], refs(second)[0]} == {"Release D", "Release C"}

    def test_the_same_name_under_two_kinds_is_two_groups(self, store):
        store.add_fact(ADA, "person:Alex", "Knows", "Sam")
        store.add_fact(ADA, "org:Alex", "Knows", "Sam")
        store.add_fact(ADA, "person:Alex", "Likes", "Tea")
        found = store.search_facts(ADA, group_by="subject", count_only=True)
        assert {g["group"]: g["count"] for g in found["groups"]} == {"person:Alex": 2, "org:Alex": 1}

    def test_a_missing_kind_is_a_group_of_its_own(self, store):
        store.add_fact(ADA, "person:Alex", "Knows", "Sam")
        store.add_fact(ADA, "Plain", "Knows", "Sam")
        found = store.search_facts(ADA, group_by="subject_kind", count_only=True)
        assert {g["group"]: g["count"] for g in found["groups"]} == {"person": 1, None: 1}

    def test_filters_apply_before_grouping(self, mapped):
        found = mapped.search_facts(ADA, action="Refers to", group_by="object", created_since="2026-11-03")
        assert {f["object_ref"]: f["group_count"] for f in found["facts"]} == {"source:Y": 1, "source:X": 1}

    def test_negative_facts_are_left_out_unless_asked_for(self, mapped):
        mapped.add_fact(ADA, "Release Z", "Refers to", "source:X", confidence=-0.5)
        counts = lambda **kw: {  # noqa: E731
            f["object_ref"]: f["group_count"]
            for f in mapped.search_facts(ADA, action="Refers to", group_by="object", **kw)["facts"]
        }
        assert counts() == {"source:X": 3, "source:Y": 1}
        assert counts(include_negative=True) == {"source:X": 4, "source:Y": 1}

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"pick": "latest"}, "pick and pick_by need group_by"),
            ({"pick_by": "valid_to"}, "pick and pick_by need group_by"),
            ({"group_by": "object", "pick": "best"}, "pick must be one of latest, oldest, highest_confidence"),
            ({"group_by": "object", "pick_by": "name"}, "pick_by must be one of"),
            ({"group_by": "object", "pick": "highest_confidence", "pick_by": "valid_to"}, "pick_by applies to"),
            ({"group_by": "colour"}, "group_by must be one of subject, action, object"),
            ({"group_by": "object", "count_only": True, "fields": ["id"]}, "fields does not apply to count_only"),
            ({"group_by": "object", "count_only": True, "order_by": "confidence"}, "count_only lists groups"),
        ],
    )
    def test_bad_combinations_are_refused_with_the_valid_choices(self, store, kwargs, message):
        with pytest.raises(ValidationError, match=message):
            store.search_facts(ADA, **kwargs)


class TestCounts:
    @pytest.fixture
    def counted(self, store):
        for i in range(7):
            store.add_fact(ADA, f"Release {i}", "Refers to", f"source:{'X' if i < 5 else 'Y'}")
        store.add_fact(ADA, "Release 0", "Is a", "Release")
        return store

    def test_without_a_grouping_it_is_just_the_total(self, counted):
        assert counted.search_facts(ADA, action="Refers to", count_only=True) == {"total": 7}
        assert counted.search_facts(ADA, count_only=True) == {"total": 8}
        assert counted.search_facts(ADA, action="Nothing", count_only=True) == {"total": 0}

    def test_with_a_grouping_it_lists_each_group_largest_first(self, counted):
        found = counted.search_facts(ADA, action="Refers to", group_by="object", count_only=True)
        assert [(g["group"], g["count"]) for g in found["groups"]] == [("source:X", 5), ("source:Y", 2)]
        assert (found["facts_total"], found["total"], found["count"], found["truncated"]) == (7, 2, 2, False)

    def test_it_pages_by_group_and_can_be_compact(self, counted):
        first = counted.search_facts(ADA, group_by="action", count_only=True, limit=1, format="compact")
        assert first["columns"] == ["group", "count"] and first["rows"] == [["Refers to", 7]]
        assert (first["total"], first["truncated"], first["facts_total"]) == (2, True, 8)
        second = counted.search_facts(ADA, group_by="action", count_only=True, limit=1, offset=1, format="compact")
        assert second["rows"] == [["Is a", 1]]

    def test_it_respects_every_filter(self, counted):
        counted.add_fact(ADA, "Release 9", "Refers to", "source:X", confidence=0.4)
        found = counted.search_facts(ADA, group_by="object", count_only=True, action="Refers to", min_confidence=0.9)
        assert (found["facts_total"], [(g["group"], g["count"]) for g in found["groups"]]) == (
            7, [("source:X", 5), ("source:Y", 2)],
        )  # fmt: skip
        assert counted.search_facts(ADA, action="Refers to", count_only=True, created_before="2000")["total"] == 0


# ------------------------------------------------------------------------------------------------ shaping


class TestShaping:
    @pytest.fixture
    def facts(self, store):
        for i in range(60):
            store.add_fact(
                ADA, f"article:Release number {i} of the quarterly statistics", "Refers to",
                f"source:Labour Market Statistics {i % 7}", confidence=0.75, valid_from="2026-04", valid_to="2026-06",
                attributes={"evidence": f"mention 'labour market statistics' ({i}) resolved by alias or name", "mention": "x"},
                references=[f"https://example.org/releases/{i}"],
            )  # fmt: skip
        return store

    def test_the_default_full_format_is_unchanged(self, facts):
        found = facts.search_facts(ADA, limit=2)
        assert set(found) == {"count", "total", "offset", "limit", "truncated", "facts"}
        assert list(found["facts"][0]) == list(FACT_FIELDS)

    def test_compact_returns_columns_and_rows_instead_of_facts(self, facts):
        found = facts.search_facts(ADA, limit=3, format="compact")
        assert set(found) == {"count", "total", "offset", "limit", "truncated", "columns", "rows"}
        assert found["columns"] == list(COMPACT_FACT_FIELDS)
        assert len(found["rows"]) == 3 and all(len(row) == len(found["columns"]) for row in found["rows"])
        row = dict(zip(found["columns"], found["rows"][0], strict=True))
        assert (row["action"], row["confidence"], row["valid_from"], row["valid_to"]) == (
            "Refers to",
            0.75,
            "2026-04",
            "2026-06",
        )
        assert row["subject_ref"].startswith("article:Release number") and row["object_ref"].startswith("source:")

    def test_compact_leaves_out_attributes_and_references_unless_named(self, facts):
        assert "attributes" not in facts.search_facts(ADA, limit=1, format="compact")["columns"]
        named = facts.search_facts(ADA, limit=1, format="compact", fields=["id", "attributes", "references"])
        assert named["columns"] == ["id", "attributes", "references"]
        assert named["rows"][0][1]["mention"] == "x" and named["rows"][0][2][0].startswith("https://example.org/")

    def test_fields_trim_full_results_in_the_order_given(self, facts):
        found = facts.search_facts(ADA, limit=2, fields=["confidence", "subject_ref"])
        assert [list(f) for f in found["facts"]] == [["confidence", "subject_ref"]] * 2
        assert found["facts"][0]["confidence"] == 0.75

    def test_fields_may_be_a_comma_separated_string_and_repeats_are_ignored(self, facts):
        found = facts.search_facts(ADA, limit=1, fields="id, id, action")
        assert list(found["facts"][0]) == ["id", "action"]

    def test_an_unknown_field_or_format_lists_what_is_valid(self, facts):
        with pytest.raises(
            ValidationError, match="Unknown field 'colour' in fields. Valid fields: id, subject, subject_kind"
        ):
            facts.search_facts(ADA, fields=["colour"])
        with pytest.raises(ValidationError, match="format must be one of full, compact"):
            facts.search_facts(ADA, format="table")
        with pytest.raises(ValidationError, match="non-empty list of field names"):
            facts.search_facts(ADA, fields=[])

    def test_a_grouped_result_can_name_group_count_as_a_field(self, facts):
        found = facts.search_facts(ADA, group_by="object", fields=["object_ref", "group_count"], format="compact")
        assert found["columns"] == ["object_ref", "group_count"]
        assert sum(row[1] for row in found["rows"]) == 60
        with pytest.raises(ValidationError, match="Unknown field 'group_count'"):
            facts.search_facts(ADA, fields=["group_count"])  # only valid when grouping

    def test_a_compact_page_is_at_least_four_times_smaller(self, facts):
        full = len(json.dumps(facts.search_facts(ADA, limit=50), separators=(",", ":")))
        compact = len(json.dumps(facts.search_facts(ADA, limit=50, format="compact"), separators=(",", ":")))
        assert full / compact >= 4

    def test_pagination_fields_are_the_same_in_both_formats(self, facts):
        for fmt in ("full", "compact"):
            found = facts.search_facts(ADA, limit=20, offset=40, format=fmt)
            assert (found["count"], found["total"], found["offset"], found["limit"], found["truncated"]) == (
                20, 60, 40, 20, False,
            )  # fmt: skip


class TestShapingTheOtherLists:
    @pytest.fixture
    def reviewed(self, store):
        fact = store.add_fact(ADA, "Release", "Refers to", "source:X", confidence=0.6, valid_from="2026")
        store.request_review(ADA, fact["id"], BOB, note="please check")
        return store, fact

    def test_due_for_review_compact_and_projection(self, store):
        store.add_fact(ADA, "A", "Is", "One", confidence=0.4)
        found = store.due_for_review(ADA, before="2099-01-01", format="compact")
        assert found["columns"] == list(COMPACT_FACT_FIELDS) and found["rows"][0][2:5] == ["Is", "One", 0.4]
        assert (found["before"], found["order"], found["total"]) == (found["before"], "oldest_reviewed", 1)
        trimmed = store.due_for_review(ADA, before="2099-01-01", fields=["subject_ref", "confidence"])
        assert trimmed["facts"] == [{"subject_ref": "A", "confidence": 0.4}]

    def test_review_outcomes_compact_leaves_out_the_review_id_and_note_until_named(self, store):
        fact = store.add_fact(ADA, "Release", "Refers to", "source:X", public=True)
        store.mark_reviewed(BOB, fact["id"], "unsure", "not sure about the period")
        found = store.review_outcomes(ADA, format="compact")
        assert found["columns"] == [
            "fact_id",
            "role",
            "reviewer",
            "outcome",
            "at",
            "subject_ref",
            "action",
            "object_ref",
        ]
        assert found["rows"][0][1:4] == ["owner", BOB, "unsure"]
        with_note = store.review_outcomes(ADA, fields=["outcome", "note"])
        assert with_note["outcomes"] == [{"outcome": "unsure", "note": "not sure about the period"}]
        with pytest.raises(ValidationError, match="Unknown field 'fact'"):
            store.review_outcomes(ADA, fields=["fact"])

    def test_pending_reviews_flatten_the_request_and_its_fact(self, reviewed):
        store, fact = reviewed
        full = store.pending_reviews(BOB)
        assert full["requests"][0]["fact"]["id"] == fact["id"]  # unchanged nested shape by default
        compact = store.pending_reviews(BOB, format="compact")
        assert compact["columns"] == [
            "id", "fact_id", "requested_by", "requested_of", "requested_at", "subject_ref", "action", "object_ref",
        ]  # fmt: skip
        row = dict(zip(compact["columns"], compact["rows"][0], strict=True))
        assert (row["fact_id"], row["requested_by"], row["object_ref"]) == (fact["id"], ADA, "source:X")
        trimmed = store.pending_reviews(BOB, fields=["note", "confidence", "valid_from"])
        assert trimmed["requests"] == [{"note": "please check", "confidence": 0.6, "valid_from": "2026"}]

    def test_relationships_between_compact_and_projected(self, store):
        store.add_fact(ADA, "Ada", "Knows", "Bo")
        store.add_fact(ADA, "Ada", "Works with", "Cy")
        store.add_fact(ADA, "Cy", "Works with", "Bo")
        full = store.relationships_between(ADA, "Ada", "Bo", max_depth=2)
        assert "direction" in full["direct"][0] and full["indirect"][0]["via"] == "cy"
        compact = store.relationships_between(ADA, "Ada", "Bo", max_depth=2, format="compact")
        assert compact["direct"]["columns"] == [*COMPACT_FACT_FIELDS, "direction"]
        assert compact["direct"]["rows"][0][-1] == "a_to_b"
        paths = compact["indirect"]
        assert (paths["columns"], paths["fact_columns"]) == (["via", "facts"], list(COMPACT_FACT_FIELDS))
        via, rows = paths["rows"][0]
        assert via == "cy" and [r[2] for r in rows] == ["Works with", "Works with"]
        trimmed = store.relationships_between(ADA, "Ada", "Bo", max_depth=2, fields=["action", "direction"])
        assert trimmed["direct"] == [{"action": "Knows", "direction": "a_to_b"}]
        assert trimmed["indirect"][0]["facts"] == [{"action": "Works with"}, {"action": "Works with"}]
        assert (compact["a"], compact["b"], compact["direct_truncated"]) == (full["a"], full["b"], False)
