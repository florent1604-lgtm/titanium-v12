"""Fail-closed static routes for the shared Command Deck UI."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute, Route


_ALLOWED_MEDIA_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".mjs": "text/javascript",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}

_CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'none'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self'",
        "font-src 'self'",
        "connect-src 'self' ws://127.0.0.1:8770",
        "media-src 'none'",
        "worker-src 'none'",
        "manifest-src 'none'",
    )
)

_SECURITY_HEADERS = {
    "Content-Security-Policy": _CONTENT_SECURITY_POLICY,
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _decode_path(value: str) -> str | None:
    """Decode nested URL encoding without ever accepting ambiguous input."""

    decoded = value
    try:
        for _ in range(4):
            candidate = unquote(decoded, errors="strict")
            if candidate == decoded:
                break
            decoded = candidate
    except (UnicodeDecodeError, ValueError):
        return None
    if "%" in decoded:
        return None
    return decoded


def _resolve_asset(root: Path, asset_path: str) -> tuple[Path, str] | None:
    decoded = _decode_path(asset_path)
    if decoded is None or "\\" in decoded or ":" in decoded or "\x00" in decoded:
        return None

    relative = "index.html" if decoded == "" else decoded
    segments = relative.split("/")
    if any(not segment or segment in {".", ".."} or segment.startswith(".") for segment in segments):
        return None

    suffix = Path(segments[-1]).suffix.lower()
    media_type = _ALLOWED_MEDIA_TYPES.get(suffix)
    if media_type is None:
        return None

    try:
        resolved_root = root.resolve(strict=True)
        candidate = resolved_root.joinpath(*segments).resolve(strict=True)
        candidate.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return None
    if not candidate.is_file():
        return None
    return candidate, media_type


def create_ui_routes(root: Path) -> list[BaseRoute]:
    """Create static UI routes rooted exclusively inside ``root``."""

    async def serve(request: Request) -> Response:
        asset_path = request.path_params.get("asset_path", "")
        resolved = _resolve_asset(root, asset_path)
        if resolved is None:
            return Response(status_code=404, headers=_SECURITY_HEADERS)
        path, media_type = resolved
        try:
            content = path.read_bytes()
        except OSError:
            return Response(status_code=404, headers=_SECURITY_HEADERS)
        return Response(
            content=content,
            media_type=media_type,
            headers=_SECURITY_HEADERS,
        )

    return [
        Route("/ui/", serve, methods=["GET"]),
        Route("/ui/{asset_path:path}", serve, methods=["GET"]),
    ]
