"""Command line: ``python -m factstore export|import``, the backup format and the schema migration path.

Examples:
    python -m factstore export --db data/facts.sqlite3 --all --out backup.jsonl
    python -m factstore export --db data/facts.sqlite3 --actor alice > alice.jsonl
    python -m factstore import --db data/facts.sqlite3 --in backup.jsonl
"""

import argparse
import json
import sys
from pathlib import Path

from .errors import FactsError
from .store import FactStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m factstore", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    export = commands.add_parser("export", help="write facts as JSON lines")
    export.add_argument("--db", required=True, type=Path, help="path to the SQLite database")
    scope = export.add_mutually_exclusive_group(required=True)
    scope.add_argument("--actor", help="export only the facts this actor created")
    scope.add_argument("--all", action="store_true", help="export every actor's facts (administrators only)")
    export.add_argument("--out", type=Path, help="output file (default: standard output)")

    load = commands.add_parser("import", help="load JSON lines (idempotent: existing ids are skipped)")
    load.add_argument("--db", required=True, type=Path, help="path to the SQLite database (created if new)")
    load.add_argument("--in", dest="source", type=Path, help="input file (default: standard input)")

    args = parser.parse_args(argv)
    try:
        store = FactStore(args.db)
        if args.command == "export":
            if args.out:
                with args.out.open("w", encoding="utf-8") as handle:
                    count = store.export_jsonl(handle, None if args.all else args.actor)
            else:
                count = store.export_jsonl(sys.stdout, None if args.all else args.actor)
            print(f"exported {count} facts", file=sys.stderr)
        else:
            if args.source:
                with args.source.open(encoding="utf-8") as handle:
                    counts = store.import_jsonl(handle)
            else:
                counts = store.import_jsonl(sys.stdin)
            print(json.dumps(counts), file=sys.stderr)
    except FactsError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
