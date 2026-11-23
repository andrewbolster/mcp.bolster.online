"""Defects found by the news-and-releases experiment: punctuation-insensitive names (schema v4 with an in-place
migration from v3), what ``describe_entity`` returns for a typed name, and the review-state filters on
``due_for_review``."""

import io
import json
import sqlite3

import pytest

from factstore import SCHEMA_VERSION, FactStore, SchemaVersionError, ValidationError
from factstore import schema as schema_module
from factstore.schema import MIGRATIONS, SCHEMA
from factstore.values import fold, fold_accents
from tests.test_factstore_migration import make_v2, open_together, read

ADA, BOB = "ada", "bob"


# ------------------------------------------------------------------------------------------------ the fold


class TestPunctuationInsensitiveFold:
    @pytest.mark.parametrize(
        ("one", "other"),
        [
            ("Monthly Births (Northern Ireland)", "Monthly Births Northern Ireland"),
            ("Labour-Market  Statistics", "labour market statistics"),
            ("Zoë (née Example)", "zoe nee example"),
            ("O'Brien", "O’Brien"),
            ("O'Brien", "O Brien"),
            ("Health, Social Care & Wellbeing: Report", "health social care & wellbeing report"),
            ("snake_case", "snake case"),
            ("  Is   a ", "is A"),
            ("Q1 - 2024", "Q1 2024"),
            ("Report -- final", "Report final"),
            ("co-op", "co op"),
            ("Q1-2024 release", "q1-2024  RELEASE"),
        ],
    )
    def test_names_that_differ_only_by_punctuation_spacing_case_or_accents_are_one_name(self, one, other):
        assert fold(one) == fold(other)

    @pytest.mark.parametrize(
        ("one", "other"),
        [
            ("C++", "C"),
            ("C#", "C"),
            ("C++", "C#"),
            ("AT&T", "AT T"),
            ("50%", "50"),
            ("1.500", "1,500"),
            ("1.500", "1500"),
            ("-5", "5"),
            (".5", "5"),
            ("x = -5", "x = 5"),
            ("2019/20", "2019-20"),
            ("2019-20", "201920"),
            ("O'Brien", "OBrien"),
            ("(?)", "(!)"),
            ("+++", "++"),
        ],
    )
    def test_characters_that_carry_meaning_keep_names_apart(self, one, other):
        assert fold(one) != fold(other)

    def test_a_name_made_only_of_punctuation_does_not_fold_to_nothing(self):
        assert fold("(?)") == fold_accents("(?)") == "(?)"
        assert fold("...") == "..."

    def test_the_old_fold_is_unchanged_and_still_used_for_the_version_3_step(self):
        assert fold_accents("Monthly Births (Northern Ireland)") == "monthly births (northern ireland)"
        assert fold_accents("Zoë") == "zoe"


class TestMatchingByTheNewFold:
    def test_a_name_with_brackets_is_found_by_the_same_name_without(self, store):
        store.add_alias(ADA, "Monthly Births (Northern Ireland)", "org:Births Statistics")
        store.add_fact(ADA, "org:Births Statistics", "Has cadence", "text:Monthly")
        for typed in (
            "Monthly Births Northern Ireland",
            "monthly births (northern ireland)",
            "MONTHLY BIRTHS, NORTHERN IRELAND",
        ):
            found = store.search_facts(ADA, subject=typed)
            assert [f["action"] for f in found["facts"]] == ["Has cadence"], typed

    def test_c_plus_plus_and_c_stay_two_entities(self, store):
        store.add_fact(ADA, "C++", "Is a", "Language")
        store.add_fact(ADA, "C", "Is a", "Letter")
        assert [f["object"] for f in store.search_facts(ADA, subject="C++")["facts"]] == ["Language"]
        assert [f["object"] for f in store.search_facts(ADA, subject="c")["facts"]] == ["Letter"]
        assert store.describe_entity(ADA, "C++")["name"] == "C++"

    def test_apostrophes_follow_the_punctuation_rule(self, store):
        store.add_fact(ADA, "O'Brien", "Likes", "Tea")
        store.add_fact(ADA, "OBrien", "Likes", "Jam")
        assert [f["object"] for f in store.search_facts(ADA, subject="O’Brien")["facts"]] == ["Tea"]
        assert [f["object"] for f in store.search_facts(ADA, subject="o brien")["facts"]] == ["Tea"]
        assert [f["object"] for f in store.search_facts(ADA, subject="obrien")["facts"]] == ["Jam"]

    def test_numbers_that_differ_only_by_their_separator_are_different_values(self, store):
        store.add_fact(ADA, "Figure A", "Equals", "number:1.500")
        store.add_fact(ADA, "Figure B", "Equals", "number:1,500")
        assert [f["subject"] for f in store.search_facts(ADA, object="number:1.500")["facts"]] == ["Figure A"]
        assert [f["subject"] for f in store.search_facts(ADA, object="number:1,500")["facts"]] == ["Figure B"]

    def test_a_negative_number_and_a_leading_point_are_not_merged_with_the_plain_number(self, store):
        for value, subject in (("number:-5", "Change"), ("number:5", "Level"), ("number:.5", "Share")):
            store.add_fact(ADA, subject, "Equals", value)
        assert [f["subject"] for f in store.search_facts(ADA, object="number:-5")["facts"]] == ["Change"]
        assert [f["subject"] for f in store.search_facts(ADA, object="number:5")["facts"]] == ["Level"]
        assert [f["subject"] for f in store.search_facts(ADA, object="number:.5")["facts"]] == ["Share"]

    def test_free_text_ignores_punctuation_too(self, store):
        store.add_fact(ADA, "Release", "Has title", "Monthly Births (Northern Ireland)")
        assert store.search_facts(ADA, q="births northern ireland")["total"] == 1
        assert store.search_facts(ADA, q="(births)")["total"] == 1

    def test_a_name_that_is_only_punctuation_can_still_be_stored_and_found(self, store):
        store.add_fact(ADA, "(?)", "Means", "Unknown")
        store.add_fact(ADA, "(!)", "Means", "Surprise")
        assert [f["object"] for f in store.search_facts(ADA, subject="(?)")["facts"]] == ["Unknown"]
        assert [f["object"] for f in store.search_facts(ADA, subject="(!)")["facts"]] == ["Surprise"]

    def test_names_stay_as_written_in_results(self, store):
        store.add_fact(ADA, "Monthly Births (Northern Ireland)", "Is a", "Series")
        assert store.search_facts(ADA, subject="monthly births northern ireland")["facts"][0]["subject"] == (
            "Monthly Births (Northern Ireland)"
        )


# ------------------------------------------------------------------------------------------ the migration

V3_FACTS = [
    # id, subject, subject_kind, action, object, object_kind
    ("g-alias", "Monthly Births (Northern Ireland)", None, "Alias of", "Births Statistics", "org"),
    ("g-births", "Births Statistics", "org", "Has cadence", "Monthly", "text"),
    ("g-cpp", "C++", None, "Is a", "Language", None),
    ("g-c", "C", None, "Is a", "Letter", None),
    ("g-ob1", "O'Brien", "person", "Likes", "Tea", None),
    ("g-ob2", "OBrien", "person", "Likes", "Jam", None),
    ("g-num1", "Figure", None, "Equals", "1.500", "number"),
    ("g-num2", "Figure", None, "Equals", "1,500", "number"),
    ("g-year", "Releases", None, "Cover", "2019/20", None),
    ("g-punct", "(?)", None, "Means", "Unknown", None),
]


def make_v3(path):
    """A real version 3 database: the same tables, schema_version 3, names folded the version 3 way."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO schema_version (version) VALUES (3)")
    for fact_id, subject, s_kind, action, obj, o_kind in V3_FACTS:
        conn.execute(
            "INSERT INTO facts (id, subject, subject_f, subject_kind, action, action_f, object, object_f, "
            "object_kind, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '2026-01-01T00:00:00.000Z')",
            (fact_id, subject, fold_accents(subject), s_kind, action, fold_accents(action), obj, fold_accents(obj), o_kind, ADA),
        )  # fmt: skip
    conn.execute(
        "INSERT INTO reviews (id, fact_id, reviewer, outcome, note, at) "
        "VALUES ('r1', 'g-births', 'bob', 'confirmed', 'ok', '2026-02-01T00:00:00.000Z')"
    )
    conn.commit()
    conn.close()


@pytest.fixture
def v3(tmp_path):
    path = tmp_path / "facts.sqlite3"
    make_v3(path)
    return path


def folded(path):
    return {
        fact_id: (s, a, o) for fact_id, s, a, o in read(path, "SELECT id, subject_f, action_f, object_f FROM facts")
    }


class TestUpgradeFromVersion3:
    def test_the_fixture_really_is_a_version_3_database(self, v3):
        assert read(v3, "SELECT version FROM schema_version") == [(3,)]
        assert folded(v3)["g-alias"][0] == "monthly births (northern ireland)"  # punctuation still significant

    def test_opening_it_upgrades_in_place_and_keeps_every_row(self, v3):
        before = read(v3, "SELECT id, subject, action, object, created_by, confidence FROM facts ORDER BY id")
        store = FactStore(v3)
        assert read(v3, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)] == [(4,)]
        assert (
            read(v3, "SELECT id, subject, action, object, created_by, confidence FROM facts ORDER BY id") == before
        )  # nothing merged, moved or deleted: ids and wording are as they were
        assert read(v3, "SELECT COUNT(*) FROM reviews") == [(1,)]
        assert store.get_fact(ADA, "g-births")["reviews"][0]["outcome"] == "confirmed"

    def test_the_folded_columns_are_recomputed_with_the_new_fold(self, v3):
        FactStore(v3)
        after = folded(v3)
        assert after["g-alias"] == ("monthly births northern ireland", "alias of", "births statistics")
        assert after["g-cpp"][0] == "c++" and after["g-c"][0] == "c"
        assert (after["g-ob1"][0], after["g-ob2"][0]) == ("o brien", "obrien")
        assert (after["g-num1"][2], after["g-num2"][2]) == ("1.500", "1,500")
        assert after["g-year"][2] == "2019/20"
        assert after["g-punct"][0] == "(?)"

    def test_names_that_differ_only_by_punctuation_now_match_each_other_without_merging_facts(self, v3):
        store = FactStore(v3)
        assert store.search_facts(ADA, subject="Monthly Births Northern Ireland")["total"] == 1  # via the alias
        assert store.search_facts(ADA, subject="C++")["total"] == 1
        assert store.search_facts(ADA, subject="o brien")["total"] == 1
        assert store.search_facts(ADA, object="number:1.500")["total"] == 1
        assert read(v3, "SELECT COUNT(*) FROM facts") == [(len(V3_FACTS),)]

    def test_a_backup_of_the_version_3_database_is_taken_first(self, v3):
        FactStore(v3)
        backup = v3.with_name("facts.sqlite3.pre-v3.bak")
        assert read(backup, "SELECT version FROM schema_version") == [(3,)]
        assert folded(backup)["g-alias"][0] == "monthly births (northern ireland)"
        assert read(backup, "SELECT COUNT(*) FROM facts") == [(len(V3_FACTS),)]

    def test_opening_it_again_changes_nothing(self, v3):
        FactStore(v3)
        snapshot = read(v3, "SELECT * FROM facts ORDER BY id")
        FactStore(v3)
        assert read(v3, "SELECT * FROM facts ORDER BY id") == snapshot

    def test_a_version_2_database_goes_through_both_steps(self, tmp_path):
        path = tmp_path / "facts.sqlite3"
        make_v2(path)
        FactStore(path)
        assert read(path, "SELECT version FROM schema_version") == [(4,)]
        assert [p.name for p in tmp_path.glob("*.bak")] == ["facts.sqlite3.pre-v2.bak"]  # one backup, of the start
        assert read(tmp_path / "facts.sqlite3.pre-v2.bak", "SELECT version FROM schema_version") == [(2,)]


class TestUpgradeFromVersion3IsAtomic:
    def test_a_failure_part_way_rolls_back_and_leaves_the_database_at_version_3(self, v3, monkeypatch):
        calls = {"n": 0}

        def flaky(text):
            calls["n"] += 1
            if calls["n"] > 6:
                raise RuntimeError("fold failed")
            return fold(text)

        monkeypatch.setitem(MIGRATIONS, 3, schema_module._refold(flaky))
        before = read(v3, "SELECT * FROM facts ORDER BY id")
        with pytest.raises(RuntimeError, match="fold failed"):
            FactStore(v3)
        assert read(v3, "SELECT version FROM schema_version") == [(3,)]
        assert read(v3, "SELECT * FROM facts ORDER BY id") == before
        monkeypatch.undo()
        FactStore(v3)  # and the real migration still works afterwards
        assert read(v3, "SELECT version FROM schema_version") == [(4,)]

    def test_a_failure_in_the_new_step_also_undoes_the_version_2_step_of_the_same_upgrade(self, tmp_path, monkeypatch):
        path = tmp_path / "facts.sqlite3"
        make_v2(path)

        def broken(conn):
            raise RuntimeError("disk on fire")

        monkeypatch.setitem(MIGRATIONS, 3, broken)
        before = read(path, "SELECT * FROM facts ORDER BY id")
        with pytest.raises(RuntimeError, match="disk on fire"):
            FactStore(path)
        assert read(path, "SELECT version FROM schema_version") == [(2,)]
        assert read(path, "SELECT * FROM facts ORDER BY id") == before


class TestWhatIsRefusedAtVersion4:
    def test_a_version_5_database_is_refused_and_left_untouched(self, tmp_path):
        path = tmp_path / "facts.sqlite3"
        FactStore(path).add_fact(ADA, "A", "Is a", "B")
        conn = sqlite3.connect(path)
        with conn:
            conn.execute("UPDATE schema_version SET version = 5")
        conn.close()
        before = path.read_bytes()
        with pytest.raises(SchemaVersionError, match="schema version 5, which is newer"):
            FactStore(path)
        assert path.read_bytes() == before
        assert list(tmp_path.glob("*.bak")) == []


class TestExportsAcrossVersionsToVersion4:
    def _export(self, version, subject):
        header = {"type": "header", "format": "factstore-jsonl", "schema_version": version}
        fact = {
            "type": "fact", "id": "x1", "subject": subject, "subject_kind": None, "action": "Is a",
            "object": "Series", "object_kind": None, "confidence": 1.0, "valid_from": None, "valid_to": None,
            "public": False, "attributes": {}, "references": [], "created_by": ADA,
            "created_at": "2026-01-01T00:00:00.000Z", "updated_by": None, "updated_at": None,
            "reviewed_by": None, "reviewed_at": None,
        }  # fmt: skip
        return io.StringIO("\n".join(json.dumps(line) for line in (header, fact)) + "\n")

    @pytest.mark.parametrize("version", [2, 3])
    def test_an_older_export_imports_with_names_refolded_by_the_current_fold(self, tmp_path, version):
        store = FactStore(tmp_path / "facts.sqlite3")
        assert store.import_jsonl(self._export(version, "Monthly Births (Northern Ireland)"))["facts"] == 1
        assert store.search_facts(ADA, subject="Monthly Births Northern Ireland")["total"] == 1

    def test_a_version_4_export_round_trips(self, tmp_path):
        source = FactStore(tmp_path / "a.sqlite3")
        source.add_fact(ADA, "Monthly Births (Northern Ireland)", "Is a", "Series")
        out = io.StringIO()
        source.export_jsonl(out, ADA)
        assert json.loads(out.getvalue().splitlines()[0])["schema_version"] == 4
        target = FactStore(tmp_path / "b.sqlite3")
        assert target.import_jsonl(io.StringIO(out.getvalue()))["facts"] == 1
        assert target.search_facts(ADA, subject="monthly births northern ireland")["total"] == 1


class TestConcurrentOpenersFromVersion3:
    OPENERS = 4

    def test_processes_opening_a_version_3_database_together_all_end_up_on_version_4(self, v3):
        assert open_together(v3, self.OPENERS) == ["ok"] * self.OPENERS
        assert read(v3, "SELECT version FROM schema_version") == [(4,)]
        assert folded(v3)["g-alias"][0] == "monthly births northern ireland"
        assert read(v3, "SELECT COUNT(*) FROM facts") == [(len(V3_FACTS),)]

    def test_only_one_backup_is_made_and_it_is_the_version_3_database(self, v3):
        open_together(v3, self.OPENERS)
        backups = sorted(path.name for path in v3.parent.iterdir() if ".pre-v" in path.name)
        assert backups == ["facts.sqlite3.pre-v3.bak"]  # no temporary copies left behind either
        assert read(v3.with_name(backups[0]), "SELECT version FROM schema_version") == [(3,)]


# ------------------------------------------------------------------------------------- describe_entity

NISRA = "org:Northern Ireland Statistics and Research Agency"


class TestDescribeEntityReturnsTheResolvedEntity:
    def test_a_typed_name_comes_back_as_the_entity_it_is_stored_as(self, store):
        store.add_fact(ADA, NISRA, "Publishes", "Labour Market Report")
        described = store.describe_entity(ADA, "northern ireland statistics AND research agency")
        assert (described["name"], described["kind"], described["ref"]) == (
            "Northern Ireland Statistics and Research Agency",
            "org",
            NISRA,
        )
        assert described["exists"] is True and described["facts_as_subject"] == 1

    def test_an_alias_comes_back_as_its_canonical_entity(self, store):
        store.add_fact(ADA, NISRA, "Publishes", "Labour Market Report")
        store.add_alias(ADA, "NISRA", NISRA)
        described = store.describe_entity(ADA, "nisra")
        assert (described["name"], described["kind"], described["ref"]) == (
            "Northern Ireland Statistics and Research Agency",
            "org",
            NISRA,
        )

    def test_a_kind_prefixed_name_comes_back_with_its_stored_spelling(self, store):
        store.add_fact(ADA, NISRA, "Publishes", "Labour Market Report")
        assert store.describe_entity(ADA, "org:northern ireland statistics and research agency")["ref"] == NISRA

    def test_the_most_used_spelling_wins(self, store):
        store.add_fact(ADA, "Quarterly bulletin", "Is a", "Series")
        store.add_fact(ADA, "Quarterly Bulletin", "Has cadence", "text:Quarterly")
        store.add_fact(ADA, "Quarterly Bulletin", "Published by", "org:NISRA")
        assert store.describe_entity(ADA, "QUARTERLY BULLETIN")["name"] == "Quarterly Bulletin"

    def test_a_bare_name_that_is_stored_without_a_kind_stays_bare(self, store):
        store.add_fact(ADA, "Thing One", "Is a", "Thing")
        described = store.describe_entity(ADA, "thing one")
        assert (described["name"], described["kind"], described["ref"]) == ("Thing One", None, "Thing One")

    def test_a_bare_name_stored_under_several_kinds_is_not_guessed(self, store):
        store.add_fact(ADA, "org:Mercury", "Makes", "Cars")
        store.add_fact(ADA, "place:Mercury", "Is in", "Space")
        described = store.describe_entity(ADA, "mercury")
        assert described["kind"] is None and described["name"] == "mercury"
        assert described["facts_as_subject"] == 2
        assert "org:Mercury" in described["warnings"][0] and "place:Mercury" in described["warnings"][0]
        assert store.describe_entity(ADA, "place:mercury")["ref"] == "place:Mercury"

    def test_a_public_fact_shows_its_spelling_to_other_actors_in_public_and_all_scopes_only(self, store):
        store.add_fact(ADA, NISRA, "Publishes", "Labour Market Report", public=True)
        typed = "northern ireland statistics and research agency"
        for scope in ("public", "all"):
            assert store.describe_entity(BOB, typed, scope=scope)["ref"] == NISRA, scope
        assert store.describe_entity(BOB, typed)["ref"] == typed  # their own scope ('mine') has nothing

    def test_another_actors_private_spelling_is_never_shown(self, store):
        store.add_fact(ADA, NISRA, "Publishes", "Labour Market Report")
        other = store.describe_entity(BOB, "northern ireland statistics and research agency")
        assert (other["name"], other["kind"], other["exists"]) == (
            "northern ireland statistics and research agency",
            None,
            False,
        )


class TestExistsMeansARealEntity:
    def test_a_name_that_only_appears_as_a_value_is_not_an_entity(self, store):
        store.add_fact(ADA, "org:NISRA", "Has cadence", "text:Quarterly")
        store.add_fact(ADA, "org:HMRC", "Has cadence", "text:Quarterly")
        described = store.describe_entity(ADA, "Quarterly")
        assert described["exists"] is False
        assert described["mentioned_as_value_in"] == 2
        assert (described["kind"], described["ref"]) == ("text", "text:Quarterly")

    def test_dates_and_numbers_are_values_too(self, store):
        store.add_fact(ADA, "Event", "Happened on", "date:2020-01-31")
        store.add_fact(ADA, "Event", "Had size", "number:42")
        assert store.describe_entity(ADA, "date:2020-01-31")["exists"] is False
        assert store.describe_entity(ADA, "number:42")["mentioned_as_value_in"] == 1

    def test_an_entity_used_as_a_subject_or_as_a_plain_object_exists(self, store):
        store.add_fact(ADA, "Bo Sample", "Is a", "Person")
        assert store.describe_entity(ADA, "Bo Sample")["exists"] is True
        person = store.describe_entity(ADA, "person")  # only ever an object, with no kind: still an entity
        assert (person["exists"], person["mentioned_as_value_in"]) == (True, 0)

    def test_an_unknown_name_does_not_exist_and_is_not_a_value_either(self, store):
        described = store.describe_entity(ADA, "Totally Unknown Dataset")
        assert (described["exists"], described["mentioned_as_value_in"]) == (False, 0)

    def test_a_name_used_both_as_an_entity_and_as_a_value_exists(self, store):
        store.add_fact(ADA, "Quarterly", "Is a", "Cadence")
        store.add_fact(ADA, "org:NISRA", "Has cadence", "text:Quarterly")
        described = store.describe_entity(ADA, "quarterly")
        assert described["exists"] is True and described["mentioned_as_value_in"] == 1


# ------------------------------------------------------------------------------------- due_for_review

LATE = "2099-01-01"


class TestDueForReviewReviewState:
    @pytest.fixture
    def mixed(self, store):
        """Four facts: the first two confirmed by their owner, the last two never reviewed."""
        ids = [store.add_fact(ADA, f"Subject {n}", "Is a", "Thing")["id"] for n in range(4)]
        for fact_id in ids[:2]:
            store.mark_reviewed(ADA, fact_id, "confirmed")
        return store, ids

    def test_by_default_nothing_changes_every_fact_counts(self, mixed):
        store, ids = mixed
        assert store.due_for_review(ADA, LATE)["total"] == 4

    def test_reviewed_true_keeps_only_facts_that_have_been_reviewed(self, mixed):
        store, ids = mixed
        listed = store.due_for_review(ADA, LATE, reviewed=True)
        assert sorted(f["id"] for f in listed["facts"]) == sorted(ids[:2])

    def test_reviewed_false_excludes_facts_that_have_been_reviewed(self, mixed):
        store, ids = mixed
        listed = store.due_for_review(ADA, LATE, reviewed=False)
        assert sorted(f["id"] for f in listed["facts"]) == sorted(ids[2:])
        assert listed["total"] == 2

    def test_include_never_reviewed_false_lists_only_facts_whose_last_review_is_old(self, mixed):
        store, ids = mixed
        listed = store.due_for_review(ADA, LATE, include_never_reviewed=False)
        assert sorted(f["id"] for f in listed["facts"]) == sorted(ids[:2])
        # and a review that is recent is not due, whatever the baseline
        assert store.due_for_review(ADA, "2000-01-01", include_never_reviewed=False)["total"] == 0

    def test_asking_for_never_reviewed_facts_and_excluding_them_is_a_contradiction(self, mixed):
        store, _ = mixed
        with pytest.raises(ValidationError, match="include_never_reviewed"):
            store.due_for_review(ADA, LATE, reviewed=False, include_never_reviewed=False)

    def test_it_agrees_with_search_facts_on_which_facts_are_reviewed(self, mixed):
        store, _ = mixed
        due = {f["id"] for f in store.due_for_review(ADA, LATE, reviewed=True)["facts"]}
        searched = {f["id"] for f in store.search_facts(ADA, reviewed=True)["facts"]}
        assert due == searched
        never_due = {f["id"] for f in store.due_for_review(ADA, LATE, reviewed=False)["facts"]}
        assert never_due == {f["id"] for f in store.search_facts(ADA, reviewed=False)["facts"]}

    def test_it_composes_with_the_other_filters_and_paging(self, store):
        ids = [store.add_fact(ADA, f"S{n}", "Is a" if n % 2 else "Likes", "T")["id"] for n in range(6)]
        store.mark_reviewed(ADA, ids[0], "confirmed")
        listed = store.due_for_review(ADA, LATE, reviewed=False, action="Likes", limit=1)
        assert (listed["total"], listed["count"], listed["truncated"]) == (2, 1, True)
        assert ids[0] not in {f["id"] for f in listed["facts"]}
