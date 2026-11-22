"""Aliases are facts: write-time canonicalisation, query-time expansion, chains, cycles, ambiguity and 'me'."""

import pytest

from factstore import AmbiguousEntityError, NoSelfBindingError, ValidationError

ADA = "ada"


@pytest.fixture
def ada(store):
    """Ada is bound to 'person:Ada Example' and has two aliases for herself."""
    store.set_self(ADA, "person:Ada Example")
    store.add_alias(ADA, "bolster", "person:Ada Example")
    store.add_alias(ADA, "A. Example", "Ada Example")
    return store


class TestWriteTimeCanonicalisation:
    def test_an_alias_is_stored_under_the_canonical_name(self, ada):
        fact = ada.add_fact(ADA, "bolster", "Has birthday", "date:1988-05-17")
        assert (fact["subject"], fact["subject_kind"]) == ("Ada Example", "person")

    def test_aliases_are_canonicalised_in_the_object_too(self, ada):
        fact = ada.add_fact(ADA, "Bo Sample", "Knows", "A. Example")
        assert fact["object"] == "Ada Example"

    def test_a_name_with_no_alias_is_left_alone(self, ada):
        fact = ada.add_fact(ADA, "Bo Sample", "Knows", "Cy Sample")
        assert (fact["subject"], fact["subject_kind"]) == ("Bo Sample", None)

    def test_values_are_never_alias_resolved(self, ada):
        ada.add_alias(ADA, "1988", "person:Someone Else")  # an entity that happens to be spelled like a date
        fact = ada.add_fact(ADA, "me", "Born in", "date:1988")
        assert (fact["object"], fact["object_kind"]) == ("1988", "date")

    def test_alias_facts_themselves_keep_their_alias_as_subject(self, ada):
        fact = ada.add_alias(ADA, "Ms E", "bolster")  # target resolves, so this points at the canonical name
        assert (fact["subject"], fact["object"], fact["object_kind"]) == ("Ms E", "Ada Example", "person")

    def test_adding_the_same_alias_twice_returns_the_existing_fact(self, ada):
        first = ada.add_alias(ADA, "ae", "person:Ada Example")
        again = ada.add_alias(ADA, "AE", "Ada Example")
        assert again["id"] == first["id"]
        assert again["already_exists"] is True


class TestQueryTimeExpansion:
    def test_every_name_of_an_entity_finds_its_facts(self, ada):
        ada.add_fact(ADA, "Ada Example", "Has birthday", "date:1988-05-17")
        for name in ("Ada Example", "bolster", "A. Example", "person:Ada Example", "me", "self", "ME"):
            found = ada.search_facts(ADA, subject=name)["facts"]
            assert [f["object"] for f in found] == ["1988-05-17"], name

    def test_facts_written_before_the_alias_existed_are_found_through_it(self, store):
        store.add_fact(ADA, "Ada E", "Likes", "Tea")  # written under the old name
        store.add_fact(ADA, "Ada Example", "Likes", "Coffee")
        store.add_alias(ADA, "Ada E", "person:Ada Example")
        assert sorted(f["object"] for f in store.search_facts(ADA, subject="Ada Example")["facts"]) == ["Coffee", "Tea"]

    def test_object_filters_resolve_aliases_too(self, ada):
        ada.add_fact(ADA, "Bo Sample", "Knows", "me")
        assert ada.search_facts(ADA, object="bolster")["count"] == 1

    def test_chains_resolve_to_the_final_entity(self, store):
        store.add_alias(ADA, "a", "b")
        store.add_alias(ADA, "b", "c")
        store.add_fact(ADA, "c", "Is", "End")
        assert store.search_facts(ADA, subject="a")["count"] == 1
        assert store.describe_entity(ADA, "a")["name"] == "c"

    def test_chains_are_depth_capped(self, store):
        for n in range(15):
            store.add_alias(ADA, f"n{n}", f"n{n + 1}")
        assert store.describe_entity(ADA, "n0")["name"] == "n10"  # ten hops, then it stops

    def test_negative_alias_facts_do_not_count(self, store):
        store.add_fact(ADA, "bolster", "Alias of", "person:Ada Example", confidence=-1)
        store.add_fact(ADA, "bolster", "Likes", "Tea")
        assert store.describe_entity(ADA, "bolster")["name"] == "bolster"

    def test_expired_aliases_do_not_count(self, store):
        store.add_fact(ADA, "old name", "Alias of", "person:Ada Example", valid_to="2001")
        assert store.describe_entity(ADA, "old name")["name"] == "old name"


class TestCycles:
    def test_an_alias_of_itself_is_refused(self, store):
        with pytest.raises(ValidationError, match="itself"):
            store.add_alias(ADA, "x", "X")

    def test_a_cycle_is_refused(self, store):
        store.add_alias(ADA, "a", "b")
        store.add_alias(ADA, "b", "c")
        with pytest.raises(ValidationError, match="cycle"):
            store.add_alias(ADA, "c", "a")

    def test_aliases_are_between_entities_not_values(self, store):
        with pytest.raises(ValidationError, match="not values"):
            store.add_alias(ADA, "date:1988", "person:Ada Example")


class TestAmbiguity:
    @pytest.fixture
    def two_szilvias(self, store):
        store.add_alias(ADA, "Sam", "person:Sam Sample")
        store.add_alias(ADA, "Sam", "person:Sam Placeholder")
        return store

    def test_a_name_with_two_entities_is_an_error_that_lists_them(self, two_szilvias):
        with pytest.raises(AmbiguousEntityError) as caught:
            two_szilvias.search_facts(ADA, subject="Sam")
        assert sorted(caught.value.candidates) == ["person:Sam Placeholder", "person:Sam Sample"]
        assert "Sam" in str(caught.value)

    def test_writing_an_ambiguous_name_is_refused_too(self, two_szilvias):
        with pytest.raises(AmbiguousEntityError):
            two_szilvias.add_fact(ADA, "Sam", "Likes", "Tea")

    def test_using_a_canonical_name_still_works(self, two_szilvias):
        assert two_szilvias.search_facts(ADA, subject="person:Sam Sample")["count"] == 0
        two_szilvias.add_fact(ADA, "person:Sam Sample", "Likes", "Tea")
        assert two_szilvias.search_facts(ADA, subject="person:Sam Sample")["count"] == 1

    def test_two_routes_to_the_same_entity_are_not_ambiguous(self, store):
        store.add_alias(ADA, "p", "person:Pat Sample")
        store.add_alias(ADA, "q", "p")
        store.add_alias(ADA, "q", "person:Pat Sample")
        assert store.describe_entity(ADA, "q")["name"] == "Pat Sample"


class TestSelf:
    def test_me_needs_a_binding(self, store):
        with pytest.raises(NoSelfBindingError, match="set_self"):
            store.add_fact(ADA, "me", "Likes", "Tea")
        with pytest.raises(NoSelfBindingError):
            store.search_facts(ADA, subject="self")

    def test_set_self_binds_me_and_self(self, store):
        binding = store.set_self(ADA, "person:Ada Example")
        assert (binding["subject"], binding["subject_kind"]) == ("ada", "actor")
        assert (binding["object"], binding["object_kind"]) == ("Ada Example", "person")
        fact = store.add_fact(ADA, "me", "Likes", "Tea")
        assert fact["subject"] == "Ada Example"

    def test_rebinding_replaces_the_old_binding(self, store):
        first = store.set_self(ADA, "person:Ada Example")
        second = store.set_self(ADA, "person:Ada Lovelace-Example")
        assert second["id"] == first["id"]
        assert store.add_fact(ADA, "me", "Likes", "Tea")["subject"] == "Ada Lovelace-Example"

    def test_set_self_follows_aliases(self, store):
        store.add_alias(ADA, "ae", "person:Ada Example")
        assert store.set_self(ADA, "ae")["object"] == "Ada Example"

    @pytest.mark.parametrize("name", ["me", "self", "date:1988", "actor:ada", "text:hello"])
    def test_set_self_needs_a_named_entity(self, store, name):
        with pytest.raises(ValidationError, match="named entity"):
            store.set_self(ADA, name)

    def test_me_cannot_be_an_alias(self, store):
        with pytest.raises(ValidationError, match="always means you"):
            store.add_alias(ADA, "me", "person:Ada Example")

    def test_each_actor_has_their_own_me(self, store):
        store.set_self("ada", "person:Ada Example")
        store.set_self("bob", "person:Bob Sample")
        assert store.add_fact("ada", "me", "Likes", "Tea")["subject"] == "Ada Example"
        assert store.add_fact("bob", "me", "Likes", "Tea")["subject"] == "Bob Sample"

    def test_actor_names_can_only_refer_to_yourself(self, store):
        with pytest.raises(ValidationError, match="only refer to yourself"):
            store.add_alias("bob", "actor:ada", "person:Bob Sample")

    def test_a_public_alias_cannot_hijack_someone_elses_me(self, store):
        store.set_self("ada", "person:Ada Example")
        store.add_fact("bob", "bob-alias", "Alias of", "person:Ada Example", public=True)
        assert store.add_fact("ada", "me", "Likes", "Tea")["subject"] == "Ada Example"

    def test_the_binding_is_visible_as_an_alias_of_the_entity(self, store):
        store.set_self(ADA, "person:Ada Example")
        assert "actor:ada" in store.describe_entity(ADA, "Ada Example")["aliases"]


class TestAliasPrivacy:
    def test_my_private_alias_does_not_resolve_for_anyone_else(self, ada):
        ada.add_fact(ADA, "bolster", "Likes", "Tea")
        assert ada.describe_entity("bob", "bolster")["name"] == "bolster"
        assert ada.search_facts("bob", scope="all", subject="bolster")["count"] == 0

    def test_a_public_alias_resolves_for_everyone_in_scopes_that_can_see_it(self, store):
        store.add_alias(ADA, "The Countess", "person:Ada Example", public=True)
        assert store.describe_entity("bob", "The Countess", scope="all")["name"] == "Ada Example"
        assert store.describe_entity("bob", "The Countess", scope="public")["name"] == "Ada Example"
        assert store.describe_entity("bob", "The Countess", scope="mine")["name"] == "The Countess"


class TestDescribeEntity:
    def test_lists_aliases_types_counts_and_last_review(self, ada):
        ada.add_fact(ADA, "me", "Is a", "person:Person")
        ada.add_fact(ADA, "Person", "Is a", "Agent")
        fact = ada.add_fact(ADA, "me", "Has birthday", "date:1988-05-17")
        ada.add_fact(ADA, "Bo Sample", "Knows", "bolster")
        ada.mark_reviewed(ADA, fact["id"], "confirmed")
        described = ada.describe_entity(ADA, "bolster")
        assert (described["name"], described["kind"]) == ("Ada Example", "person")
        assert set(described["aliases"]) == {"actor:ada", "bolster", "A. Example"}
        assert described["types"] == ["Person"]
        assert described["inherited_types"] == ["Agent"]
        assert (described["facts_as_subject"], described["facts_as_object"]) == (2, 1)
        assert described["last_reviewed"] is not None

    def test_a_stranger_has_no_types_and_no_counts(self, store):
        described = store.describe_entity(ADA, "Nobody")
        assert (described["types"], described["facts_as_subject"], described["last_reviewed"]) == ([], 0, None)
