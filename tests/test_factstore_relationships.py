"""relationships_between: direct facts in either direction, one-intermediary paths, aliases and edge cases."""

import pytest

from factstore import AmbiguousEntityError, ValidationError

ADA = "ada"


@pytest.fixture
def world(store):
    store.set_self(ADA, "person:Ada Example")
    store.add_alias(ADA, "bolster", "person:Ada Example")
    store.add_alias(ADA, "Bo", "person:Bo Sample")
    store.add_fact(ADA, "me", "Partner", "person:Bo Sample", valid_from="2012", valid_to="2015")
    store.add_fact(ADA, "person:Bo Sample", "Admires", "person:Ada Example")
    store.add_fact(ADA, "me", "Knows", "person:Cy Sample")
    store.add_fact(ADA, "person:Cy Sample", "Knows", "person:Bo Sample")
    store.add_fact(ADA, "me", "Lives in", "place:Belfast")
    store.add_fact(ADA, "place:Belfast", "Located in", "place:Ireland")
    store.add_fact(ADA, "person:Bo Sample", "Born in", "place:Ireland")
    return store


def actions(facts):
    return sorted(f["action"] for f in facts)


class TestDirect:
    def test_finds_facts_in_both_directions_with_their_direction(self, world):
        found = world.relationships_between(ADA, "me", "person:Bo Sample")
        assert {(f["action"], f["direction"]) for f in found["direct"]} == {
            ("Partner", "a_to_b"),
            ("Admires", "b_to_a"),
        }
        assert (found["a"], found["b"]) == ("person:Ada Example", "person:Bo Sample")
        assert found["indirect"] == []

    def test_argument_order_flips_the_directions(self, world):
        found = world.relationships_between(ADA, "Bo Sample", "me")
        assert {(f["action"], f["direction"]) for f in found["direct"]} == {
            ("Partner", "b_to_a"),
            ("Admires", "a_to_b"),
        }

    def test_aliases_work_on_both_sides(self, world):
        found = world.relationships_between(ADA, "bolster", "Bo")
        assert actions(found["direct"]) == ["Admires", "Partner"]

    def test_unrelated_entities_have_nothing_between_them(self, world):
        found = world.relationships_between(ADA, "me", "Nobody Sample")
        assert (found["direct"], found["indirect"]) == ([], [])

    def test_negative_facts_do_not_count(self, world):
        world.add_fact(ADA, "me", "Sibling of", "person:Bo Sample", confidence=-1)
        assert "Sibling of" not in actions(world.relationships_between(ADA, "me", "Bo")["direct"])

    def test_alias_facts_are_structure_not_relationships(self, world):
        assert "Alias of" not in actions(world.relationships_between(ADA, "me", "Bo")["direct"])

    def test_the_same_entity_twice_is_an_error(self, world):
        with pytest.raises(ValidationError, match="same entity"):
            world.relationships_between(ADA, "me", "bolster")

    @pytest.mark.parametrize("depth", [0, 3, True, "1"])
    def test_depth_is_validated(self, world, depth):
        with pytest.raises(ValidationError, match="max_depth"):
            world.relationships_between(ADA, "me", "Bo", max_depth=depth)

    def test_an_ambiguous_name_is_an_error(self, world):
        world.add_alias(ADA, "Sam", "person:Sam One")
        world.add_alias(ADA, "Sam", "person:Sam Two")
        with pytest.raises(AmbiguousEntityError):
            world.relationships_between(ADA, "me", "Sam")


class TestOneIntermediary:
    def test_depth_two_adds_paths_through_one_entity(self, world):
        found = world.relationships_between(ADA, "me", "Bo", max_depth=2)
        # Cy Sample is one intermediary; me - Belfast - Ireland - Bo has two, so it is not a depth-2 path
        assert [path["via"] for path in found["indirect"]] == ["cy sample"]
        assert actions(found["direct"]) == ["Admires", "Partner"]

    def test_each_path_carries_its_two_facts(self, world):
        found = world.relationships_between(ADA, "me", "Bo", max_depth=2)
        cy = next(path for path in found["indirect"] if path["via"] == "cy sample")
        assert sorted(f["action"] for f in cy["facts"]) == ["Knows", "Knows"]
        assert len(cy["facts"]) == 2

    def test_hops_can_run_in_either_direction(self, world):
        # me -> Cy (Knows) and Cy -> Bo (Knows): second hop goes the "wrong" way when the arguments swap
        found = world.relationships_between(ADA, "Bo", "me", max_depth=2)
        assert "cy sample" in {path["via"] for path in found["indirect"]}

    def test_depth_one_never_returns_indirect_paths(self, world):
        assert world.relationships_between(ADA, "me", "Bo", max_depth=1)["indirect"] == []

    def test_other_names_of_the_endpoints_are_not_intermediaries(self, world):
        world.add_fact(ADA, "bolster", "Mentioned with", "person:Bo Sample")  # same entity as 'me'
        found = world.relationships_between(ADA, "me", "Bo", max_depth=2)
        assert "bolster" not in {path["via"] for path in found["indirect"]}

    def test_cycles_in_the_data_terminate(self, store):
        store.add_fact(ADA, "A", "Links", "B")
        store.add_fact(ADA, "B", "Links", "C")
        store.add_fact(ADA, "C", "Links", "A")
        store.add_fact(ADA, "C", "Links", "D")
        found = store.relationships_between(ADA, "A", "D", max_depth=2)
        assert [path["via"] for path in found["indirect"]] == ["c"]

    def test_the_number_of_paths_is_capped(self, store):
        for n in range(120):
            store.add_fact(ADA, "Start", "Links", f"Mid {n}")
            store.add_fact(ADA, f"Mid {n}", "Links", "End")
        assert len(store.relationships_between(ADA, "Start", "End", max_depth=2)["indirect"]) == 100

    def test_a_walk_only_uses_facts_the_scope_can_see(self, world):
        world.add_fact("bob", "person:Bo Sample", "Knows", "person:Ada Example", public=True)
        found = world.relationships_between("bob", "Bo Sample", "Ada Example", scope="all", max_depth=2)
        assert [(f["action"], f["created_by"]) for f in found["direct"]] == [("Knows", "bob")]
        assert found["indirect"] == []  # Ada's private paths through Cy Sample are not bob's to walk
