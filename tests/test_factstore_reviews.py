"""Reviews: requests, the one-fact grant, outcomes, due lists and pending lists."""

from datetime import UTC, datetime, timedelta

import pytest

from factstore import NotFoundError, ValidationError
from factstore.schema import session

ADA, BOB = "ada", "bob"


@pytest.fixture
def fact(store):
    return store.add_fact(ADA, "Ada Example", "Has birthday", "date:1988-05-17")


class TestRequestReview:
    def test_only_the_owner_can_ask_and_not_themselves(self, store, fact):
        with pytest.raises(NotFoundError):
            store.request_review(BOB, fact["id"], "cy")  # bob cannot even see it
        with pytest.raises(ValidationError, match="yourself"):
            store.request_review(ADA, fact["id"], "ADA")

    def test_a_request_is_open_and_names_both_actors(self, store, fact):
        request = store.request_review(ADA, fact["id"], "Bob", note="still right?")
        assert (request["requested_by"], request["requested_of"], request["status"]) == (ADA, BOB, "open")
        assert request["note"] == "still right?"
        assert request["already_open"] is False

    def test_asking_twice_returns_the_open_request(self, store, fact):
        first = store.request_review(ADA, fact["id"], BOB)
        again = store.request_review(ADA, fact["id"], BOB)
        assert again["id"] == first["id"]
        assert again["already_open"] is True

    def test_a_note_is_length_limited(self, store, fact):
        with pytest.raises(ValidationError, match="note"):
            store.request_review(ADA, fact["id"], BOB, note="x" * 501)


class TestGrant:
    def test_the_requested_actor_can_read_exactly_that_fact(self, store, fact):
        other = store.add_fact(ADA, "Ada Example", "Likes", "Tea")
        assert store.search_facts(BOB, scope="all")["count"] == 0
        store.request_review(ADA, fact["id"], BOB)
        assert [f["id"] for f in store.search_facts(BOB, scope="all")["facts"]] == [fact["id"]]
        assert store.get_fact(BOB, fact["id"])["id"] == fact["id"]
        with pytest.raises(NotFoundError):
            store.get_fact(BOB, other["id"])

    def test_it_does_not_widen_scope_mine_or_ownership(self, store, fact):
        store.request_review(ADA, fact["id"], BOB)
        assert store.search_facts(BOB, scope="mine")["count"] == 0
        from factstore import PermissionDeniedError

        with pytest.raises(PermissionDeniedError):
            store.update_fact(BOB, fact["id"], confidence=0.1)
        with pytest.raises(PermissionDeniedError):
            store.delete_fact(BOB, fact["id"])

    def test_it_ends_when_the_request_is_resolved(self, store, fact):
        store.request_review(ADA, fact["id"], BOB)
        store.mark_reviewed(BOB, fact["id"], "unsure")
        assert store.search_facts(BOB, scope="all")["count"] == 0
        with pytest.raises(NotFoundError):
            store.get_fact(BOB, fact["id"])

    def test_it_ends_when_the_fact_is_deleted(self, store, fact):
        store.request_review(ADA, fact["id"], BOB)
        store.delete_fact(ADA, fact["id"])
        assert store.pending_reviews(BOB)["count"] == 0

    def test_another_actor_gets_nothing(self, store, fact):
        store.request_review(ADA, fact["id"], BOB)
        assert store.search_facts("cy", scope="all")["count"] == 0


class TestMarkReviewed:
    def test_confirmed_stamps_the_fact_and_logs_the_review(self, store, fact):
        result = store.mark_reviewed(ADA, fact["id"], "confirmed", "checked the passport")
        assert result["fact"]["reviewed_by"] == ADA
        assert result["fact"]["reviewed_at"] is not None
        assert (result["review"]["outcome"], result["review"]["note"]) == ("confirmed", "checked the passport")
        assert result["counter_fact"] is None

    def test_a_reviewer_confirming_a_requested_fact_stamps_it_and_closes_the_request(self, store, fact):
        store.request_review(ADA, fact["id"], BOB)
        result = store.mark_reviewed(BOB, fact["id"], "confirmed")
        assert result["fact"]["reviewed_by"] == BOB
        assert store.pending_reviews(BOB)["count"] == 0
        assert store.pending_reviews(ADA, "sent")["count"] == 0

    def test_a_dispute_creates_the_reviewers_own_negative_fact_and_leaves_the_owners_alone(self, store, fact):
        store.request_review(ADA, fact["id"], BOB)
        result = store.mark_reviewed(BOB, fact["id"], "disputed", "that is a sibling's birthday")
        counter = result["counter_fact"]
        assert counter["created_by"] == BOB
        assert counter["confidence"] == -1.0
        assert counter["public"] is False
        assert (counter["subject"], counter["action"], counter["object"]) == (
            "Ada Example",
            "Has birthday",
            "1988-05-17",
        )
        assert counter["references"] == [f"fact:{fact['id']}"]
        assert counter["attributes"] == {"disputes": fact["id"]}
        untouched = store.get_fact(ADA, fact["id"])
        assert (untouched["confidence"], untouched["reviewed_at"], untouched["updated_at"]) == (1.0, None, None)
        # bob can read his own counter-fact, and only that, once the request is closed
        assert [f["id"] for f in store.search_facts(BOB, include_negative=True)["facts"]] == [counter["id"]]
        assert store.search_facts(BOB, scope="all", include_negative=True)["count"] == 1

    def test_the_owner_cannot_dispute_their_own_fact(self, store, fact):
        with pytest.raises(ValidationError, match="update_fact"):
            store.mark_reviewed(ADA, fact["id"], "disputed")
        # nothing was logged, no counter-fact appeared, and the fact is untouched
        assert store.get_fact(ADA, fact["id"])["reviews"] == []
        assert store.search_facts(ADA, include_negative=True)["count"] == 1
        # the owner can still confirm, or say they are unsure
        assert store.mark_reviewed(ADA, fact["id"], "unsure")["review"]["outcome"] == "unsure"
        assert store.mark_reviewed(ADA, fact["id"], "confirmed")["fact"]["reviewed_by"] == ADA

    def test_unsure_only_logs_and_does_not_stamp(self, store, fact):
        result = store.mark_reviewed(ADA, fact["id"], "unsure")
        assert result["fact"]["reviewed_at"] is None

    def test_anyone_can_review_a_public_fact(self, store):
        public = store.add_fact(ADA, "Ada Example", "Likes", "Tea", public=True)
        assert store.mark_reviewed(BOB, public["id"], "confirmed")["fact"]["reviewed_by"] == BOB

    def test_you_cannot_review_what_you_cannot_see(self, store, fact):
        with pytest.raises(NotFoundError):
            store.mark_reviewed(BOB, fact["id"], "confirmed")

    def test_outcome_is_validated(self, store, fact):
        with pytest.raises(ValidationError, match="outcome"):
            store.mark_reviewed(ADA, fact["id"], "approved")


class TestPendingReviews:
    def test_received_lists_open_requests_with_their_facts_oldest_first(self, store):
        first = store.add_fact(ADA, "A", "Is a", "Letter")
        second = store.add_fact(ADA, "B", "Is a", "Letter")
        store.request_review(ADA, second["id"], BOB)
        store.request_review(ADA, first["id"], BOB)
        pending = store.pending_reviews(BOB)
        assert pending["count"] == 2
        assert [r["fact"]["id"] for r in pending["requests"]] == [second["id"], first["id"]]
        assert pending["requests"][0]["status"] == "open"

    def test_sent_lists_what_the_actor_asked_for(self, store, fact):
        store.request_review(ADA, fact["id"], BOB)
        assert store.pending_reviews(ADA, "sent")["count"] == 1
        assert store.pending_reviews(ADA)["count"] == 0
        assert store.pending_reviews(BOB, "sent")["count"] == 0

    def test_direction_is_validated(self, store):
        with pytest.raises(ValidationError, match="direction"):
            store.pending_reviews(ADA, "sideways")

    def test_only_open_requests_are_listed(self, store, fact):
        store.request_review(ADA, fact["id"], BOB)
        store.mark_reviewed(BOB, fact["id"], "confirmed")
        assert store.pending_reviews(BOB)["count"] == 0


class TestDueForReview:
    @staticmethod
    def age(store, fact_id, *, created=None, reviewed=None):
        def stamp(days):
            return (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")

        with session(store.path) as conn:
            if created is not None:
                conn.execute("UPDATE facts SET created_at = ? WHERE id = ?", (stamp(created), fact_id))
            if reviewed is not None:
                conn.execute("UPDATE facts SET reviewed_at = ? WHERE id = ?", (stamp(reviewed), fact_id))

    def test_never_reviewed_counts_from_creation_and_the_list_is_oldest_first(self, store):
        old = store.add_fact(ADA, "Old", "Is a", "Fact")
        older = store.add_fact(ADA, "Older", "Is a", "Fact")
        fresh = store.add_fact(ADA, "Fresh", "Is a", "Fact")
        self.age(store, old["id"], created=120)
        self.age(store, older["id"], created=400)
        due = store.due_for_review(ADA)
        assert [f["id"] for f in due["facts"]] == [older["id"], old["id"]]
        assert fresh["id"] not in [f["id"] for f in due["facts"]]
        assert due["count"] == 2

    def test_a_recent_review_resets_the_clock(self, store):
        reviewed = store.add_fact(ADA, "Reviewed", "Is a", "Fact")
        self.age(store, reviewed["id"], created=400, reviewed=10)
        assert store.due_for_review(ADA)["count"] == 0
        self.age(store, reviewed["id"], reviewed=200)
        assert store.due_for_review(ADA)["count"] == 1

    def test_before_overrides_the_default_window(self, store, fact):
        assert store.due_for_review(ADA)["count"] == 0
        assert store.due_for_review(ADA, before="2100-01-01")["count"] == 1
        assert store.due_for_review(ADA, before="2000-01-01")["count"] == 0

    def test_it_only_lists_the_actors_own_facts(self, store, fact):
        assert store.due_for_review(BOB, before="2100-01-01")["count"] == 0

    def test_limit(self, store):
        for name in "ABC":
            store.add_fact(ADA, name, "Is a", "Letter")
        assert len(store.due_for_review(ADA, before="2100-01-01", limit=2)["facts"]) == 2

    def test_reviewing_removes_it_from_the_list(self, store, fact):
        assert store.due_for_review(ADA, before="2100-01-01")["count"] == 1
        store.mark_reviewed(ADA, fact["id"], "confirmed")
        assert store.due_for_review(ADA)["count"] == 0
