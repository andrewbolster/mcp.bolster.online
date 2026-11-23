"""Engine basics: add, get, search, update, delete, confidence, validity, attributes and kinds."""

import pytest

from factstore import UNSET, NotFoundError, PermissionDeniedError, ValidationError

ADA = "ada"


def add(store, actor=ADA, **overrides):
    fields = {"subject": "Ada Example", "action": "Has birthday", "object": "date:1988-05-17", **overrides}
    return store.add_fact(actor, **fields)


class TestAddAndGet:
    def test_stores_every_field_with_server_set_provenance(self, store):
        fact = store.add_fact(
            ADA,
            "Ada Example",
            "Has birthday",
            "date:1988-05-17",
            references=["https://example.org/a"],
            attributes={"source": "passport"},
        )
        assert fact["subject"] == "Ada Example"
        assert (fact["object"], fact["object_kind"]) == ("1988-05-17", "date")
        assert fact["confidence"] == 1.0
        assert fact["public"] is False
        assert fact["created_by"] == ADA
        assert fact["created_at"].endswith("Z")
        assert (fact["updated_by"], fact["updated_at"], fact["reviewed_by"], fact["reviewed_at"]) == (None,) * 4
        assert fact["attributes"] == {"source": "passport"}
        assert fact["references"] == ["https://example.org/a"]
        assert store.get_fact(ADA, fact["id"])["id"] == fact["id"]

    def test_id_is_a_uuid7(self, store):
        import uuid

        assert uuid.UUID(add(store)["id"]).version == 7

    def test_actor_is_normalised(self, store):
        fact = store.add_fact("  Ada ", "A", "Is a", "Letter")
        assert fact["created_by"] == "ada"
        assert store.get_fact("ADA", fact["id"])["id"] == fact["id"]

    @pytest.mark.parametrize("bad", ["", "   ", None])
    def test_actor_must_be_non_empty(self, store, bad):
        with pytest.raises(ValidationError, match="actor"):
            store.add_fact(bad, "A", "Is a", "B")

    def test_missing_fact(self, store):
        with pytest.raises(NotFoundError):
            store.get_fact(ADA, "nope")

    def test_the_untyped_hint_is_off_unless_asked_for(self, store):
        assert "untyped" not in add(store, action="Partner", object="person:Bo Sample")

    def test_untyped_lists_entities_with_no_type_fact(self, store):
        fact = add(store, action="Partner", object="person:Bo Sample", check_types=True)
        assert fact["untyped"] == ["Ada Example", "person:Bo Sample"]
        store.add_fact(ADA, "Ada Example", "Is a", "person:Person")
        again = add(store, action="Partner", object="person:Bo Sample", check_types=True)
        assert again["untyped"] == ["person:Bo Sample"]

    def test_values_are_never_untyped(self, store):
        assert add(store, check_types=True)["untyped"] == ["Ada Example"]

    def test_type_facts_get_no_untyped_hint(self, store):
        assert "untyped" not in store.add_fact(ADA, "Ada Example", "Is a", "Person", check_types=True)


class TestConfidence:
    def test_default_is_one_and_signed_values_are_kept(self, store):
        assert add(store)["confidence"] == 1.0
        assert add(store, object="date:1999", confidence=-1)["confidence"] == -1.0
        assert add(store, object="date:2000", confidence=0)["confidence"] == 0.0

    def test_out_of_range_is_rejected(self, store):
        with pytest.raises(ValidationError):
            add(store, confidence=1.5)

    def test_negatives_are_hidden_unless_asked_for(self, store):
        add(store, object="date:1988-05-17")
        add(store, object="date:1999-01-01", confidence=-1)
        add(store, object="date:2000-01-01", confidence=0)
        assert store.search_facts(ADA)["count"] == 1
        everything = store.search_facts(ADA, include_negative=True)
        assert sorted(f["confidence"] for f in everything["facts"]) == [-1.0, 0.0, 1.0]

    def test_min_confidence(self, store):
        add(store, object="date:1988-05-17", confidence=0.4)
        add(store, object="date:1999-01-01", confidence=0.9)
        assert [f["confidence"] for f in store.search_facts(ADA, min_confidence=0.5)["facts"]] == [0.9]


class TestValidity:
    def test_bounds_are_optional_and_kept_as_given(self, store):
        fact = add(store, action="Partner", object="person:Bo Sample", valid_from="2012-03", valid_to="2015")
        assert (fact["valid_from"], fact["valid_to"]) == ("2012-03", "2015")

    def test_valid_to_before_valid_from_is_rejected(self, store):
        with pytest.raises(ValidationError, match="valid_to must not be before valid_from"):
            add(store, valid_from="2015-06-01", valid_to="2014-01-01")

    def test_bad_bound(self, store):
        with pytest.raises(ValidationError, match="strict ISO 8601"):
            add(store, valid_from="last year")

    @pytest.fixture
    def partners(self, store):
        add(store, action="Partner", object="person:Bo Sample", valid_from="2012", valid_to="2015")
        add(store, action="Partner", object="person:Cy Sample", valid_from="2015-07")
        add(store, action="Partner", object="person:Dee Placeholder", valid_to="2011")
        add(store, action="Likes", object="Tea")  # no bounds: always valid
        return store

    def names_at(self, store, instant):
        found = store.search_facts(ADA, action="Partner", valid_at=instant)["facts"]
        return sorted(f["object"] for f in found)

    def test_valid_at_uses_half_open_intervals_with_open_ends(self, partners):
        assert self.names_at(partners, "2010-01-01") == ["Dee Placeholder"]
        assert self.names_at(partners, "2013-05-17") == ["Bo Sample"]
        assert self.names_at(partners, "2015-06-30") == ["Bo Sample"]  # valid_to='2015' includes all of 2015
        assert self.names_at(partners, "2016-01-01") == ["Cy Sample"]
        assert self.names_at(partners, "2030-01-01") == ["Cy Sample"]

    def test_timeless_facts_are_valid_at_any_instant(self, partners):
        assert [f["object"] for f in partners.search_facts(ADA, action="Likes", valid_at="1900-01-01")["facts"]] == [
            "Tea"
        ]

    def test_range_overlap(self, partners):
        def overlapping(**kwargs):
            return sorted(f["object"] for f in partners.search_facts(ADA, action="Partner", **kwargs)["facts"])

        assert overlapping(valid_from="2014", valid_to="2016") == ["Bo Sample", "Cy Sample"]
        assert overlapping(valid_from="2016") == ["Cy Sample"]
        assert overlapping(valid_to="2011-06") == ["Dee Placeholder"]
        assert overlapping(valid_from="2011-06", valid_to="2012-03") == ["Bo Sample", "Dee Placeholder"]

    def test_timezone_offsets_are_honoured(self, store):
        add(
            store,
            action="On shift",
            object="Ward 1",
            valid_from="2026-01-01T09:00:00+02:00",
            valid_to="2026-01-01T17:00:00+02:00",
        )
        assert store.search_facts(ADA, action="On shift", valid_at="2026-01-01T07:30:00Z")["count"] == 1
        assert store.search_facts(ADA, action="On shift", valid_at="2026-01-01T06:30:00Z")["count"] == 0


class TestKindsAndMatching:
    def test_prefix_is_stored_as_kind_and_name_matches_case_insensitively(self, store):
        add(store, action="Partner", object="person:Bo Sample")
        found = store.search_facts(ADA, object="bo SAMPLE")["facts"]
        assert [(f["object"], f["object_kind"]) for f in found] == [("Bo Sample", "person")]

    def test_a_query_kind_matches_that_kind_or_an_unspecified_one(self, store):
        add(store, action="Knows", object="person:Bo Sample")
        add(store, action="Visited", object="place:Bo Sample")
        add(store, action="Mentioned", object="Bo Sample")
        assert store.search_facts(ADA, object="person:Bo Sample")["count"] == 2
        assert store.search_facts(ADA, object="place:Bo Sample")["count"] == 2
        assert store.search_facts(ADA, object="Bo Sample")["count"] == 3

    def test_kind_filters_are_exact(self, store):
        add(store, action="Knows", object="person:Bo Sample")
        add(store, action="Mentioned", object="Bo Sample")
        assert store.search_facts(ADA, object_kind="person")["count"] == 1
        with pytest.raises(ValidationError, match="object_kind"):
            store.search_facts(ADA, object_kind="vehicle")

    def test_unrecognised_prefix_stays_in_the_name(self, store):
        fact = add(store, subject="Meeting: standup", action="Is a", object="Event")
        assert (fact["subject"], fact["subject_kind"]) == ("Meeting: standup", None)

    def test_action_matching_is_case_and_whitespace_insensitive(self, store):
        add(store)
        assert store.search_facts(ADA, action="  has   BIRTHDAY ")["count"] == 1


class TestSearch:
    def test_newest_first_and_limit(self, store):
        for n in range(5):
            add(store, object=f"date:{1990 + n}")
        facts = store.search_facts(ADA, limit=3)["facts"]
        assert [f["object"] for f in facts] == ["1994", "1993", "1992"]

    def test_limit_is_clamped(self, store):
        assert store.search_facts(ADA, limit=10_000)["count"] == 0
        assert store.search_facts(ADA, limit=0)["count"] == 0

    def test_free_text_needs_every_word_in_any_order(self, store):
        add(store, subject="Ada Example", action="Lives in", object="place:Belfast")
        add(store, subject="Bo Sample", action="Lives in", object="place:Cork")
        assert store.search_facts(ADA, q="belfast ada")["count"] == 1
        assert store.search_facts(ADA, q="lives")["count"] == 2
        assert store.search_facts(ADA, q="belfast cork")["count"] == 0

    def test_free_text_treats_like_wildcards_literally(self, store):
        add(store, subject="100% Wool", action="Is a", object="Fabric")
        add(store, subject="1000 Wool", action="Is a", object="Fabric")
        assert store.search_facts(ADA, q="100%")["count"] == 1

    def test_attributes(self, store):
        add(store, object="date:1988-05-17", attributes={"source": "passport", "checked": True})
        add(store, object="date:1999-01-01", attributes={"source": "hearsay"})
        add(store, object="date:2000-01-01")
        assert store.search_facts(ADA, attribute_key="source")["count"] == 2
        found = store.search_facts(ADA, attribute_key="source", attribute_value="passport")["facts"]
        assert [f["object"] for f in found] == ["1988-05-17"]
        assert store.search_facts(ADA, attribute_key="checked", attribute_value="1")["count"] == 1

    def test_attribute_value_needs_a_key_and_keys_are_validated(self, store):
        with pytest.raises(ValidationError, match="needs attribute_key"):
            store.search_facts(ADA, attribute_value="x")
        with pytest.raises(ValidationError, match="attribute names"):
            store.search_facts(ADA, attribute_key='x"; DROP TABLE facts; --')

    def test_type_filters_follow_is_a_transitively(self, store):
        store.add_fact(ADA, "Ada Example", "Is a", "Person")
        store.add_fact(ADA, "Person", "Is a", "Agent")
        add(store, action="Knows", object="Cy Sample")
        add(store, subject="Rock", action="Knows", object="Cy Sample")
        found = store.search_facts(ADA, subject_type="Agent", action="Knows")["facts"]
        assert [f["subject"] for f in found] == ["Ada Example"]

    def test_type_cycles_terminate(self, store):
        store.add_fact(ADA, "A", "Is a", "B")
        store.add_fact(ADA, "B", "Is a", "A")
        # each is an instance of the other, so both match; the point is that the lookup terminates
        assert store.search_facts(ADA, subject_type="A")["count"] == 2

    def test_reviewed_before(self, store):
        old = add(store)
        store.mark_reviewed(ADA, old["id"], "confirmed")
        assert store.search_facts(ADA, reviewed_before="2000-01-01")["count"] == 0
        assert store.search_facts(ADA, reviewed_before="2100-01-01")["count"] == 1

    def test_unknown_scope(self, store):
        with pytest.raises(ValidationError, match="scope"):
            store.search_facts(ADA, scope="everyone")

    def test_alias_facts_are_hidden_unless_asked_for_by_action(self, store):
        store.add_alias(ADA, "A. Example", "person:Ada Example")
        add(store)
        assert store.search_facts(ADA)["count"] == 1
        assert store.search_facts(ADA, action="Alias of")["count"] == 1


class TestUpdate:
    def test_changes_only_what_is_supplied_and_records_who_and_when(self, store):
        fact = add(store, confidence=0.5, attributes={"a": 1}, references=["r"])
        updated = store.update_fact(ADA, fact["id"], confidence=0.9)
        assert updated["confidence"] == 0.9
        assert (updated["attributes"], updated["references"], updated["object"]) == ({"a": 1}, ["r"], "1988-05-17")
        assert updated["updated_by"] == ADA
        assert updated["updated_at"] >= updated["created_at"]

    def test_validity_can_be_set_and_cleared(self, store):
        fact = add(store, valid_from="2012", valid_to="2015")
        assert store.update_fact(ADA, fact["id"], valid_to=None)["valid_to"] is None
        assert store.update_fact(ADA, fact["id"], valid_to="2016")["valid_to"] == "2016"
        assert store.update_fact(ADA, fact["id"], valid_from=None)["valid_from"] is None

    def test_updated_validity_is_checked_against_the_stored_bound(self, store):
        fact = add(store, valid_from="2012", valid_to="2015")
        with pytest.raises(ValidationError, match="valid_to must not be before"):
            store.update_fact(ADA, fact["id"], valid_to="2010")

    def test_publish_and_unpublish(self, store):
        fact = add(store)
        assert store.update_fact(ADA, fact["id"], public=True)["public"] is True
        assert store.update_fact(ADA, fact["id"], public=False)["public"] is False

    def test_names_are_re_resolved(self, store):
        store.add_alias(ADA, "Bo", "person:Bo Sample")
        fact = add(store, action="Knows", object="Cy Sample")
        updated = store.update_fact(ADA, fact["id"], object="Bo")
        assert (updated["object"], updated["object_kind"]) == ("Bo Sample", "person")

    def test_attributes_and_references_replace(self, store):
        fact = add(store, attributes={"a": 1}, references=["r"])
        updated = store.update_fact(ADA, fact["id"], attributes={}, references=[])
        assert (updated["attributes"], updated["references"]) == ({}, [])

    def test_unset_sentinel_is_the_default(self, store):
        fact = add(store, valid_from="2012")
        assert store.update_fact(ADA, fact["id"], valid_from=UNSET)["valid_from"] == "2012"

    def test_only_the_creator_may_update_even_a_public_fact(self, store):
        fact = add(store, public=True)
        with pytest.raises(PermissionDeniedError):
            store.update_fact("bob", fact["id"], confidence=0.1)

    def test_a_private_fact_of_someone_else_does_not_exist(self, store):
        fact = add(store)
        with pytest.raises(NotFoundError):
            store.update_fact("bob", fact["id"], confidence=0.1)


class TestDelete:
    def test_removes_the_fact_and_its_review_records(self, store):
        fact = add(store)
        store.request_review(ADA, fact["id"], "bob")
        store.mark_reviewed(ADA, fact["id"], "confirmed")
        assert store.delete_fact(ADA, fact["id"]) == {"deleted": fact["id"]}
        with pytest.raises(NotFoundError):
            store.get_fact(ADA, fact["id"])
        assert store.pending_reviews("bob")["count"] == 0

    def test_only_the_creator_may_delete(self, store):
        fact = add(store, public=True)
        with pytest.raises(PermissionDeniedError):
            store.delete_fact("bob", fact["id"])
        assert store.get_fact(ADA, fact["id"])["id"] == fact["id"]
