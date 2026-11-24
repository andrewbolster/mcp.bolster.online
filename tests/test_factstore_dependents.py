"""``dependents``: what is connected to an entity by chains of facts, nearest first, and never through a fact the
actor cannot read."""

import dataclasses

import pytest

from factstore import AmbiguousEntityError, Config, FactStore, ValidationError

ADA, BOB, CY = "ada", "bob", "cy"


@pytest.fixture
def kstore(tmp_path) -> FactStore:
    """A store whose config knows the kinds the catalogue experiments used."""
    cfg = dataclasses.replace(Config(), kinds=Config().kinds | {"source", "claim", "event"})
    return FactStore(tmp_path / "facts.sqlite3", cfg)


@pytest.fixture
def chain(kstore):
    """claim:C1 and claim:C2 derive from source:S1; source:S1 derives from source:Raw; event:E affects source:S1."""
    s = kstore
    s.add_fact(ADA, "claim:C1", "Derived from", "source:S1", confidence=0.8, attributes={"statement": "one"})
    s.add_fact(ADA, "claim:C2", "Derived from", "source:S1", confidence=0.6, valid_from="2024", valid_to="2025")
    s.add_fact(ADA, "source:S1", "Derived from", "source:Raw")
    s.add_fact(ADA, "event:E", "Affects", "source:S1")
    return s


def entities(result):
    return [row[0] for row in result["rows"]] if "rows" in result else [row["entity"] for row in result["dependents"]]


class TestWalking:
    def test_what_points_at_an_entity_is_its_dependents(self, chain):
        found = chain.dependents(ADA, "source:S1", via=["Derived from"])
        assert [(d["entity"], d["depth"], d["via"]) for d in found["dependents"]] == [
            ("claim:C1", 1, ["Derived from"]),
            ("claim:C2", 1, ["Derived from"]),
        ]
        assert (found["start"], found["direction"], found["depth"], found["via"]) == (
            "source:S1", "in", 1, ["Derived from"],
        )  # fmt: skip
        assert found["total"] == 2 and found["capped"] is False and found["truncated"] is False

    def test_without_via_any_action_is_followed(self, chain):
        found = chain.dependents(ADA, "source:S1")
        assert entities(found) == ["claim:C1", "claim:C2", "event:E"]
        assert found["via"] is None

    def test_each_dependent_names_the_fact_it_was_reached_through(self, chain):
        found = chain.dependents(ADA, "source:S1", via=["Derived from"])
        first = found["dependents"][0]
        stored = chain.get_fact(ADA, first["fact_ids"][0])
        assert (stored["subject_ref"], stored["action"], stored["object_ref"]) == (
            "claim:C1",
            "Derived from",
            "source:S1",
        )
        assert (first["confidence"], first["valid_from"], first["valid_to"]) == (0.8, None, None)
        second = found["dependents"][1]
        assert (second["confidence"], second["valid_from"], second["valid_to"]) == (0.6, "2024", "2025")

    def test_out_follows_facts_that_start_at_the_entity(self, chain):
        found = chain.dependents(ADA, "claim:C1", direction="out", depth=2)
        assert [(d["entity"], d["depth"]) for d in found["dependents"]] == [("source:S1", 1), ("source:Raw", 2)]
        assert [d["via"] for d in found["dependents"]] == [["Derived from"], ["Derived from", "Derived from"]]

    def test_in_walks_further_with_depth(self, chain):
        shallow = chain.dependents(ADA, "source:Raw", via=["Derived from"], depth=1)
        deep = chain.dependents(ADA, "source:Raw", via=["Derived from"], depth=2)
        assert entities(shallow) == ["source:S1"]
        assert [(d["entity"], d["depth"]) for d in deep["dependents"]] == [
            ("source:S1", 1), ("claim:C1", 2), ("claim:C2", 2),
        ]  # fmt: skip

    def test_both_directions_pass_through_a_shared_entity(self, chain):
        found = chain.dependents(
            ADA, "event:E", via=["Affects", "Derived from"], depth=2, direction="both", result_kind="claim"
        )
        assert [(d["entity"], d["depth"], d["via"]) for d in found["dependents"]] == [
            ("claim:C1", 2, ["Affects", "Derived from"]),
            ("claim:C2", 2, ["Affects", "Derived from"]),
        ]
        assert found["total"] == 2  # result_kind narrows the reply, not the walk

    def test_an_entity_is_reported_once_by_its_shortest_path(self, kstore):
        s = kstore
        s.add_fact(ADA, "claim:Long", "Derived from", "source:Mid")
        s.add_fact(ADA, "source:Mid", "Derived from", "source:Top")
        s.add_fact(ADA, "claim:Long", "Derived from", "source:Top")  # a second, shorter route
        found = s.dependents(ADA, "source:Top", depth=3)
        long = [d for d in found["dependents"] if d["entity"] == "claim:Long"]
        assert len(long) == 1 and long[0]["depth"] == 1

    def test_cycles_do_not_loop_and_the_start_is_never_returned(self, kstore):
        s = kstore
        s.add_fact(ADA, "source:A", "Uses data from", "source:B")
        s.add_fact(ADA, "source:B", "Uses data from", "source:C")
        s.add_fact(ADA, "source:C", "Uses data from", "source:A")
        s.add_fact(ADA, "source:A", "Uses data from", "source:A")  # even a self-loop
        found = s.dependents(ADA, "source:A", depth=3, direction="both")
        assert sorted(entities(found)) == ["source:B", "source:C"]

    def test_the_via_filter_ignores_case_spacing_and_punctuation(self, chain):
        assert entities(chain.dependents(ADA, "source:S1", via=[" derived  FROM "])) == ["claim:C1", "claim:C2"]
        assert entities(chain.dependents(ADA, "source:S1", via="Affects")) == ["event:E"]
        assert entities(chain.dependents(ADA, "source:S1", via=["Affects", "Derived from"])) == [
            "claim:C1", "claim:C2", "event:E",
        ]  # fmt: skip


class TestWhatIsNotAnEntity:
    def test_values_are_never_returned_or_passed_through(self, kstore):
        s = kstore
        s.add_fact(ADA, "source:S1", "Published on", "date:2026-11-23")
        s.add_fact(ADA, "article:Other", "Published on", "date:2026-11-23")
        s.add_fact(ADA, "source:S1", "Has cadence", "text:monthly")
        assert s.dependents(ADA, "source:S1", direction="out", depth=2)["total"] == 0
        with pytest.raises(ValidationError, match="is a value, not an entity"):
            s.dependents(ADA, "date:2026-11-23", direction="both")

    def test_alias_facts_are_structure_and_are_not_followed(self, kstore):
        s = kstore
        s.add_alias(ADA, "S One", "source:S1")
        s.add_fact(ADA, "claim:C1", "Derived from", "S One")
        assert entities(s.dependents(ADA, "source:S1", direction="both")) == ["claim:C1"]

    def test_negative_facts_are_followed_only_when_asked(self, kstore):
        s = kstore
        s.add_fact(ADA, "claim:Refuted", "Derived from", "source:S1", confidence=-0.8)
        assert s.dependents(ADA, "source:S1")["total"] == 0
        found = s.dependents(ADA, "source:S1", include_negative=True)
        assert entities(found) == ["claim:Refuted"] and found["dependents"][0]["confidence"] == -0.8


class TestNames:
    def test_the_start_can_be_an_alias_and_facts_written_under_it_count(self, kstore):
        s = kstore
        s.add_fact(ADA, "claim:Early", "Derived from", "LFS")  # written before the alias exists
        s.add_alias(ADA, "LFS", "source:Labour Market")
        s.add_fact(ADA, "claim:Late", "Derived from", "LFS")
        assert entities(s.dependents(ADA, "LFS")) == ["claim:Early", "claim:Late"]
        assert entities(s.dependents(ADA, "source:Labour Market")) == ["claim:Early", "claim:Late"]

    def test_me_means_the_caller(self, kstore):
        s = kstore
        s.set_self(ADA, "person:Ada Example")
        s.add_fact(ADA, "person:Bo Sample", "Knows", "me")
        assert entities(s.dependents(ADA, "me")) == ["person:Bo Sample"]

    def test_an_ambiguous_name_is_an_error_that_lists_the_candidates(self, kstore):
        s = kstore
        s.add_alias(ADA, "PPS", "org:Public Prosecution Service")
        s.add_alias(ADA, "PPS", "source:PPS Bulletin")
        with pytest.raises(AmbiguousEntityError, match="Public Prosecution Service") as caught:
            s.dependents(ADA, "PPS")
        assert "PPS Bulletin" in str(caught.value)
        assert s.dependents(ADA, "org:PPS")["start"] == "org:Public Prosecution Service"


class TestShapeAndLimits:
    def test_compact_is_columns_and_rows(self, chain):
        found = chain.dependents(ADA, "source:S1", via=["Derived from"], format="compact")
        assert found["columns"] == ["entity", "depth", "via", "fact_ids"]
        assert [row[:3] for row in found["rows"]] == [
            ["claim:C1", 1, ["Derived from"]],
            ["claim:C2", 1, ["Derived from"]],
        ]
        assert "dependents" not in found and found["count"] == 2

    def test_fields_choose_the_columns_and_can_reach_the_last_facts_attributes(self, chain):
        found = chain.dependents(ADA, "source:S1", via=["Derived from"], fields=["entity", "confidence", "attributes"])
        assert found["dependents"][0] == {"entity": "claim:C1", "confidence": 0.8, "attributes": {"statement": "one"}}
        assert "attributes" not in chain.dependents(ADA, "source:S1")["dependents"][0]  # not unless named

    def test_an_unknown_field_lists_the_valid_ones(self, chain):
        with pytest.raises(ValidationError, match="Unknown field 'nope'.*entity, name, kind, depth, via, fact_ids"):
            chain.dependents(ADA, "source:S1", fields=["nope"])

    def test_paging_reports_the_total_and_whether_more_follow(self, chain):
        first = chain.dependents(ADA, "source:S1", limit=2)
        second = chain.dependents(ADA, "source:S1", limit=2, offset=2)
        assert (first["count"], first["total"], first["truncated"]) == (2, 3, True)
        assert (second["count"], second["truncated"]) == (1, False)
        assert entities(first) + entities(second) == ["claim:C1", "claim:C2", "event:E"]

    def test_the_walk_stops_at_the_cap_and_says_so(self, tmp_path):
        s = FactStore(tmp_path / "capped.sqlite3", dataclasses.replace(Config(), max_dependents=3))
        for i in range(10):
            s.add_fact(ADA, f"person:P{i}", "Knows", "person:Hub")
        found = s.dependents(ADA, "person:Hub")
        assert found["capped"] is True and found["total"] == 3
        assert s.dependents(ADA, "person:P0", direction="out")["capped"] is False

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"depth": 0}, "depth must be 1 to 3"),
            ({"depth": 4}, "depth must be 1 to 3"),
            ({"depth": True}, "depth must be 1 to 3"),
            ({"direction": "up"}, "direction must be one of in, out, both"),
            ({"via": []}, "via must be a non-empty list"),
            ({"result_kind": "nonsense"}, "not a configured kind"),
            ({"format": "xml"}, "format must be one of full, compact"),
        ],
    )
    def test_bad_arguments_say_what_is_valid(self, chain, kwargs, message):
        with pytest.raises(ValidationError, match=message):
            chain.dependents(ADA, "source:S1", **kwargs)

    def test_an_unknown_start_is_simply_an_entity_with_no_dependents(self, chain):
        found = chain.dependents(ADA, "source:Nothing Here")
        assert found["total"] == 0 and found["dependents"] == []


# ------------------------------------------------------------------------------------------------ visibility


class TestNeverThroughAnUnreadableFact:
    """Ada's chain is S1 <- M <- C. Bob may read only what Ada made public, or was asked to review."""

    @pytest.fixture
    def private_chain(self, kstore):
        s = kstore
        first = s.add_fact(ADA, "claim:Mid", "Derived from", "source:S1")
        second = s.add_fact(ADA, "claim:Top", "Derived from", "claim:Mid")
        return s, first, second

    def test_nothing_of_a_private_chain_is_visible_to_another_actor(self, private_chain):
        s, *_ = private_chain
        for scope in ("mine", "public", "all"):
            for direction in ("in", "out", "both"):
                found = s.dependents(BOB, "source:S1", depth=3, direction=direction, scope=scope)
                assert (found["total"], found["dependents"]) == (0, [])
        assert s.dependents(ADA, "source:S1", depth=3)["total"] == 2

    def test_a_walk_stops_where_the_next_fact_is_private(self, private_chain):
        s, first, second = private_chain
        s.update_fact(ADA, first["id"], public=True)  # the first hop is public, the second is not
        found = s.dependents(BOB, "source:S1", depth=3, scope="public")
        assert entities(found) == ["claim:Mid"]
        assert second["id"] not in str(found)

    def test_a_walk_starting_after_the_private_hop_sees_nothing_of_it(self, private_chain):
        s, first, second = private_chain
        s.update_fact(ADA, second["id"], public=True)  # only the outer hop is public
        assert s.dependents(BOB, "source:S1", depth=3, scope="public")["total"] == 0
        assert entities(s.dependents(BOB, "claim:Mid", scope="public")) == ["claim:Top"]

    def test_a_review_request_grants_exactly_one_hop_while_it_is_open(self, private_chain):
        s, first, second = private_chain
        s.request_review(ADA, first["id"], BOB)
        found = s.dependents(BOB, "source:S1", depth=3, scope="all")
        assert entities(found) == ["claim:Mid"] and found["dependents"][0]["fact_ids"] == [first["id"]]
        assert s.dependents(CY, "source:S1", depth=3, scope="all")["total"] == 0
        s.mark_reviewed(BOB, first["id"], "unsure")
        assert s.dependents(BOB, "source:S1", depth=3, scope="all")["total"] == 0

    def test_counts_and_flags_reflect_only_what_the_actor_can_read(self, private_chain):
        s, first, second = private_chain
        s.update_fact(ADA, first["id"], public=True)
        found = s.dependents(BOB, "source:S1", depth=3, scope="all", format="compact")
        assert (found["total"], found["count"], found["capped"]) == (1, 1, False)

    def test_another_actors_private_alias_does_not_resolve_the_start(self, kstore):
        s = kstore
        s.add_alias(ADA, "Nick", "source:S1")
        s.add_fact(ADA, "claim:C1", "Derived from", "source:S1")
        assert s.dependents(BOB, "Nick")["total"] == 0  # for Bob, 'Nick' is an unknown name
