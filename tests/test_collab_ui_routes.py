from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette

from collab_hub.app import create_app
from collab_hub.store import CollabStore
from collab_hub.ui_routes import create_ui_routes


SECURITY_HEADERS = {
    "cache-control": "no-store",
    "pragma": "no-cache",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cross-origin-resource-policy": "same-origin",
}


@pytest.fixture
def client(tmp_path: Path):
    store = CollabStore(tmp_path / "collab.sqlite3")
    with TestClient(create_app(store)) as test_client:
        yield test_client
    store.close()


@pytest.fixture
def ui_root(tmp_path: Path) -> Path:
    root = tmp_path / "collab_ui"
    (root / "components").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>Deck</title>", encoding="utf-8")
    (root / "styles.css").write_text("body { color: white; }", encoding="utf-8")
    (root / "app.mjs").write_text("export const ready = true;", encoding="utf-8")
    (root / "mark.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (root / "deck.woff2").write_bytes(b"wOF2")
    (root / "components" / "messages.mjs").write_text(
        "export const messages = [];", encoding="utf-8"
    )
    return root


@pytest.fixture
def isolated_client(ui_root: Path) -> TestClient:
    return TestClient(Starlette(routes=create_ui_routes(ui_root)))


def test_ui_has_local_only_csp(client: TestClient) -> None:
    response = client.get("/ui/")

    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert "http:" not in csp
    assert "https:" not in csp


@pytest.mark.parametrize(
    ("asset", "content_type"),
    [
        ("/ui/", "text/html; charset=utf-8"),
        ("/ui/styles.css", "text/css; charset=utf-8"),
        ("/ui/app.mjs", "text/javascript; charset=utf-8"),
        ("/ui/mark.svg", "image/svg+xml"),
        ("/ui/deck.woff2", "font/woff2"),
        ("/ui/components/messages.mjs", "text/javascript; charset=utf-8"),
    ],
)
def test_serves_only_allowlisted_assets_with_exact_mime(
    isolated_client: TestClient, asset: str, content_type: str
) -> None:
    response = isolated_client.get(asset)

    assert response.status_code == 200
    assert response.headers["content-type"] == content_type
    for header, expected in SECURITY_HEADERS.items():
        assert response.headers[header] == expected


@pytest.mark.parametrize(
    "path",
    [
        "/ui/../outside.html",
        "/ui/%2e%2e/outside.html",
        "/ui/%252e%252e/outside.html",
        "/ui/%2e%2e%2foutside.html",
        "/ui/%5c..%5coutside.html",
        "/ui/%255c..%255coutside.html",
        "/ui/.hidden.html",
        "/ui/components/.hidden.mjs",
        "/ui/app.py",
        "/ui/.git/config",
        "/ui/missing.mjs",
        "/ui/components/",
    ],
)
def test_refuses_traversal_hidden_disallowed_and_missing_paths(
    isolated_client: TestClient, path: str
) -> None:
    response = isolated_client.get(path, follow_redirects=False)

    assert response.status_code == 404
    assert response.content in (b"", b"Not Found")


def test_refuses_symlink_that_escapes_ui_root(
    ui_root: Path, isolated_client: TestClient, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.mjs"
    outside.write_text("export const secret = true;", encoding="utf-8")
    link = ui_root / "escape.mjs"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    response = isolated_client.get("/ui/escape.mjs")

    assert response.status_code == 404
    assert b"secret" not in response.content


def test_refuses_ntfs_alternate_data_stream(
    ui_root: Path, isolated_client: TestClient
) -> None:
    stream = Path(f"{ui_root / 'index.html'}:leak.mjs")
    try:
        stream.write_text("export const secret = true;", encoding="utf-8")
    except OSError as exc:
        pytest.skip(f"alternate data streams unavailable: {exc}")

    response = isolated_client.get("/ui/index.html:leak.mjs")

    assert response.status_code == 404
    assert b"secret" not in response.content


def test_does_not_expose_python_git_secrets_or_directory_listing(
    ui_root: Path, isolated_client: TestClient
) -> None:
    (ui_root / "server.py").write_text("PASSWORD = 'not-public'", encoding="utf-8")
    (ui_root / ".env").write_text("TOKEN=not-public", encoding="utf-8")
    (ui_root / "private.txt").write_text("not-public", encoding="utf-8")

    for path in ("/ui/server.py", "/ui/.env", "/ui/private.txt", "/ui/components/"):
        response = isolated_client.get(path, follow_redirects=False)
        assert response.status_code == 404
        assert b"not-public" not in response.content


def test_existing_api_routes_remain_available(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
