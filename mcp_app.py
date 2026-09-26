"""Thin MCP tools that call the existing authenticated Memory HTTP API."""

from __future__ import annotations

import contextlib
import os
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from a2wsgi import WSGIMiddleware
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.routing import Mount

from app import create_app


MemoryCategory = Literal["semantic", "episodic", "relationship", "taste", "ongoing"]
MemoryStatus = Literal["active", "historical", "superseded", "archived"]


class MemoryInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    memory_text: Annotated[str, Field(max_length=4000)]
    category: MemoryCategory
    subtype: str | None = None
    importance: Annotated[int, Field(ge=1, le=10)] = 5
    occurred_at: datetime | None = None
    source: str = "custom_gpt"
    status: MemoryStatus = "active"
    supersedes: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="allow")

    category: MemoryCategory | None = None
    subtype: str | None = None
    status: MemoryStatus | None = None
    min_importance: Annotated[int, Field(ge=1, le=10)] | None = None
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None


diary_app = create_app()
mcp = MCPServer("Xiaxia Memory")


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call one existing API route using its existing Bearer credential."""
    port = os.environ.get("PORT", "10000")
    token = os.environ["MEMORY_API_TOKEN"]
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120.0) as client:
        response = client.request(
            method,
            path,
            params={key: value for key, value in (params or {}).items() if value is not None},
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
    return response.json()


def _model_payload(value: BaseModel) -> dict[str, Any]:
    return value.model_dump(mode="json", by_alias=True, exclude_unset=True)


@mcp.tool()
def saveMemories(
    raw_text: Annotated[str | None, Field(max_length=24000)] = None,
    source: str | None = "automatic",
    memories: Annotated[list[MemoryInput], Field(max_length=100)] = None,
) -> dict[str, Any]:
    """Save supplied memories or submit text for extraction; return the saved records."""
    body: dict[str, Any] = {"source": source}
    if raw_text is not None:
        body["raw_text"] = raw_text
    if memories is not None:
        body["memories"] = [_model_payload(item) for item in memories]
    return _request("POST", "/api/v1/memories/save", body=body)


@mcp.tool()
def searchMemories(
    query: str = "",
    top_k: Annotated[int, Field(ge=1, le=20)] = 6,
    filters: SearchFilters = None,
) -> dict[str, Any]:
    """Search memories with an optional query and filters; return matching records."""
    body: dict[str, Any] = {"query": query, "top_k": top_k}
    if filters is not None:
        body["filters"] = _model_payload(filters)
    return _request("POST", "/api/v1/memories/search", body=body)


@mcp.tool()
def getRecentContext(
    days: Annotated[int, Field(ge=1, le=90)] = 14,
    max_items: Annotated[int, Field(ge=5, le=40)] = 20,
) -> dict[str, Any]:
    """Return bounded recent context in the existing API's five memory groups."""
    return _request("GET", "/api/v1/context/recent", params={"days": days, "max_items": max_items})


@mcp.tool()
def archiveWindowPeriod(
    period_label: str,
    memories: Annotated[list[MemoryInput], Field(min_length=1, max_length=100)],
    metadata: dict[str, Any] = None,
) -> dict[str, Any]:
    """Import structured memories for a labeled legacy chat period."""
    body: dict[str, Any] = {
        "period_label": period_label,
        "memories": [_model_payload(item) for item in memories],
    }
    if metadata is not None:
        body["metadata"] = metadata
    return _request("POST", "/api/v1/windows/archive", body=body)


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette):
    async with mcp.session_manager.run():
        yield


host = os.environ.get("MEMORY_PUBLIC_HOST", "xiaxia-memory.onrender.com")
transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[host, f"{host}:*", "localhost:*", "127.0.0.1:*"],
)
mcp_http_app = mcp.streamable_http_app(transport_security=transport_security)
memory_wsgi_app = WSGIMiddleware(diary_app, workers=4)


async def dispatch_http(scope, receive, send):
    """Send /mcp to MCP; preserve all existing Flask routes elsewhere."""
    if scope["path"] == "/mcp":
        await mcp_http_app(scope, receive, send)
    else:
        await memory_wsgi_app(scope, receive, send)


app = Starlette(routes=[Mount("/", app=dispatch_http)], lifespan=lifespan)
