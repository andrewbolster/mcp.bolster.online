"""JSONL export/import (the backup and migration format), schema-version refusal and the command line."""

import io
import json
import sqlite3

import pytest

from factstore import SCHEMA_VERSION, FactStore, SchemaVersionError, ValidationError
from factstore.__main__ import main

ADA, BOB = "ada", "bob"


@pytest.fixture
def populated(store):
    store.set_self(ADA, "person:Ada Example")
    store.add_alias(ADA, "bolster", "person:Ada Example")
    birthday = store.add_fact(
        ADA,
        "me",
        "Has birthday",
        "date:1988-05-17",
        attributes={"source": "passport"},
        references=["doc-1"],
        valid_from="1988-05-17T00:00:00Z",
        public=True,
    )
    partner = store.add_fact(
        ADA, "me", "Partner", "person:Bo Sample", valid_from="2012", valid_to="2015", confidence=0.8
    )
    store.add_fact(BOB, "Bob Sample", "Likes", "Tea")
    store.request_review(ADA, partner["id"], BOB, note="still right?")
    store.mark_reviewed(BOB, partner["id"], "disputed", "not sure")
    store.mark_reviewed(ADA, birthday["id"], "confirmed")
    store.request_review(ADA, birthday["id"], "cy")  # left open
    return store


def export(store, actor=None):
    out = io.StringIO()
    count = store.export_jsonl(out, actor)
    return out.getvalue(), count


def records(text):
    return [json.loads(line) for line in text.splitlines()]


class TestFormat:
    def test_header_first_then_one_record_per_line(self, populated):
        text, count = export(populated)
        lines = records(text)
        assert lines[0] == {"type": "header", "format": "factstore-jsonl", "schema_version": SCHEMA_VERSION}
        assert sum(1 for r in lines if r["type"] == "fact") == count == 6
        assert {r["type"] for r in lines} == {"header", "fact", "review", "review_request"}

    def test_a_fact_line_carries_every_field(self, populated):
        fact = next(r for r in records(export(populated)[0]) if r["type"] == "fact" and r["action"] == "Has birthday")
        assert set(fact) == {
            "type", "id", "subject", "subject_kind", "action", "object", "object_kind", "confidence", "valid_from",
            "valid_to", "public", "attributes", "references", "created_by", "created_at", "updated_by", "updated_at",
            "reviewed_by", "reviewed_at",
        }  # fmt: skip
        assert fact["attributes"] == {"source": "passport"}
        assert fact["reviewed_by"] == ADA

    def test_an_actor_export_has_only_their_facts_and_the_records_about_them(self, populated):
        lines = records(export(populated, BOB)[0])
        facts = [r for r in lines if r["type"] == "fact"]
        assert {f["created_by"] for f in facts} == {BOB}
        assert all(
            r["fact_id"] in {f["id"] for f in facts} for r in lines if r["type"] != "fact" and r["type"] != "header"
        )


class TestRoundTrip:
    def test_everything_survives_into_a_fresh_store(self, populated, tmp_path):
        text, _ = export(populated)
        fresh = FactStore(tmp_path / "fresh.sqlite3")
        counts = fresh.import_jsonl(io.StringIO(text))
        assert counts == {"facts": 6, "reviews": 2, "review_requests": 2, "skipped": 0}
        assert export(fresh)[0] == text  # byte-for-byte identical, ids and created_at included

    def test_behaviour_survives_too(self, populated, tmp_path):
        fresh = FactStore(tmp_path / "fresh.sqlite3")
        fresh.import_jsonl(io.StringIO(export(populated)[0]))
        assert fresh.add_fact(ADA, "me", "Likes", "Tea")["subject"] == "Ada Example"  # the self binding came across
        assert [f["object"] for f in fresh.search_facts(ADA, subject="bolster", action="Partner")["facts"]] == [
            "Bo Sample"
        ]
        assert fresh.search_facts(ADA, subject="me", action="Partner", valid_at="2013-01-01")["count"] == 1
        assert fresh.pending_reviews("cy")["count"] == 1  # the open request, and so its grant, came across
        assert fresh.search_facts("cy", scope="all")["count"] == 1

    def test_import_is_idempotent(self, populated, tmp_path):
        text, _ = export(populated)
        fresh = FactStore(tmp_path / "fresh.sqlite3")
        fresh.import_jsonl(io.StringIO(text))
        again = fresh.import_jsonl(io.StringIO(text))
        assert again == {"facts": 0, "reviews": 0, "review_requests": 0, "skipped": 10}
        assert export(fresh)[0] == text

    def test_import_merges_with_existing_data(self, populated, tmp_path):
        other = FactStore(tmp_path / "other.sqlite3")
        mine = other.add_fact("dee", "Dee Placeholder", "Likes", "Jam")
        other.import_jsonl(io.StringIO(export(populated)[0]))
        assert other.get_fact("dee", mine["id"])["object"] == "Jam"
        assert other.search_facts(ADA, subject="me")["count"] >= 2


class TestImportValidation:
    def reject(self, store, text, message):
        with pytest.raises(ValidationError, match=message):
            store.import_jsonl(io.StringIO(text))

    header = json.dumps({"type": "header", "format": "factstore-jsonl", "schema_version": SCHEMA_VERSION}) + "\n"

    def test_a_file_without_a_header_is_rejected(self, store):
        self.reject(store, '{"type": "fact"}\n', "first line must be the header")
        self.reject(store, "", "expected a header")

    def test_a_foreign_format_is_rejected(self, store):
        self.reject(store, json.dumps({"type": "header", "format": "something-else"}) + "\n", "not a factstore-jsonl")

    def test_a_newer_file_than_this_code_is_refused(self, store):
        newer = json.dumps({"type": "header", "format": "factstore-jsonl", "schema_version": SCHEMA_VERSION + 1}) + "\n"
        with pytest.raises(SchemaVersionError, match="understands up to"):
            store.import_jsonl(io.StringIO(newer))

    def test_a_bad_line_names_its_number_and_imports_nothing(self, store):
        good = {"type": "fact", "id": "01a-good", "subject": "A", "action": "Is a", "object": "B", "created_by": "ada",
                "created_at": "2026-01-01T00:00:00.000Z"}  # fmt: skip
        bad = {**good, "id": "01a-bad", "confidence": 5}
        self.reject(store, self.header + json.dumps(good) + "\n" + json.dumps(bad) + "\n", "line 3: .*confidence")
        assert store.search_facts("ada")["count"] == 0  # all or nothing

    def test_not_json_and_unknown_types(self, store):
        self.reject(store, self.header + "not json\n", "line 2")
        self.reject(store, self.header + json.dumps({"type": "mystery"}) + "\n", "unknown record type")
        self.reject(store, self.header + "[1, 2]\n", "must be a JSON object")

    def test_required_fields(self, store):
        no_id = {
            "type": "fact",
            "subject": "A",
            "action": "Is a",
            "object": "B",
            "created_by": "ada",
            "created_at": "2026-01-01T00:00:00Z",
        }
        self.reject(store, self.header + json.dumps(no_id) + "\n", "needs an id")
        no_time = {**no_id, "id": "x", "created_at": None}
        self.reject(store, self.header + json.dumps(no_time) + "\n", "created_at is required")
        bad_time = {**no_id, "id": "y", "created_at": "yesterday"}
        self.reject(store, self.header + json.dumps(bad_time) + "\n", "ISO 8601")


class TestSchemaVersion:
    def set_version(self, path, version):
        conn = sqlite3.connect(path)
        with conn:
            conn.execute("UPDATE schema_version SET version = ?", (version,))
        conn.close()

    def test_a_newer_database_is_refused_and_left_untouched(self, tmp_path):
        path = tmp_path / "facts.sqlite3"
        FactStore(path).add_fact(ADA, "A", "Is a", "B")
        self.set_version(path, SCHEMA_VERSION + 1)
        before = path.read_bytes()
        with pytest.raises(SchemaVersionError, match=f"version {SCHEMA_VERSION + 1}, which is newer"):
            FactStore(path)
        assert path.read_bytes() == before

    def test_an_older_database_is_refused_with_the_migration_path_named(self, tmp_path):
        path = tmp_path / "facts.sqlite3"
        FactStore(path)
        self.set_version(path, SCHEMA_VERSION - 1)
        with pytest.raises(SchemaVersionError, match="older.*export"):
            FactStore(path)

    def test_reopening_a_current_database_keeps_its_data(self, tmp_path):
        path = tmp_path / "facts.sqlite3"
        fact = FactStore(path).add_fact(ADA, "A", "Is a", "B")
        assert FactStore(path).get_fact(ADA, fact["id"])["id"] == fact["id"]

    def test_a_new_database_records_the_version_and_uses_wal(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "facts.sqlite3"
        FactStore(path)
        conn = sqlite3.connect(path)
        assert conn.execute("SELECT version FROM schema_version").fetchall() == [(SCHEMA_VERSION,)]
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        conn.close()


class TestCommandLine:
    def test_export_then_import_through_files(self, populated, tmp_path, capsys):
        backup = tmp_path / "backup.jsonl"
        assert main(["export", "--db", str(populated.path), "--all", "--out", str(backup)]) == 0
        assert "exported 6 facts" in capsys.readouterr().err
        target = tmp_path / "restored.sqlite3"
        assert main(["import", "--db", str(target), "--in", str(backup)]) == 0
        assert json.loads(capsys.readouterr().err)["facts"] == 6
        assert FactStore(target).search_facts(ADA, subject="me", action="Partner")["count"] == 1

    def test_an_actor_export_to_standard_output(self, populated, capsys):
        assert main(["export", "--db", str(populated.path), "--actor", "BOB"]) == 0
        captured = capsys.readouterr()
        facts = [r for r in records(captured.out) if r["type"] == "fact"]
        assert {f["created_by"] for f in facts} == {BOB}

    def test_import_from_standard_input(self, populated, tmp_path, capsys, monkeypatch):
        text, _ = export(populated)
        monkeypatch.setattr("sys.stdin", io.StringIO(text))
        assert main(["import", "--db", str(tmp_path / "stdin.sqlite3")]) == 0
        assert json.loads(capsys.readouterr().err)["facts"] == 6

    def test_errors_exit_non_zero_with_a_message(self, tmp_path, capsys):
        path = tmp_path / "facts.sqlite3"
        FactStore(path)
        conn = sqlite3.connect(path)
        with conn:
            conn.execute("UPDATE schema_version SET version = 99")
        conn.close()
        assert main(["export", "--db", str(path), "--all"]) == 1
        assert "newer" in capsys.readouterr().err

    def test_export_needs_an_actor_or_all(self, tmp_path):
        with pytest.raises(SystemExit):
            main(["export", "--db", str(tmp_path / "x.sqlite3")])
