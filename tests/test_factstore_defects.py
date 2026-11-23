"""Defects found by the catalogue experiment: kind disambiguation, dispute polarity, review outcomes, paging,
kinds in results, existence, due-list filters, the opt-in type hint and the batch write."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from factstore import AmbiguousEntityError, NotFoundError, ValidationError
from factstore.schema import session
from factstore.values import iso

ADA, BOB, CY = "ada", "bob", "cy"


def fill(store, facts, actor=ADA):
    """Write any number of facts through add_many, in batches the engine accepts."""
    for start in range(0, len(facts), 100):
        store.add_many(actor, facts[start : start + 100])


def backdate(store, fact_id, days):
    with session(store.path) as conn:
        conn.execute(
            "UPDATE facts SET created_at = ? WHERE id = ?", (iso(datetime.now(UTC) - timedelta(days=days)), fact_id)
        )


# ------------------------------------------------------------------------------------------------ B1


@pytest.fixture
def sams(store):
    """'Sam' is an alias of both a person and an organisation, each with one fact."""
    store.add_alias(ADA, "Sam", "person:Sam Sample")
    store.add_alias(ADA, "Sam", "org:Sam Corp")
    store.add_fact(ADA, "person:Sam Sample", "Likes", "Tea")
    store.add_fact(ADA, "org:Sam Corp", "Based in", "place:Belfast")
    return store


class TestKindDisambiguation:
    def test_a_bare_name_is_still_ambiguous_and_the_advice_works(self, sams):
        with pytest.raises(AmbiguousEntityError) as caught:
            sams.search_facts(ADA, subject="Sam")
        assert sorted(caught.value.candidates) == ["org:Sam Corp", "person:Sam Sample"]
        advice = str(caught.value)
        assert "kind prefix" in advice
        assert "'person:Sam'" in advice
        assert [f["action"] for f in sams.search_facts(ADA, subject="person:Sam")["facts"]] == ["Likes"]

    def test_a_kind_prefix_picks_the_entity(self, sams):
        assert [f["action"] for f in sams.search_facts(ADA, subject="person:Sam")["facts"]] == ["Likes"]
        assert [f["action"] for f in sams.search_facts(ADA, subject="org:Sam")["facts"]] == ["Based in"]

    def test_a_kind_filter_picks_the_entity_too(self, sams):
        facts = sams.search_facts(ADA, subject="Sam", subject_kind="org")["facts"]
        assert [f["action"] for f in facts] == ["Based in"]

    def test_the_object_side_is_disambiguated(self, sams):
        sams.add_fact(ADA, "Bo Sample", "Works for", "org:Sam Corp")
        sams.add_fact(ADA, "Bo Sample", "Knows", "person:Sam Sample")
        assert [f["action"] for f in sams.search_facts(ADA, object="org:Sam")["facts"]] == ["Works for"]
        assert [f["action"] for f in sams.search_facts(ADA, object="Sam", object_kind="person")["facts"]] == ["Knows"]

    def test_writing_with_a_kind_prefix_stores_the_chosen_entity(self, sams):
        stored = sams.add_fact(ADA, "org:Sam", "Employs", "Bo Sample")
        assert (stored["subject"], stored["subject_kind"]) == ("Sam Corp", "org")

    def test_relationships_between_accepts_a_kind_prefix(self, sams):
        found = sams.relationships_between(ADA, "org:Sam", "place:Belfast")
        assert [f["action"] for f in found["direct"]] == ["Based in"]
        assert found["a"] == "org:Sam Corp"

    def test_still_ambiguous_after_the_kind_is_applied_lists_the_candidates(self, sams):
        sams.add_alias(ADA, "Sam", "org:Sam Industries")
        with pytest.raises(AmbiguousEntityError) as caught:
            sams.search_facts(ADA, subject="org:Sam")
        assert sorted(caught.value.candidates) == ["org:Sam Corp", "org:Sam Industries"]
        assert "full names" in str(caught.value)
        assert "kind prefix" not in str(caught.value)  # a prefix would not help, so the message must not say so

    def test_a_kind_none_of_them_has_says_so(self, sams):
        with pytest.raises(AmbiguousEntityError) as caught:
            sams.search_facts(ADA, subject="place:Sam")
        assert "None of them is of kind 'place'" in str(caught.value)
        assert sorted(caught.value.candidates) == ["org:Sam Corp", "person:Sam Sample"]


# ------------------------------------------------------------------------------------------------ B2


def disputable(store, confidence):
    fact = store.add_fact(ADA, "Ada Example", "Partner", "person:Bo Sample", confidence=confidence)
    store.request_review(ADA, fact["id"], BOB)
    return fact


class TestDisputePolarity:
    @pytest.mark.parametrize(
        ("disputed", "expected"),
        [(1.0, -1.0), (0.6, -1.0), (0.0, -1.0), (-0.3, 1.0), (-1.0, 1.0)],
    )
    def test_the_counter_fact_takes_the_opposite_sign(self, store, disputed, expected):
        fact = disputable(store, disputed)
        result = store.mark_reviewed(BOB, fact["id"], "disputed")
        counter = result["counter_fact"]
        assert counter["confidence"] == expected
        assert counter["created_by"] == BOB
        assert (counter["subject"], counter["action"], counter["object"]) == ("Ada Example", "Partner", "Bo Sample")
        assert counter["references"] == [f"fact:{fact['id']}"]
        assert store.get_fact(ADA, fact["id"])["confidence"] == disputed  # the owner's fact is untouched

    def test_a_reviewer_can_state_a_graded_dispute(self, store):
        fact = disputable(store, 0.6)
        counter = store.mark_reviewed(BOB, fact["id"], "disputed", confidence=-0.4)["counter_fact"]
        assert counter["confidence"] == -0.4

    def test_a_graded_confirmation_of_a_falsification_is_positive(self, store):
        fact = disputable(store, -1.0)
        assert store.mark_reviewed(BOB, fact["id"], "disputed", confidence=0.25)["counter_fact"]["confidence"] == 0.25

    @pytest.mark.parametrize("wrong", [0.4, 0.0, 1.0])
    def test_the_wrong_sign_is_refused_and_writes_nothing(self, store, wrong):
        fact = disputable(store, 0.6)
        with pytest.raises(ValidationError, match="opposite"):
            store.mark_reviewed(BOB, fact["id"], "disputed", confidence=wrong)
        assert store.search_facts(BOB, include_negative=True)["total"] == 0
        assert store.pending_reviews(BOB)["total"] == 1  # the request is still open

    def test_the_stated_confidence_is_range_checked(self, store):
        fact = disputable(store, 0.6)
        with pytest.raises(ValidationError, match="between -1.0 and 1.0"):
            store.mark_reviewed(BOB, fact["id"], "disputed", confidence=-2)

    def test_confidence_only_applies_to_disputes(self, store):
        fact = disputable(store, 0.6)
        with pytest.raises(ValidationError, match="disputed"):
            store.mark_reviewed(BOB, fact["id"], "confirmed", confidence=-0.4)

    def test_an_owner_cannot_use_it_on_their_own_fact(self, store):
        fact = store.add_fact(ADA, "Ada Example", "Likes", "Tea")
        with pytest.raises(ValidationError, match="update_fact"):
            store.mark_reviewed(ADA, fact["id"], "disputed", confidence=-0.5)


# ------------------------------------------------------------------------------------------------ B3


@pytest.fixture
def reviewed(store):
    """Ada's public fact, confirmed by Bob and disputed by Cy."""
    fact = store.add_fact(ADA, "Ada Example", "Has birthday", "date:1988-05-17", public=True)
    store.mark_reviewed(BOB, fact["id"], "confirmed", note="checked the passport")
    store.mark_reviewed(CY, fact["id"], "disputed", note="I remember May 18")
    return fact


class TestReviewOutcomes:
    def test_the_owner_sees_every_outcome_on_their_fact(self, store, reviewed):
        listed = store.get_fact(ADA, reviewed["id"])["reviews"]
        assert {(r["reviewer"], r["outcome"], r["note"]) for r in listed} == {
            (BOB, "confirmed", "checked the passport"),
            (CY, "disputed", "I remember May 18"),
        }
        assert all(set(r) == {"reviewer", "outcome", "note", "at"} for r in listed)

    def test_a_reviewer_sees_only_their_own_entries(self, store, reviewed):
        assert [r["reviewer"] for r in store.get_fact(BOB, reviewed["id"])["reviews"]] == [BOB]
        assert [r["reviewer"] for r in store.get_fact(CY, reviewed["id"])["reviews"]] == [CY]

    def test_a_stranger_has_no_entries_and_cannot_read_a_private_fact_at_all(self, store, reviewed):
        assert store.get_fact("dan", reviewed["id"])["reviews"] == []  # the fact is public; dan reviewed nothing
        private = store.add_fact(ADA, "Ada Example", "Likes", "Tea")
        store.request_review(ADA, private["id"], BOB)
        store.mark_reviewed(BOB, private["id"], "unsure")
        with pytest.raises(NotFoundError):
            store.get_fact("dan", private["id"])

    def test_entries_are_newest_first(self, store, reviewed):
        with session(store.path) as conn:
            conn.execute(
                "UPDATE reviews SET at = ? WHERE reviewer = ?",
                (iso(datetime.now(UTC) - timedelta(days=3)), BOB),
            )
        assert [r["reviewer"] for r in store.get_fact(ADA, reviewed["id"])["reviews"]] == [CY, BOB]

    def test_the_list_is_capped(self, store):
        fact = store.add_fact(ADA, "Ada Example", "Likes", "Tea")
        for _ in range(25):
            store.mark_reviewed(ADA, fact["id"], "unsure")
        assert len(store.get_fact(ADA, fact["id"])["reviews"]) == store.config.max_reviews_shown == 20

    def test_a_dispute_never_exposes_the_reviewers_counter_fact_to_the_owner(self, store, reviewed):
        counter = next(f for f in store.search_facts(CY, include_negative=True, scope="mine")["facts"])
        assert counter["confidence"] == -1.0
        as_owner = store.get_fact(ADA, reviewed["id"])
        assert counter["id"] not in json.dumps(as_owner)
        owner_facts = store.search_facts(ADA, scope="all", include_negative=True)["facts"]
        assert [f["id"] for f in owner_facts] == [reviewed["id"]]
        with pytest.raises(NotFoundError):
            store.get_fact(ADA, counter["id"])

    def test_review_outcomes_lists_what_others_said_about_my_facts(self, store, reviewed):
        listed = store.review_outcomes(ADA)
        assert listed["total"] == 2 and listed["truncated"] is False
        assert {(o["reviewer"], o["outcome"]) for o in listed["outcomes"]} == {(BOB, "confirmed"), (CY, "disputed")}
        first = listed["outcomes"][0]
        assert (first["fact_id"], first["subject_ref"], first["action"], first["object_ref"]) == (
            reviewed["id"], "Ada Example", "Has birthday", "date:1988-05-17",
        )  # fmt: skip
        assert "counter" not in json.dumps(listed)

    def test_review_outcomes_is_owner_only(self, store, reviewed):
        assert store.review_outcomes(BOB)["total"] == 0  # bob made a review but owns no facts
        assert store.review_outcomes(CY)["outcomes"] == []
        assert store.review_outcomes("dan")["total"] == 0

    def test_review_outcomes_filters_by_time_and_pages(self, store, reviewed):
        with session(store.path) as conn:
            conn.execute(
                "UPDATE reviews SET at = ? WHERE reviewer = ?",
                (iso(datetime.now(UTC) - timedelta(days=10)), BOB),
            )
        recent = store.review_outcomes(ADA, since=iso(datetime.now(UTC) - timedelta(days=1)))
        assert [o["reviewer"] for o in recent["outcomes"]] == [CY]
        page = store.review_outcomes(ADA, limit=1)
        assert (page["count"], page["total"], page["truncated"]) == (1, 2, True)
        rest = store.review_outcomes(ADA, limit=1, offset=1)
        assert (rest["count"], rest["truncated"]) == (1, False)
        assert page["outcomes"][0]["review_id"] != rest["outcomes"][0]["review_id"]

    def test_deleting_a_fact_removes_its_outcomes(self, store, reviewed):
        store.delete_fact(ADA, reviewed["id"])
        assert store.review_outcomes(ADA)["total"] == 0


# ------------------------------------------------------------------------------------------------ B4


@pytest.fixture
def crowd(store):
    """250 of Ada's facts, more than the largest page."""
    fill(store, [{"subject": f"Item {n}", "action": "Is in", "object": "place:Belfast"} for n in range(250)])
    return store


class TestPaging:
    def test_a_full_page_reports_the_total_and_that_it_is_truncated(self, crowd):
        page = crowd.search_facts(ADA, limit=200)
        assert (page["count"], page["total"], page["offset"], page["limit"], page["truncated"]) == (
            200, 250, 0, 200, True,
        )  # fmt: skip

    def test_the_default_page_is_fifty_and_says_there_is_more(self, crowd):
        page = crowd.search_facts(ADA)
        assert (page["count"], page["total"], page["truncated"]) == (50, 250, True)

    def test_offset_reads_the_rest_with_no_gap_or_overlap(self, crowd):
        first = crowd.search_facts(ADA, limit=200)
        rest = crowd.search_facts(ADA, limit=200, offset=200)
        assert (rest["count"], rest["total"], rest["truncated"]) == (50, 250, False)
        ids = [f["id"] for f in first["facts"]] + [f["id"] for f in rest["facts"]]
        assert len(ids) == len(set(ids)) == 250

    def test_an_exact_fit_is_not_truncated(self, crowd):
        page = crowd.search_facts(ADA, limit=100, offset=150)
        assert (page["count"], page["truncated"]) == (100, False)

    def test_an_empty_result_has_a_total_of_zero(self, store):
        assert store.search_facts(ADA, subject="Nobody") == {
            "count": 0, "total": 0, "offset": 0, "limit": 50, "truncated": False, "facts": [],
        }  # fmt: skip

    @pytest.mark.parametrize("bad", [-1, "2", 1.5, True])
    def test_offset_must_be_a_whole_number(self, store, bad):
        with pytest.raises(ValidationError, match="offset"):
            store.search_facts(ADA, offset=bad)

    def test_pending_reviews_pages(self, store):
        for n in range(3):
            fact = store.add_fact(ADA, f"Item {n}", "Is in", "place:Belfast")
            store.request_review(ADA, fact["id"], BOB)
        first = store.pending_reviews(BOB, limit=2)
        assert (first["count"], first["total"], first["truncated"]) == (2, 3, True)
        rest = store.pending_reviews(BOB, limit=2, offset=2)
        assert (rest["count"], rest["truncated"], len(rest["requests"])) == (1, False, 1)
        assert store.pending_reviews(ADA, "sent")["total"] == 3

    def test_due_for_review_pages(self, crowd):
        page = crowd.due_for_review(ADA, before="2999-01-01", limit=200)
        assert (page["count"], page["total"], page["truncated"]) == (200, 250, True)
        rest = crowd.due_for_review(ADA, before="2999-01-01", limit=200, offset=200)
        assert (rest["count"], rest["truncated"]) == (50, False)

    def test_relationships_say_when_direct_facts_are_cut_off(self, store):
        fill(store, [{"subject": "Ada Example", "action": "Visited", "object": "place:Belfast"}] * 200)
        exact = store.relationships_between(ADA, "Ada Example", "place:Belfast")
        assert (len(exact["direct"]), exact["direct_truncated"]) == (200, False)
        store.add_fact(ADA, "Ada Example", "Visited", "place:Belfast")
        more = store.relationships_between(ADA, "Ada Example", "place:Belfast")
        assert (len(more["direct"]), more["direct_truncated"], more["indirect_truncated"]) == (200, True, False)

    def test_relationships_say_when_paths_are_cut_off(self, store):
        facts = []
        for n in range(101):
            facts += [
                {"subject": "Ada Example", "action": "Knows", "object": f"Mid {n}"},
                {"subject": f"Mid {n}", "action": "Knows", "object": "Target Corp"},
            ]
        fill(store, facts)
        found = store.relationships_between(ADA, "Ada Example", "Target Corp", max_depth=2)
        assert (len(found["indirect"]), found["indirect_truncated"]) == (100, True)


# ------------------------------------------------------------------------------------------------ B5


class TestKindsInResults:
    def test_a_returned_name_goes_straight_back_into_a_query(self, sams):
        stored = sams.add_fact(ADA, "org:Sam", "Employs", "Bo Sample")
        assert (stored["subject_ref"], stored["object_ref"]) == ("org:Sam Corp", "Bo Sample")
        again = sams.search_facts(ADA, subject=stored["subject_ref"], action="Employs")
        assert [f["id"] for f in again["facts"]] == [stored["id"]]  # although bare "Sam" is ambiguous

    def test_a_name_with_no_kind_round_trips_unchanged(self, store):
        fact = store.add_fact(ADA, "Meeting: standup", "Is held in", "Room 4")
        assert fact["subject_kind"] is None and fact["subject_ref"] == "Meeting: standup"
        assert store.search_facts(ADA, subject=fact["subject_ref"])["total"] == 1

    def test_every_listing_carries_the_refs(self, store):
        fact = store.add_fact(ADA, "Ada Example", "Has birthday", "date:1988-05-17")
        store.request_review(ADA, fact["id"], BOB)
        assert store.search_facts(ADA)["facts"][0]["object_ref"] == "date:1988-05-17"
        assert store.pending_reviews(BOB)["requests"][0]["fact"]["object_ref"] == "date:1988-05-17"
        assert store.due_for_review(ADA, before="2999-01-01")["facts"][0]["object_ref"] == "date:1988-05-17"
        assert store.get_fact(ADA, fact["id"])["subject_ref"] == "Ada Example"

    def test_refs_are_derived_so_a_backup_does_not_store_them(self, store):
        store.add_fact(ADA, "org:Sam Corp", "Likes", "Tea")
        import io

        out = io.StringIO()
        store.export_jsonl(out, ADA)
        line = json.loads(out.getvalue().splitlines()[1])
        assert "subject_ref" not in line and "object_ref" not in line


# ------------------------------------------------------------------------------------------------ B6


class TestExists:
    def test_unknown_is_not_the_same_as_known_but_empty(self, store):
        assert store.describe_entity(ADA, "Totally Unknown Dataset")["exists"] is False
        store.add_fact(ADA, "Known Thing", "Is a", "Dataset", confidence=-1.0)
        known = store.describe_entity(ADA, "Known Thing")
        assert known["exists"] is True
        assert (known["facts_as_subject"], known["facts_as_object"]) == (0, 0)  # only a falsification mentions it

    def test_an_entity_that_is_only_an_alias_target_exists(self, store):
        store.add_alias(ADA, "Sam", "person:Sam Sample")
        assert store.describe_entity(ADA, "Sam")["exists"] is True
        assert store.describe_entity(ADA, "person:Sam Sample")["ref"] == "person:Sam Sample"

    def test_existence_respects_visibility(self, store):
        store.add_fact(ADA, "Secret Thing", "Likes", "Tea")
        assert store.describe_entity(ADA, "Secret Thing")["exists"] is True
        assert store.describe_entity(BOB, "Secret Thing", scope="all")["exists"] is False
        store.add_fact(ADA, "Open Thing", "Likes", "Tea", public=True)
        assert store.describe_entity(BOB, "Open Thing", scope="public")["exists"] is True


# ------------------------------------------------------------------------------------------------ B7


@pytest.fixture
def due(store):
    old = store.add_fact(ADA, "Ada Example", "Has birthday", "date:1988-05-17", confidence=1.0)
    mid = store.add_fact(ADA, "Ada Example", "Partner", "person:Bo Sample", confidence=0.3)
    new = store.add_fact(ADA, "Bo Sample", "Likes", "Tea", confidence=0.8)
    for fact, days in ((old, 30), (mid, 20), (new, 10)):
        backdate(store, fact["id"], days)
    return {"old": old["id"], "mid": mid["id"], "new": new["id"]}


def due_ids(store, **filters):
    return [f["id"] for f in store.due_for_review(ADA, before="2999-01-01", **filters)["facts"]]


class TestDueForReview:
    def test_the_default_order_is_oldest_first(self, store, due):
        assert due_ids(store) == [due["old"], due["mid"], due["new"]]

    def test_lowest_confidence_first(self, store, due):
        assert due_ids(store, order="lowest_confidence") == [due["mid"], due["new"], due["old"]]

    def test_newest_first(self, store, due):
        assert due_ids(store, order="newest") == [due["new"], due["mid"], due["old"]]

    def test_an_unknown_order_is_refused(self, store, due):
        with pytest.raises(ValidationError, match="order"):
            store.due_for_review(ADA, order="random")

    def test_filter_by_action_ignores_case(self, store, due):
        assert due_ids(store, action="has BIRTHDAY") == [due["old"]]

    def test_filter_by_subject_resolves_aliases(self, store, due):
        store.add_alias(ADA, "AE", "Ada Example")
        found = due_ids(store, subject="AE")
        assert due["old"] in found and due["mid"] in found and due["new"] not in found
        assert due_ids(store, subject="Nobody Here") == []

    def test_filter_by_object_kind(self, store, due):
        assert due_ids(store, object_kind="date") == [due["old"]]
        assert due_ids(store, object_kind="person") == [due["mid"]]
        with pytest.raises(ValidationError, match="object_kind"):
            store.due_for_review(ADA, object_kind="galaxy")

    def test_filter_by_creation_time(self, store, due):
        cutoff = iso(datetime.now(UTC) - timedelta(days=15))
        assert due_ids(store, created_before=cutoff) == [due["old"], due["mid"]]

    def test_filters_combine_and_total_counts_the_filtered_set(self, store, due):
        result = store.due_for_review(ADA, before="2999-01-01", subject="Ada Example", limit=1)
        assert (result["count"], result["total"], result["truncated"], result["order"]) == (
            1, 2, True, "oldest_reviewed",
        )  # fmt: skip
        assert result["facts"][0]["id"] == due["old"]

    def test_only_my_own_facts_are_listed(self, store, due):
        assert store.due_for_review(BOB, before="2999-01-01")["total"] == 0


# ------------------------------------------------------------------------------------------------ friction 10


def test_the_type_hint_is_opt_in(store):
    assert "untyped" not in store.add_fact(ADA, "Ada Example", "Partner", "person:Bo Sample")
    hinted = store.add_fact(ADA, "Ada Example", "Partner", "person:Bo Sample", check_types=True)
    assert hinted["untyped"] == ["Ada Example", "person:Bo Sample"]


# ------------------------------------------------------------------------------------------------ batch write


class TestAddMany:
    def test_stores_every_fact_and_returns_ids_in_order(self, store):
        result = store.add_many(
            ADA,
            [
                {"subject": "Ada Example", "action": "Likes", "object": "Tea"},
                {"subject": "Ada Example", "action": "Has birthday", "object": "date:1988-05-17", "confidence": 0.9},
                {"subject": "Bo Sample", "action": "Likes", "object": "Coffee", "public": True, "attributes": {"a": 1}},
            ],
        )
        assert result["count"] == 3 and len(result["ids"]) == 3
        stored = [store.get_fact(ADA, fact_id) for fact_id in result["ids"]]
        assert [f["object"] for f in stored] == ["Tea", "1988-05-17", "Coffee"]
        assert stored[1]["confidence"] == 0.9 and stored[2]["public"] is True and stored[2]["attributes"] == {"a": 1}
        assert stored[0]["created_by"] == ADA

    def test_a_bad_item_writes_nothing_and_names_its_position(self, store):
        before = store.search_facts(ADA)["total"]
        with pytest.raises(ValidationError, match=r"Item 2: .*between -1.0 and 1.0"):
            store.add_many(
                ADA,
                [
                    {"subject": "A", "action": "Likes", "object": "B"},
                    {"subject": "A. Example", "action": "Alias of", "object": "person:Ada Example"},
                    {"subject": "C", "action": "Likes", "object": "D", "confidence": 5},
                ],
            )
        assert store.search_facts(ADA, include_negative=True)["total"] == before == 0
        assert store.search_facts(ADA, action="Alias of")["total"] == 0  # the alias from item 1 was rolled back too

    def test_later_items_can_use_aliases_made_earlier_in_the_batch(self, store):
        store.add_many(
            ADA,
            [
                {"subject": "A. Example", "action": "Alias of", "object": "person:Ada Example"},
                {"subject": "A. Example", "action": "Likes", "object": "Tea"},
            ],
        )
        found = store.search_facts(ADA, subject="Ada Example")["facts"]
        assert [(f["subject"], f["subject_kind"]) for f in found] == [("Ada Example", "person")]

    def test_the_cap_is_one_hundred(self, store):
        batch = [{"subject": f"S{n}", "action": "Likes", "object": "Tea"} for n in range(101)]
        with pytest.raises(ValidationError, match="at most 100"):
            store.add_many(ADA, batch)
        assert store.search_facts(ADA)["total"] == 0
        assert store.add_many(ADA, batch[:100])["count"] == 100

    @pytest.mark.parametrize("bad", [[], None, "nope", {"subject": "A"}])
    def test_it_needs_a_non_empty_list(self, store, bad):
        with pytest.raises(ValidationError, match="non-empty list"):
            store.add_many(ADA, bad)

    def test_items_must_be_complete_known_objects(self, store):
        with pytest.raises(ValidationError, match=r"Item 0: missing object"):
            store.add_many(ADA, [{"subject": "A", "action": "Likes"}])
        with pytest.raises(ValidationError, match=r"Item 1: unknown field\(s\) colour"):
            store.add_many(
                ADA,
                [
                    {"subject": "A", "action": "Likes", "object": "B"},
                    {"subject": "A", "action": "B", "object": "C", "colour": 1},
                ],
            )
        with pytest.raises(ValidationError, match=r"Item 0: each fact must be an object"):
            store.add_many(ADA, ["not a fact"])

    def test_batches_are_private_to_the_actor_like_any_other_write(self, store):
        store.add_many(ADA, [{"subject": "A", "action": "Likes", "object": "B"}])
        assert store.search_facts(BOB, scope="all")["total"] == 0
