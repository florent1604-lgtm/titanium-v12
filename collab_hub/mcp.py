"""Strict C1-only MCP adapter for CollabHub."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from mcp.server.fastmcp import FastMCP

from .contracts import MessageDraft
from .store import CollabStore


def _stored_to_dict(message) -> dict:
    value = asdict(message)
    value["evidence_refs"] = list(message.evidence_refs)
    return value


def create_collab_mcp(store: CollabStore, broker: Any) -> FastMCP:
    """Create the exact five-tool collaboration surface; no effectful tools."""
    mcp = FastMCP(
        "titanium-collab-hub",
        instructions=(
            "Local C1 shadow collaboration only. No shell, permission approval, "
            "filesystem mutation, Git operation, CommandGateway dispatch or trading."
        ),
        host="127.0.0.1",
        port=8770,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool()
    async def collab_publish(
        principal: str,
        target: str,
        kind: str,
        content: str,
        idempotency_key: str,
        task_id: str | None = None,
        correlation_id: str | None = None,
        in_reply_to: str | None = None,
        evidence_refs: list[str] | None = None,
        classification: str = "INTERNAL",
    ) -> dict:
        """Publish one typed C1 message after a durable SQLite commit."""
        draft = MessageDraft(
            principal=principal,
            target=target,
            kind=kind,
            content=content,
            idempotency_key=idempotency_key,
            task_id=task_id,
            correlation_id=correlation_id,
            in_reply_to=in_reply_to,
            evidence_refs=tuple(evidence_refs or ()),
            classification=classification,
        )
        receipt = await asyncio.to_thread(store.publish, draft)
        if not receipt.duplicate:
            rows = await asyncio.to_thread(
                store.read, after_offset=receipt.global_offset - 1, limit=1
            )
            if rows:
                await broker.publish(_stored_to_dict(rows[0]))
        return asdict(receipt)

    @mcp.tool()
    async def collab_read(after_offset: int = 0, limit: int = 100) -> dict:
        """Replay committed collaboration messages in global-offset order."""
        rows = await asyncio.to_thread(store.read, after_offset=after_offset, limit=limit)
        return {"messages": [_stored_to_dict(row) for row in rows]}

    @mcp.tool()
    async def collab_ack(consumer_id: str, global_offset: int) -> dict:
        """Advance a durable consumer cursor monotonically."""
        await asyncio.to_thread(
            store.ack, consumer_id=consumer_id, global_offset=global_offset
        )
        current = await asyncio.to_thread(store.consumer_offset, consumer_id)
        return {"consumer_id": consumer_id, "global_offset": current}

    @mcp.tool()
    async def collab_presence(
        principal: str | None = None,
        state: str | None = None,
        detail: str = "",
    ) -> dict:
        """Set one C1 presence heartbeat or list all known principals."""
        if principal is not None or state is not None:
            if principal is None or state is None:
                raise ValueError("principal et state doivent être fournis ensemble")
            await asyncio.to_thread(
                store.set_presence, principal=principal, state=state, detail=detail
            )
        rows = await asyncio.to_thread(store.list_presence)
        return {"presence": list(rows)}

    @mcp.tool()
    async def collab_health() -> dict:
        """Return durable store and realtime transport health."""
        result = await asyncio.to_thread(store.health)
        result["ws_clients"] = broker.active_count
        result["transport"] = "LOOPBACK_C1_SHADOW"
        return result

    return mcp
