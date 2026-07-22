"""Managed loopback launcher for the Titanium CollabHub singleton."""

from __future__ import annotations

from pathlib import Path
import sys

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collab_hub.app import create_app
from collab_hub.store import CollabStore, DEFAULT_DB


def main() -> None:
    if "--check" in sys.argv[1:]:
        print("COLLAB_IMPORT_OK")
        return
    store = CollabStore(DEFAULT_DB)
    try:
        uvicorn.run(
            create_app(store),
            host="127.0.0.1",
            port=8770,
            reload=False,
            log_level="info",
        )
    finally:
        store.close()


if __name__ == "__main__":
    main()
