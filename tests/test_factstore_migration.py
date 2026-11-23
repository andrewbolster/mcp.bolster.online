"""Schema v3: a version 2 database upgrades in place, atomically, with a backup, and is never half-migrated."""

import io
import json
import sqlite3
import threading

import pytest

from factstore import SCHEMA_VERSION, FactStore, SchemaVersionError
from factstore import schema as schema_module
from factstore.schema import MIGRATIONS, SCHEMA

ADA, JOSE = "ada", "josé"


def v2_fold(text):
    """How version 2 folded names: case and whitespace only, so accents were significant."""
    return " ".join(text.split()).casefold()


FACTS = [
    # id, subject, subject_kind, action, object, object_kind, created_by
    ("f-alias", "Zoë", None, "Alias of", "Zoe Example", "person", ADA),
    ("f-likes", "Zoe Example", "person", "Likes", "Café", None, ADA),
    ("f-pref", "Zoe Example", "person", "Préfère", "Thé", None, ADA),
    ("f-self", JOSE, "actor", "Alias of", "Jose Example", "person", JOSE),
    ("f-jose", "Jose Example", "person", "Likes", "Jam", None, JOSE),
]


def make_v2(path):
    """A real version 2 database: the same tables, schema_version 2, names folded the version 2 way."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO schema_version (version) VALUES (2)")
    for fact_id, subject, s_kind, action, obj, o_kind, owner in FACTS:
        conn.execute(
            "INSERT INTO facts (id, subject, subject_f, subject_kind, action, action_f, object, object_f, "
            "object_kind, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '2026-01-01T00:00:00.000Z')",
            (fact_id, subject, v2_fold(subject), s_kind, action, v2_fold(action), obj, v2_fold(obj), o_kind, owner),
        )
    conn.execute(
        "INSERT INTO reviews (id, fact_id, reviewer, outcome, note, at) "
        "VALUES ('r1', 'f-likes', 'bob', 'confirmed', 'ok', '2026-02-01T00:00:00.000Z')"
    )
    conn.execute(
        "INSERT INTO review_requests (id, fact_id, requested_by, requested_of, requested_at, status) "
        "VALUES ('q1', 'f-pref', 'ada', 'cy', '2026-02-01T00:00:00.000Z', 'open')"
    )
    conn.commit()
    conn.close()


def read(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


@pytest.fixture
def v2(tmp_path):
    path = tmp_path / "facts.sqlite3"
    make_v2(path)
    return path


class TestUpgradeInPlace:
    def test_the_current_schema_version_is_3(self):
        assert SCHEMA_VERSION == 3 and set(MIGRATIONS) == {2}

    def test_opening_a_version_2_database_upgrades_it_and_keeps_every_row(self, v2):
        before = read(v2, "SELECT id, subject, action, object, created_by FROM facts ORDER BY id")
        store = FactStore(v2)
        assert read(v2, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]
        assert read(v2, "SELECT id, subject, action, object, created_by FROM facts ORDER BY id") == before
        assert read(v2, "SELECT COUNT(*) FROM reviews") == [(1,)]
        assert read(v2, "SELECT COUNT(*) FROM review_requests") == [(1,)]
        assert store.get_fact(ADA, "f-likes")["reviews"][0]["outcome"] == "confirmed"

    def test_the_folded_columns_are_recomputed(self, v2):
        assert dict(read(v2, "SELECT id, subject_f FROM facts"))["f-alias"] == "zoë"  # the version 2 form
        FactStore(v2)
        folded = {
            fact_id: (s, a, o) for fact_id, s, a, o in read(v2, "SELECT id, subject_f, action_f, object_f FROM facts")
        }
        assert folded["f-alias"] == ("zoe", "alias of", "zoe example")
        assert folded["f-pref"] == ("zoe example", "prefere", "the")
        assert folded["f-likes"] == ("zoe example", "likes", "cafe")

    def test_accent_insensitive_searches_work_on_the_upgraded_data(self, v2):
        store = FactStore(v2)
        assert store.search_facts(ADA, subject="Zoe")["total"] == 2  # the alias 'Zoë' now matches 'Zoe'
        assert store.search_facts(ADA, action="PREFERE")["total"] == 1
        assert store.search_facts(ADA, object="cafe")["total"] == 1
        assert store.describe_entity(ADA, "ZOË")["ref"] == "person:Zoe Example"

    def test_an_accented_logins_self_binding_still_works_after_the_upgrade(self, v2):
        store = FactStore(v2)
        found = store.search_facts(JOSE, subject="me")
        assert [f["object"] for f in found["facts"]] == ["Jam"]

    def test_a_backup_of_the_old_database_is_taken_first(self, v2):
        FactStore(v2)
        backup = v2.with_name("facts.sqlite3.pre-v2.bak")
        assert backup.exists()
        assert read(backup, "SELECT version FROM schema_version") == [(2,)]
        assert dict(read(backup, "SELECT id, subject_f FROM facts"))["f-alias"] == "zoë"
        assert read(backup, "SELECT COUNT(*) FROM facts") == [(len(FACTS),)]

    def test_opening_it_again_changes_nothing(self, v2):
        FactStore(v2)
        snapshot = read(v2, "SELECT * FROM facts ORDER BY id")
        FactStore(v2)
        assert read(v2, "SELECT * FROM facts ORDER BY id") == snapshot
        assert read(v2, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]

    def test_a_new_database_starts_at_the_current_version_with_no_backup(self, tmp_path):
        path = tmp_path / "facts.sqlite3"
        FactStore(path)
        assert read(path, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]
        assert list(tmp_path.glob("*.bak")) == []


class TestFailureLeavesTheDatabaseAsItWas:
    def test_a_failure_part_way_rolls_everything_back(self, v2, monkeypatch):
        def broken(conn):
            conn.execute("UPDATE facts SET subject_f = 'half-done' WHERE id = 'f-alias'")
            conn.execute("UPDATE schema_version SET version = 99")
            raise RuntimeError("disk on fire")

        monkeypatch.setitem(MIGRATIONS, 2, broken)
        with pytest.raises(RuntimeError, match="disk on fire"):
            FactStore(v2)
        assert read(v2, "SELECT version FROM schema_version") == [(2,)]
        assert dict(read(v2, "SELECT id, subject_f FROM facts"))["f-alias"] == "zoë"
        monkeypatch.undo()
        FactStore(v2)  # and the real migration still works afterwards
        assert read(v2, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]
        assert dict(read(v2, "SELECT id, subject_f FROM facts"))["f-alias"] == "zoe"

    def test_an_error_in_the_folding_itself_also_rolls_back(self, v2, monkeypatch):
        calls = {"n": 0}
        real_fold = schema_module.fold

        def flaky(text):
            calls["n"] += 1
            if calls["n"] > 4:
                raise RuntimeError("fold failed")
            return real_fold(text)

        monkeypatch.setattr(schema_module, "fold", flaky)
        with pytest.raises(RuntimeError, match="fold failed"):
            FactStore(v2)
        assert read(v2, "SELECT version FROM schema_version") == [(2,)]
        assert dict(read(v2, "SELECT id, subject_f FROM facts"))["f-alias"] == "zoë"


class TestWhatIsRefused:
    def test_a_newer_database_is_refused_and_left_untouched(self, tmp_path):
        path = tmp_path / "facts.sqlite3"
        FactStore(path).add_fact(ADA, "A", "Is a", "B")
        conn = sqlite3.connect(path)
        with conn:
            conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION + 1,))
        conn.close()
        before = path.read_bytes()
        with pytest.raises(SchemaVersionError, match="newer"):
            FactStore(path)
        assert path.read_bytes() == before
        assert list(tmp_path.glob("*.bak")) == []

    def test_a_version_with_no_migration_path_is_refused_and_not_backed_up(self, v2):
        conn = sqlite3.connect(v2)
        with conn:
            conn.execute("UPDATE schema_version SET version = 1")
        conn.close()
        with pytest.raises(SchemaVersionError, match="older.*export"):
            FactStore(v2)
        assert read(v2, "SELECT version FROM schema_version") == [(1,)]
        assert not v2.with_name("facts.sqlite3.pre-v1.bak").exists()


class TestExportsAcrossVersions:
    def test_a_version_2_export_imports_into_version_3_with_names_refolded(self, tmp_path):
        lines = [
            {"type": "header", "format": "factstore-jsonl", "schema_version": 2},
            {
                "type": "fact", "id": "x1", "subject": "Zoë Example", "subject_kind": "person", "action": "Likes",
                "object": "Café", "object_kind": None, "confidence": 1.0, "valid_from": None, "valid_to": None,
                "public": False, "attributes": {}, "references": [], "created_by": ADA,
                "created_at": "2026-01-01T00:00:00.000Z", "updated_by": None, "updated_at": None,
                "reviewed_by": None, "reviewed_at": None,
            },
        ]  # fmt: skip
        store = FactStore(tmp_path / "facts.sqlite3")
        counts = store.import_jsonl(io.StringIO("\n".join(json.dumps(line) for line in lines) + "\n"))
        assert counts["facts"] == 1
        assert store.search_facts(ADA, subject="ZOE EXAMPLE", object="cafe")["total"] == 1

    def test_the_export_header_names_the_format_and_the_schema_version(self, tmp_path):
        store = FactStore(tmp_path / "facts.sqlite3")
        out = io.StringIO()
        store.export_jsonl(out)
        assert json.loads(out.getvalue().splitlines()[0]) == {
            "type": "header",
            "format": "factstore-jsonl",
            "schema_version": SCHEMA_VERSION,
        }


class TestConcurrentOpeners:
    def test_two_processes_opening_a_version_2_database_at_once_both_end_up_on_version_3(self, v2):
        errors: list[BaseException] = []

        def opener():
            try:
                FactStore(v2)
            except BaseException as error:  # noqa: BLE001 - reported to the main thread
                errors.append(error)

        threads = [threading.Thread(target=opener) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert errors == []
        assert read(v2, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]
        assert dict(read(v2, "SELECT id, subject_f FROM facts"))["f-alias"] == "zoe"
        assert read(v2, "SELECT COUNT(*) FROM facts") == [(len(FACTS),)]
