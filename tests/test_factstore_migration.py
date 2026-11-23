"""Schema v3 and v4: an older database upgrades in place, atomically, with a backup, and is never half-migrated."""

import io
import json
import multiprocessing
import sqlite3
import threading
import time

import pytest

from factstore import SCHEMA_VERSION, DatabaseBusyError, FactStore, SchemaVersionError
from factstore import schema as schema_module
from factstore.__main__ import main as cli_main
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
    def test_the_current_schema_version_is_4(self):
        assert SCHEMA_VERSION == 4 and set(MIGRATIONS) == {2, 3}

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

        # the 3 -> 4 step fails part-way through, AFTER the 2 -> 3 step has already rewritten rows in the same
        # transaction: both must roll back, leaving the version 2 database exactly as it was
        monkeypatch.setitem(MIGRATIONS, 3, schema_module._refold(flaky))
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


def open_when_released(path, barrier, results):
    """Runs in a child process: wait for the start barrier, open the store, report what happened."""
    try:
        barrier.wait(60)
        FactStore(path)
        results.put("ok")
    except BaseException as error:  # noqa: BLE001 - reported to the parent
        results.put(f"{type(error).__name__}: {error}")


def open_together(path, openers):
    """Open ``path`` from ``openers`` separate processes released by one barrier, so they all start at once."""
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(openers), ctx.Queue()
    processes = [ctx.Process(target=open_when_released, args=(path, barrier, results)) for _ in range(openers)]
    for process in processes:
        process.start()
    outcomes = [results.get(timeout=120) for _ in processes]
    for process in processes:
        process.join(timeout=30)
    return outcomes


class TestConcurrentOpeners:
    """Opening is safe to repeat and safe to race: the first attempt at converting a database to WAL, or at creating
    or upgrading it, may be refused by SQLite with 'database is locked' without waiting, so openers retry."""

    OPENERS = 4

    def test_processes_opening_a_version_2_database_together_all_end_up_on_version_3(self, v2):
        assert open_together(v2, self.OPENERS) == ["ok"] * self.OPENERS
        assert read(v2, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]
        assert dict(read(v2, "SELECT id, subject_f FROM facts"))["f-alias"] == "zoe"
        assert read(v2, "SELECT COUNT(*) FROM facts") == [(len(FACTS),)]
        assert read(v2, "PRAGMA journal_mode") == [("wal",)]

    def test_only_one_backup_is_made_and_it_is_the_database_before_the_upgrade(self, v2):
        open_together(v2, self.OPENERS)
        backups = sorted(path.name for path in v2.parent.iterdir() if ".pre-v" in path.name)
        assert backups == ["facts.sqlite3.pre-v2.bak"]  # no temporary copies left behind either
        backup = v2.with_name(backups[0])
        assert read(backup, "SELECT version FROM schema_version") == [(2,)]
        assert dict(read(backup, "SELECT id, subject_f FROM facts"))["f-alias"] == "zoë"
        assert read(backup, "SELECT COUNT(*) FROM facts") == [(len(FACTS),)]

    def test_processes_creating_a_new_database_together_all_succeed(self, tmp_path):
        path = tmp_path / "facts.sqlite3"
        assert open_together(path, self.OPENERS) == ["ok"] * self.OPENERS
        assert read(path, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]
        assert read(path, "SELECT COUNT(*) FROM schema_version") == [(1,)]  # recorded once, not once per opener
        assert read(path, "SELECT COUNT(*) FROM facts") == [(0,)]
        assert FactStore(path).add_fact(ADA, "A", "Is a", "B")["subject"] == "A"

    def test_processes_opening_a_current_database_together_change_nothing(self, tmp_path):
        path = tmp_path / "facts.sqlite3"
        FactStore(path).add_fact(ADA, "A", "Is a", "B")
        assert open_together(path, self.OPENERS) == ["ok"] * self.OPENERS
        assert read(path, "SELECT COUNT(*) FROM facts") == [(1,)]

    def test_threads_in_one_process_opening_a_version_2_database_together_all_succeed(self, v2):
        errors: list[BaseException] = []
        barrier = threading.Barrier(self.OPENERS)

        def opener():
            try:
                barrier.wait(30)
                FactStore(v2)
            except BaseException as error:  # noqa: BLE001 - reported to the main thread
                errors.append(error)

        threads = [threading.Thread(target=opener) for _ in range(self.OPENERS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert errors == []
        assert read(v2, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]


class TestTheOpenRetriesAndWaits:
    def test_every_connection_waits_for_locks_from_its_first_statement(self, tmp_path):
        conn = schema_module.connect(tmp_path / "facts.sqlite3")
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 30_000
        conn.close()

    def test_a_lock_error_is_retried_and_other_errors_are_not(self, tmp_path, monkeypatch):
        path = tmp_path / "facts.sqlite3"
        calls = []

        def locked_twice(_path):
            calls.append(1)
            if len(calls) < 3:
                raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(schema_module, "_open_once", locked_twice)
        schema_module.initialise(path)
        assert len(calls) == 3

        calls.clear()

        def table_locked(_path):
            calls.append(1)
            if len(calls) < 2:
                raise sqlite3.OperationalError("database table is locked")

        monkeypatch.setattr(schema_module, "_open_once", table_locked)
        schema_module.initialise(path)
        assert len(calls) == 2

        calls.clear()

        def broken(_path):
            calls.append(1)
            raise sqlite3.OperationalError("no such table: facts")

        monkeypatch.setattr(schema_module, "_open_once", broken)
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            schema_module.initialise(path)
        assert len(calls) == 1  # not retried

    def test_a_database_that_stays_locked_gives_a_clear_error_after_the_bound(self, v2, monkeypatch):
        monkeypatch.setattr(schema_module, "BUSY_TIMEOUT_SECONDS", 0.2)
        monkeypatch.setattr(schema_module, "OPEN_RETRY_SECONDS", 0.6)
        holder = sqlite3.connect(v2)
        holder.execute("PRAGMA journal_mode=WAL")
        holder.execute("BEGIN IMMEDIATE")  # another process is writing and does not let go
        try:
            started = time.monotonic()
            with pytest.raises(DatabaseBusyError, match="stayed locked.*0.6 s"):
                FactStore(v2)
            assert 0.5 <= time.monotonic() - started < 10
        finally:
            holder.rollback()
            holder.close()
        assert read(v2, "SELECT version FROM schema_version") == [(2,)]  # nothing was changed
        FactStore(v2)  # and once the lock is released the upgrade goes through
        assert read(v2, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]

    def test_a_current_database_opens_while_another_process_holds_the_write_lock(self, tmp_path, monkeypatch):
        path = tmp_path / "facts.sqlite3"
        FactStore(path)
        monkeypatch.setattr(schema_module, "BUSY_TIMEOUT_SECONDS", 0.2)
        monkeypatch.setattr(schema_module, "OPEN_RETRY_SECONDS", 0.6)
        holder = sqlite3.connect(path)
        holder.execute("BEGIN IMMEDIATE")
        try:
            FactStore(path)  # takes no write lock, so it is not held up
        finally:
            holder.rollback()
            holder.close()

    def test_a_newer_database_is_refused_even_while_it_is_locked(self, tmp_path, monkeypatch):
        path = tmp_path / "facts.sqlite3"
        FactStore(path)
        conn = sqlite3.connect(path)
        with conn:
            conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION + 1,))
        monkeypatch.setattr(schema_module, "BUSY_TIMEOUT_SECONDS", 0.2)
        monkeypatch.setattr(schema_module, "OPEN_RETRY_SECONDS", 0.6)
        conn.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(SchemaVersionError, match="newer"):  # refused without waiting for the lock
                FactStore(path)
        finally:
            conn.rollback()
            conn.close()

    def test_the_command_line_upgrades_a_version_2_database_and_creates_a_new_one(self, v2, tmp_path, capsys):
        backup = tmp_path / "backup.jsonl"
        assert cli_main(["export", "--db", str(v2), "--all", "--out", str(backup)]) == 0
        assert read(v2, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]  # exporting upgraded it
        fresh = tmp_path / "other" / "facts.sqlite3"
        assert cli_main(["import", "--db", str(fresh), "--in", str(backup)]) == 0
        assert read(fresh, "SELECT version FROM schema_version") == [(SCHEMA_VERSION,)]
        assert read(fresh, "SELECT COUNT(*) FROM facts") == [(len(FACTS),)]
        assert "exported 5 facts" in capsys.readouterr().err
