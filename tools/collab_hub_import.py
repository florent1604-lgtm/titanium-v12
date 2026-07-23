"""Operator CLI for read-only import of the legacy collaboration bus."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collab_hub.import_ndjson import import_ndjson_paths
from collab_hub.store import CollabStore, DEFAULT_DB


def main() -> None:
    paths = tuple(Path(value) for value in sys.argv[1:]) or (
        ROOT / "collab" / "messages" / "stream.ndjson",
        ROOT / "collab" / "messages" / "acks.ndjson",
    )
    store = CollabStore(DEFAULT_DB)
    try:
        report = import_ndjson_paths(store, paths)
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()

