"""Leak tests: no read path, in any scope, exposes another actor's private data.

Ada owns a rich private dataset. Bob (and a stranger, Cy) then try every way the engine offers of reading,
searching, resolving and counting. A leak is Ada's fact ids or the distinctive values only her facts contain; a name
the caller typed being echoed back is not a leak. The one exception is the single fact Ada has asked Bob to review,
for as long as that request is open.
"""

import io
import json

import pytest

from factstore import FactsError, NotFoundError

ADA, BOB, CY = "ada", "bob", "cy"
#: Values that appear only inside Ada's private facts (never in an attacker's input).
VALUES = ("quuxcorp", '"object": "wibbleton"', "1970-01-01", "example.org/sekret", '"note": "sekret"')


@pytest.fixture
def populated(store):
    """Ada's private dataset, by name."""
    store.set_self(ADA, "person:Zorblax Prime")
    store.add_alias(ADA, "Sekret Nickname", "person:Zorblax Prime")
    facts = {
        "type": store.add_fact(ADA, "person:Zorblax Prime", "Is a", "Person"),
        "birthday": store.add_fact(ADA, "me", "Has birthday", "date:1970-01-01", attributes={"note": "sekret"}),
        "work": store.add_fact(ADA, "Sekret Nickname", "Works at", "org:Quuxcorp", valid_from="2020"),
        "home": store.add_fact(ADA, "me", "Lives in", "place:Wibbleton", references=["https://example.org/sekret"]),
        "partner": store.add_fact(ADA, "me", "Partner", "person:Quxx Sample"),
        "negative": store.add_fact(ADA, "me", "Dislikes", "Tea", confidence=-1),
    }
    facts["knows"] = store.add_fact(ADA, "person:Quxx Sample", "Knows", "person:Wibbleton Mayor")
    facts["mayor"] = store.add_fact(ADA, "person:Wibbleton Mayor", "Knows", "person:Zorblax Prime")
    return facts


def attempts(store, actor):
    """Everything an actor can try that reads facts: (label, callable)."""
    calls = []
    for scope in ("mine", "public", "all"):
        for neg in (False, True):
            calls += [
                (
                    f"all {scope} neg={neg}",
                    lambda s=scope, n=neg: store.search_facts(actor, scope=s, include_negative=n),
                ),
                (
                    f"free text {scope} neg={neg}",
                    lambda s=scope, n=neg: store.search_facts(actor, scope=s, q="zorblax", include_negative=n),
                ),
            ]
        calls += [
            (
                f"subject {scope}",
                lambda s=scope: store.search_facts(actor, scope=s, subject="Zorblax Prime", include_negative=True),
            ),
            (
                f"alias subject {scope}",
                lambda s=scope: store.search_facts(actor, scope=s, subject="Sekret Nickname", include_negative=True),
            ),
            (f"me {scope}", lambda s=scope: store.search_facts(actor, scope=s, subject="me")),
            (f"object {scope}", lambda s=scope: store.search_facts(actor, scope=s, object="person:Zorblax Prime")),
            (f"action {scope}", lambda s=scope: store.search_facts(actor, scope=s, action="Works at")),
            (f"kind {scope}", lambda s=scope: store.search_facts(actor, scope=s, object_kind="org")),
            (f"type {scope}", lambda s=scope: store.search_facts(actor, scope=s, subject_type="Person")),
            (f"attribute {scope}", lambda s=scope: store.search_facts(actor, scope=s, attribute_key="note")),
            (f"valid_at {scope}", lambda s=scope: store.search_facts(actor, scope=s, valid_at="2021-01-01")),
            (
                f"reviewed_before {scope}",
                lambda s=scope: store.search_facts(actor, scope=s, reviewed_before="2100-01-01"),
            ),
            (f"describe {scope}", lambda s=scope: store.describe_entity(actor, "Zorblax Prime", scope=s)),
            (f"describe alias {scope}", lambda s=scope: store.describe_entity(actor, "Sekret Nickname", scope=s)),
            (
                f"between {scope}",
                lambda s=scope: store.relationships_between(
                    actor, "Zorblax Prime", "Quxx Sample", scope=s, max_depth=2
                ),
            ),
            (
                f"between reversed {scope}",
                lambda s=scope: store.relationships_between(
                    actor, "Quxx Sample", "Zorblax Prime", scope=s, max_depth=2
                ),
            ),
            (
                f"between mayor {scope}",
                lambda s=scope: store.relationships_between(
                    actor, "Zorblax Prime", "Wibbleton Mayor", scope=s, max_depth=2
                ),
            ),
        ]
    calls += [
        ("pending received", lambda: store.pending_reviews(actor)),
        ("pending sent", lambda: store.pending_reviews(actor, "sent")),
        ("due", lambda: store.due_for_review(actor, before="2100-01-01")),
    ]
    return calls


def outputs(store, actor):
    """(label, lower-cased JSON text) of every attempt; an error message counts as output too."""
    results = []
    for label, call in attempts(store, actor):
        try:
            results.append((label, json.dumps(call(), default=str).lower()))
        except FactsError as error:
            results.append((label, str(error).lower()))
    return results


def leaks(text, *, allowed_values=(), allowed_ids=(), populated):
    found = [v for v in VALUES if v not in allowed_values and v in text]
    found += [name for name, fact in populated.items() if fact["id"] not in allowed_ids and fact["id"] in text]
    return found


@pytest.mark.parametrize("actor", [BOB, CY])
def test_no_read_path_exposes_a_private_fact(store, populated, actor):
    for label, text in outputs(store, actor):
        assert not leaks(text, populated=populated), f"{actor} saw private data via {label}: {text[:300]}"


def test_get_update_delete_review_of_a_private_fact_look_like_a_missing_id(store, populated):
    absent = "00000000-0000-7000-8000-000000000000"
    with pytest.raises(NotFoundError) as caught:
        store.get_fact(BOB, absent)
    expected = str(caught.value).replace(absent, "ID")
    secret = populated["birthday"]["id"]
    for call in (
        lambda: store.get_fact(BOB, secret),
        lambda: store.update_fact(BOB, secret, confidence=0.5),
        lambda: store.delete_fact(BOB, secret),
        lambda: store.mark_reviewed(BOB, secret, "confirmed"),
        lambda: store.request_review(BOB, secret, CY),
    ):
        with pytest.raises(NotFoundError) as denied:
            call()
        assert str(denied.value).replace(secret, "ID") == expected


def test_the_same_names_are_separate_private_names_to_someone_else(store, populated):
    fact = store.add_fact(BOB, "Zorblax Prime", "Likes", "Tea", check_types=True)
    assert fact["subject_kind"] is None  # Ada's alias and kind did not resolve for Bob
    assert fact["untyped"] == ["Zorblax Prime", "Tea"]  # Ada's private 'Is a' did not suppress the hint
    assert store.search_facts(BOB, subject="Zorblax Prime")["count"] == 1
    assert store.search_facts(ADA, subject="Zorblax Prime", action="Likes")["count"] == 0  # and Bob's fact is not Ada's


def test_the_export_of_one_actor_contains_only_their_facts(store, populated):
    store.add_fact(BOB, "Bob Sample", "Likes", "Tea")
    out = io.StringIO()
    store.export_jsonl(out, BOB)
    text = out.getvalue().lower()
    assert "bob sample" in text
    assert not leaks(text, populated=populated)


def test_public_facts_are_readable_by_others_and_nothing_else_comes_with_them(store, populated):
    shared = store.add_fact(ADA, "Zorblax Prime", "Likes", "Biscuits", public=True)
    assert [f["id"] for f in store.search_facts(BOB, scope="public")["facts"]] == [shared["id"]]
    assert store.get_fact(BOB, shared["id"])["created_by"] == ADA
    assert store.search_facts(BOB, scope="mine")["count"] == 0
    described = store.describe_entity(BOB, "Zorblax Prime", scope="all")
    assert (described["aliases"], described["facts_as_subject"]) == ([], 1)  # not Ada's private aliases or counts
    for label, text in outputs(store, BOB):
        assert not leaks(text, populated=populated), label


class TestTheSingleGrantedFact:
    @pytest.fixture
    def granted(self, store, populated):
        store.request_review(ADA, populated["work"]["id"], BOB)
        return populated["work"]["id"]

    def test_only_that_fact_is_readable_while_the_request_is_open(self, store, populated, granted):
        assert [f["id"] for f in store.search_facts(BOB, scope="all")["facts"]] == [granted]
        assert store.get_fact(BOB, granted)["id"] == granted
        for label, text in outputs(store, BOB):
            assert not leaks(text, allowed_values=("quuxcorp",), allowed_ids=(granted,), populated=populated), label
        described = store.describe_entity(BOB, "Zorblax Prime", scope="all")
        assert described["facts_as_subject"] == 1  # the granted fact, not Ada's others
        assert described["aliases"] == []  # Ada's private alias facts were not granted

    def test_the_grant_is_one_fact_not_the_entity_and_not_ownership(self, store, populated, granted):
        for name in ("birthday", "home", "partner", "type", "negative", "knows"):
            with pytest.raises(NotFoundError):
                store.get_fact(BOB, populated[name]["id"])
        assert store.search_facts(BOB, scope="mine")["count"] == 0

    def test_it_is_gone_after_the_review(self, store, populated, granted):
        store.mark_reviewed(BOB, granted, "unsure")
        for label, text in outputs(store, BOB):
            assert not leaks(text, populated=populated), label

    def test_a_third_actor_never_gets_it(self, store, populated, granted):
        for label, text in outputs(store, CY):
            assert not leaks(text, populated=populated), label

    def test_a_dispute_leaves_bob_with_only_his_own_private_copy(self, store, populated, granted):
        store.mark_reviewed(BOB, granted, "disputed")
        mine = store.search_facts(BOB, scope="all", include_negative=True)["facts"]
        assert [f["created_by"] for f in mine] == [BOB]
        assert store.search_facts(CY, scope="all", include_negative=True)["count"] == 0
        assert store.search_facts(ADA, subject="Zorblax Prime", action="Works at")["count"] == 1  # Ada's is untouched


def test_ada_always_sees_her_own_data(store, populated):
    assert store.search_facts(ADA, scope="all", q="zorblax", include_negative=True)["count"] >= 4
    assert store.search_facts(ADA, scope="mine", subject="me")["count"] >= 3
    assert store.describe_entity(ADA, "Sekret Nickname", scope="mine")["name"] == "Zorblax Prime"
