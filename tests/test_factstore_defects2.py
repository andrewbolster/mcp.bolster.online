"""Defects found by the claims experiment: reviewer-side outcomes, accent-insensitive names, kind-prefix warnings,
review and validity filters, and free text over attributes and references."""

import pytest

from factstore import NoSelfBindingError, ValidationError
from factstore.config import Config
from factstore.schema import session
from factstore.values import actor_id, extras_text, fold, kind_prefix_warnings

ADA, BOB, CY = "ada", "bob", "cy"


def add(store, subject="Ada Example", action="Likes", obj="Tea", actor=ADA, **kwargs):
    return store.add_fact(actor, subject, action, obj, **kwargs)


def set_reviewed_at(store, fact_id, when):
    with session(store.path) as conn:
        conn.execute("UPDATE facts SET reviewed_at = ? WHERE id = ?", (when, fact_id))


# ------------------------------------------------------------------------------------------------ D5


class TestAccentInsensitiveNames:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("Zoë", "zoe"),
            ("ZOË", "Zoe"),
            ("Seán Ó Briain", "sean o briain"),
            ("Éamon", "EAMON"),
            ("Ångström", "angstrom"),
            ("Straße", "STRASSE"),
            ("  Is   À ", "is a"),
            ("ﬁnal", "final"),
        ],
    )
    def test_fold_ignores_case_accents_and_spacing(self, a, b):
        assert fold(a) == fold(b)

    def test_fold_still_tells_different_letters_apart(self):
        assert fold("Zoe") != fold("Zoa")
        assert fold("Ola") != fold("Ole")

    def test_any_spelling_finds_the_entity_and_its_facts(self, store):
        store.add_alias(ADA, "Zoë", "person:Zoe Example")
        add(store, "person:Zoe Example", "Likes", "Coffee")
        for spelling in ("Zoe", "ZOË", "zoë", "zoe"):
            assert store.search_facts(ADA, subject=spelling)["total"] == 1, spelling
        assert store.describe_entity(ADA, "ZOE")["exists"] is True

    def test_actions_and_objects_fold_the_same_way(self, store):
        add(store, "Ada Example", "Préfère", "Café")
        assert store.search_facts(ADA, action="prefere")["total"] == 1
        assert store.search_facts(ADA, object="CAFE")["total"] == 1

    def test_the_stored_name_keeps_its_accents(self, store):
        stored = add(store, "Zoë Example", "Likes", "Café")
        assert (stored["subject"], stored["object"]) == ("Zoë Example", "Café")


class TestActorsAreNotAccentFolded:
    """Folding a name must never merge two actors: that would let one read the other's private facts."""

    def test_accented_and_plain_logins_are_different_actors(self):
        assert actor_id("José") == "josé"
        assert actor_id("José") != actor_id("jose")

    def test_one_cannot_read_the_others_private_facts(self, store):
        add(store, "Jose Example", "Likes", "Tea", actor="jose")
        mine = add(store, "José Example", "Likes", "Jam", actor="josé")
        assert store.search_facts("josé", scope="all")["total"] == 1
        assert store.search_facts("jose", scope="all")["total"] == 1
        assert [f["id"] for f in store.search_facts("josé", scope="all")["facts"]] == [mine["id"]]

    def test_an_accented_login_can_still_bind_itself(self, store):
        store.set_self("josé", "person:Jose Example")
        add(store, "me", "Likes", "Tea", actor="josé")
        assert store.search_facts("josé", subject="me")["total"] == 1
        with pytest.raises(NoSelfBindingError):
            store.search_facts("jose", subject="me")


# ------------------------------------------------------------------------------------------------ D1


@pytest.fixture
def reviewed(store):
    """Ada owns two facts. Bob confirms one and disputes the other; Cy disputes the first."""
    first = add(store, "Ada Example", "Has birthday", "date:1988-05-17")
    second = add(store, "Ada Example", "Likes", "Tea")
    store.request_review(ADA, second["id"], BOB, note="please check")
    store.request_review(ADA, first["id"], BOB)
    store.request_review(ADA, first["id"], CY)
    store.mark_reviewed(BOB, first["id"], "confirmed", note="matches my records")
    store.mark_reviewed(BOB, second["id"], "disputed", note="she prefers coffee")
    store.mark_reviewed(CY, first["id"], "disputed", note="I remember May 18")
    return store, first, second


class TestReviewerSideOutcomes:
    def test_the_owner_view_is_unchanged_and_the_default(self, reviewed):
        store, first, second = reviewed
        listed = store.review_outcomes(ADA)
        assert listed["total"] == 3
        assert {(o["fact_id"], o["reviewer"], o["outcome"], o["role"]) for o in listed["outcomes"]} == {
            (first["id"], BOB, "confirmed", "owner"),
            (first["id"], CY, "disputed", "owner"),
            (second["id"], BOB, "disputed", "owner"),
        }

    def test_a_reviewer_gets_nothing_by_default_but_can_list_their_own_reviews(self, reviewed):
        store, first, second = reviewed
        assert store.review_outcomes(BOB)["total"] == 0  # owns nothing
        mine = store.review_outcomes(BOB, role="reviewer")
        assert mine["total"] == 2
        assert {(o["fact_id"], o["outcome"], o["role"], o["note"]) for o in mine["outcomes"]} == {
            (first["id"], "confirmed", "reviewer", "matches my records"),
            (second["id"], "disputed", "reviewer", "she prefers coffee"),
        }

    def test_a_reviewer_never_sees_what_another_reviewer_said(self, reviewed):
        store, first, _ = reviewed
        for who, expected in ((BOB, "confirmed"), (CY, "disputed")):
            entries = [o for o in store.review_outcomes(who, role="all")["outcomes"] if o["fact_id"] == first["id"]]
            assert [(o["reviewer"], o["outcome"]) for o in entries] == [(who, expected)]

    def test_on_a_public_fact_a_reviewer_still_sees_only_their_own_entry(self, store):
        public = add(store, "Ada Example", "Likes", "Jam", public=True)
        store.mark_reviewed(BOB, public["id"], "confirmed", note="bob's view")
        store.mark_reviewed(CY, public["id"], "unsure", note="cy's view")
        for who, role in ((BOB, "reviewer"), (BOB, "all"), (CY, "reviewer"), (CY, "all")):
            entries = store.review_outcomes(who, role=role)["outcomes"]
            assert [(o["reviewer"], o["role"]) for o in entries] == [(who, "reviewer")], (who, role)
        assert {o["reviewer"] for o in store.review_outcomes(ADA)["outcomes"]} == {BOB, CY}
        assert [o["note"] for o in store.review_outcomes(ADA, role="reviewer")["outcomes"]] == []

    def test_the_fact_wording_is_hidden_once_the_reviewers_access_has_ended(self, reviewed):
        store, first, second = reviewed
        entries = store.review_outcomes(BOB, role="reviewer")["outcomes"]
        assert {entry["fact_id"] for entry in entries} == {first["id"], second["id"]}
        for entry in entries:  # both requests are resolved and both facts are private
            assert "subject_ref" not in entry
            assert "action" not in entry
            assert "object_ref" not in entry

    def test_the_wording_is_shown_while_the_request_is_open_or_the_fact_is_public(self, store):
        private = add(store, "Ada Example", "Likes", "Tea")
        public = add(store, "Ada Example", "Likes", "Jam", public=True)
        store.request_review(ADA, private["id"], BOB)
        store.mark_reviewed(BOB, public["id"], "confirmed")
        open_view = {o["fact_id"]: o for o in store.review_outcomes(BOB, role="reviewer")["outcomes"]}
        assert open_view[public["id"]]["object_ref"] == "Jam"
        store.mark_reviewed(BOB, private["id"], "unsure")
        closed = {o["fact_id"]: o for o in store.review_outcomes(BOB, role="reviewer")["outcomes"]}
        assert "object_ref" not in closed[private["id"]]
        assert closed[public["id"]]["object_ref"] == "Jam"

    def test_all_lists_both_roles_and_never_a_review_twice(self, reviewed):
        store, first, _ = reviewed
        store.mark_reviewed(ADA, first["id"], "confirmed")  # the owner confirming her own fact
        bos = store.add_fact(BOB, "Bo Sample", "Likes", "Jam")
        store.request_review(BOB, bos["id"], ADA)
        store.mark_reviewed(ADA, bos["id"], "confirmed")  # her review of somebody else's fact
        listed = store.review_outcomes(ADA, role="all")
        roles = [o["role"] for o in listed["outcomes"]]
        ids = [o["review_id"] for o in listed["outcomes"]]
        assert listed["total"] == len(roles) == 5  # three from others and her own confirmation, plus the one she wrote
        assert sorted(roles) == ["owner"] * 4 + ["reviewer"]
        assert len(set(ids)) == 5
        assert store.review_outcomes(ADA, role="owner")["total"] == 4
        assert store.review_outcomes(ADA, role="reviewer")["total"] == 2  # her own two reviews, on either owner's fact

    def test_a_reviewers_own_confirmation_is_recorded_for_them(self, store):
        theirs = add(store, "Bo Sample", "Likes", "Jam", actor=BOB)
        store.request_review(BOB, theirs["id"], ADA)
        store.mark_reviewed(ADA, theirs["id"], "confirmed")
        assert store.review_outcomes(ADA, role="reviewer")["outcomes"][0]["outcome"] == "confirmed"

    def test_an_unknown_role_is_rejected(self, store):
        with pytest.raises(ValidationError, match="role"):
            store.review_outcomes(ADA, role="everyone")

    def test_paging_and_since_apply_to_the_reviewer_view(self, reviewed):
        store, _, _ = reviewed
        page = store.review_outcomes(BOB, role="reviewer", limit=1)
        assert (page["count"], page["total"], page["truncated"]) == (1, 2, True)
        assert store.review_outcomes(BOB, role="reviewer", since="2100-01-01")["total"] == 0


# ------------------------------------------------------------------------------------------------ D3


class TestKindPrefixWarnings:
    def test_an_unknown_prefix_is_stored_literally_and_the_reply_says_so(self, store):
        stored = add(store, "claim:Foo", "Is a", "Claim")
        assert stored["subject"] == "claim:Foo"
        assert stored["subject_kind"] is None
        assert "warnings" in stored
        assert "'claim'" in stored["warnings"][0] and "literal text" in stored["warnings"][0]

    def test_a_configured_kind_or_ordinary_text_gets_no_warning(self, store):
        for subject in ("person:Ada Example", "Meeting: standup", "http://example.com/x", "Ratio 3:4", "10:30 am"):
            assert "warnings" not in add(store, subject, "Likes", "Tea"), subject

    def test_object_names_are_checked_too(self, store):
        stored = add(store, "Ada Example", "Works at", "org:Acme")
        assert "warnings" not in stored
        stored = add(store, "Ada Example", "Works at", "employer:Acme")
        assert "employer" in stored["warnings"][0]

    def test_the_batch_names_the_item(self, store):
        result = store.add_many(
            ADA,
            [
                {"subject": "A", "action": "Likes", "object": "B"},
                {"subject": "claim:C", "action": "Likes", "object": "B"},
            ],
        )
        assert result["count"] == 2
        assert len(result["warnings"]) == 1 and result["warnings"][0].startswith("Item 1:")

    def test_update_search_describe_and_relationships_warn_about_the_names_they_were_given(self, store):
        fact = add(store, "Ada Example", "Likes", "Tea")
        assert "claim" in store.update_fact(ADA, fact["id"], subject="claim:Ada")["warnings"][0]
        assert "claim" in store.search_facts(ADA, subject="claim:Ada")["warnings"][0]
        assert "claim" in store.describe_entity(ADA, "claim:Ada")["warnings"][0]
        assert "claim" in store.relationships_between(ADA, "claim:Ada", "Tea")["warnings"][0]
        assert "warnings" not in store.search_facts(ADA, subject="Tea")

    def test_binding_yourself_to_an_unknown_prefix_warns(self, store):
        assert "warnings" in store.set_self(ADA, "claim:Ada")

    def test_the_helper_lists_the_configured_kinds(self):
        (message,) = kind_prefix_warnings(Config(), {"subject": "claim:Foo"})
        assert "person" in message and "org" in message

    def test_an_unconfigured_kind_filter_names_the_configured_ones(self, store):
        with pytest.raises(ValidationError, match=r"not a configured kind.*date, number, org"):
            store.search_facts(ADA, subject="Ada", subject_kind="claim")
        with pytest.raises(ValidationError, match="literal text"):
            store.search_facts(ADA, object="Tea", object_kind="claim")


# ------------------------------------------------------------------------------------------------ D4


class TestReviewedFilters:
    @pytest.fixture
    def three(self, store):
        old = add(store, "A", "Likes", "One")
        recent = add(store, "B", "Likes", "Two")
        never = add(store, "C", "Likes", "Three")
        set_reviewed_at(store, old["id"], "2020-01-01T00:00:00.000Z")
        store.mark_reviewed(ADA, recent["id"], "confirmed")
        return store, old, recent, never

    @staticmethod
    def ids(result):
        return {fact["id"] for fact in result["facts"]}

    def test_reviewed_before_only_matches_facts_that_have_been_reviewed(self, three):
        store, old, recent, never = three
        assert self.ids(store.search_facts(ADA, reviewed_before="2021-01-01")) == {old["id"]}
        assert self.ids(store.search_facts(ADA, reviewed_before="2100-01-01")) == {old["id"], recent["id"]}

    def test_include_never_reviewed_counts_creation_as_the_baseline(self, three):
        store, old, recent, never = three
        everything = {old["id"], recent["id"], never["id"]}
        assert (
            self.ids(store.search_facts(ADA, reviewed_before="2100-01-01", include_never_reviewed=True)) == everything
        )
        assert self.ids(store.search_facts(ADA, reviewed_before="2021-01-01", include_never_reviewed=True)) == {
            old["id"]
        }

    def test_reviewed_true_and_false(self, three):
        store, old, recent, never = three
        assert self.ids(store.search_facts(ADA, reviewed=True)) == {old["id"], recent["id"]}
        assert self.ids(store.search_facts(ADA, reviewed=False)) == {never["id"]}

    def test_never_reviewed_before_a_cutoff_needs_the_baseline_flag(self, three):
        store, _, _, never = three
        with pytest.raises(ValidationError, match="include_never_reviewed"):
            store.search_facts(ADA, reviewed=False, reviewed_before="2100-01-01")
        listed = store.search_facts(ADA, reviewed=False, reviewed_before="2100-01-01", include_never_reviewed=True)
        assert self.ids(listed) == {never["id"]}


# ------------------------------------------------------------------------------------------------ D6


class TestValidityFilters:
    @pytest.fixture
    def periods(self, store):
        made = {
            "inside": add(store, "P1", "Is", "Inside", valid_from="2021", valid_to="2022"),
            "wider": add(store, "P2", "Is", "Wider", valid_from="2019", valid_to="2024"),
            "open_start": add(store, "P3", "Is", "OpenStart", valid_to="2022"),
            "open_end": add(store, "P4", "Is", "OpenEnd", valid_from="2021"),
            "none": add(store, "P5", "Is", "NoPeriod"),
            "exact": add(store, "P6", "Is", "Exact", valid_from="2020", valid_to="2023"),
        }
        return store, made

    @staticmethod
    def names(result):
        return {fact["subject"] for fact in result["facts"]}

    def test_the_default_is_overlap_and_keeps_open_and_missing_periods(self, periods):
        store, _ = periods
        found = store.search_facts(ADA, valid_from="2020", valid_to="2023")
        assert self.names(found) == {"P1", "P2", "P3", "P4", "P5", "P6"}

    def test_valid_within_keeps_only_periods_that_fit_inside_the_window(self, periods):
        store, _ = periods
        found = store.search_facts(ADA, valid_from="2020", valid_to="2023", valid_within=True)
        assert self.names(found) == {"P1", "P6"}  # P2 starts before the window, P3/P4 are open, P5 has no period

    def test_a_one_sided_window_only_constrains_that_side(self, periods):
        store, _ = periods
        assert self.names(store.search_facts(ADA, valid_from="2020", valid_within=True)) == {"P1", "P4", "P6"}
        assert self.names(store.search_facts(ADA, valid_to="2022", valid_within=True)) == {"P1", "P3"}

    def test_valid_within_needs_a_window(self, store):
        with pytest.raises(ValidationError, match="valid_within needs"):
            store.search_facts(ADA, valid_within=True)
        with pytest.raises(ValidationError, match="valid_within needs"):
            store.search_facts(ADA, valid_at="2021", valid_within=True)

    def test_has_period(self, periods):
        store, _ = periods
        assert self.names(store.search_facts(ADA, has_period=True)) == {"P1", "P2", "P3", "P4", "P6"}
        assert self.names(store.search_facts(ADA, has_period=False)) == {"P5"}
        assert self.names(store.search_facts(ADA, has_period=None)) == {"P1", "P2", "P3", "P4", "P5", "P6"}

    def test_the_two_combine(self, periods):
        store, _ = periods
        found = store.search_facts(ADA, valid_from="2019", valid_to="2024", valid_within=True, has_period=True)
        assert self.names(found) == {"P1", "P2", "P6"}


# ------------------------------------------------------------------------------------------------ D8


class TestFreeTextCoversAttributesAndReferences:
    def test_attribute_values_keys_and_nested_values_are_searched(self, store):
        add(store, "Claim 1", "States", "Housing rose", attributes={"statement": "Prices anchored by hospitals"})
        add(store, "Claim 2", "States", "Jobs fell", attributes={"evidence": {"source_pr": "PR 2289"}})
        assert store.search_facts(ADA, q="anchored hospitals")["total"] == 1
        assert store.search_facts(ADA, q="statement")["total"] == 1  # an attribute name
        assert store.search_facts(ADA, q="2289")["total"] == 1  # nested
        assert store.search_facts(ADA, q="nonexistent")["total"] == 0

    def test_references_are_searched(self, store):
        add(store, "Claim 3", "States", "Rents rose", references=["https://github.com/example/repo/pull/2291"])
        assert store.search_facts(ADA, q="pull/2291")["total"] == 1

    def test_matching_ignores_case_and_accents_inside_attributes(self, store):
        add(store, "Claim 4", "States", "Cafés", attributes={"note": "Zoë ordered a CAFÉ"})
        assert store.search_facts(ADA, q="zoe cafe")["total"] == 1
        assert store.search_facts(ADA, q="ZOË")["total"] == 1

    def test_every_word_must_match_across_name_and_extras(self, store):
        add(store, "Claim 5", "States", "Housing", attributes={"note": "rose sharply"})
        assert store.search_facts(ADA, q="housing sharply")["total"] == 1
        assert store.search_facts(ADA, q="housing falling")["total"] == 0

    def test_it_never_leaks_another_actors_private_attributes(self, store):
        add(store, "Claim 6", "States", "Secret", attributes={"note": "tangerine"}, references=["tangerine-ref"])
        for scope in ("mine", "public", "all"):
            assert store.search_facts(BOB, scope=scope, q="tangerine")["total"] == 0, scope
        assert store.search_facts(ADA, q="tangerine")["total"] == 1

    def test_the_helper_flattens_everything_it_is_given(self):
        text = extras_text('{"a": {"b": ["X", 2]}, "c": null}', '["Ref Y"]')
        assert all(word in text.split() for word in ("a", "b", "x", "2", "c", "ref", "y"))
        assert extras_text(None, None) == ""
        assert "not json" in extras_text("not json", None)
