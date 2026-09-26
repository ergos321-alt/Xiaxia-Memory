from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from unittest.mock import patch

import yaml
from flask import Flask

import app as app_module


_original_create_app = app_module.create_app
app_module.create_app = lambda: Flask("mcp-schema-tests")
try:
    mcp_module = importlib.import_module("mcp_app")
finally:
    app_module.create_app = _original_create_app


def test_mcp_discovery_matches_all_openapi_operations():
    spec = yaml.safe_load((Path(__file__).parents[1] / "openapi.yaml").read_text(encoding="utf-8"))
    expected = {
        operation["operationId"]
        for path in spec["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    }
    tools = asyncio.run(mcp_module.mcp.list_tools())
    assert {tool.name for tool in tools} == expected
    assert len(tools) == len(expected) == 4


def test_mcp_schemas_keep_openapi_requiredness_and_bounds():
    tools = {tool.name: tool for tool in asyncio.run(mcp_module.mcp.list_tools())}
    assert tools["saveMemories"].input_schema.get("required", []) == []
    assert tools["searchMemories"].input_schema.get("required", []) == []
    assert tools["getRecentContext"].input_schema["properties"]["days"]["default"] == 14
    assert tools["getRecentContext"].input_schema["properties"]["max_items"]["minimum"] == 5
    archive = tools["archiveWindowPeriod"].input_schema
    assert archive["required"] == ["period_label", "memories"]
    assert archive["properties"]["memories"]["minItems"] == 1
    assert archive["properties"]["memories"]["maxItems"] == 100
    assert archive["$defs"]["MemoryInput"]["properties"]["memory_text"]["maxLength"] == 4000


def test_archive_tool_forwards_to_existing_route_without_business_logic():
    memory = mcp_module.MemoryInput(memory_text="An existing fact", category="episodic")
    expected = {"period_label": "a supplied period", "memories": [{"memory_text": "An existing fact", "category": "episodic"}]}
    with patch.object(mcp_module, "_request", return_value={"saved": 1}) as request:
        result = mcp_module.archiveWindowPeriod("a supplied period", [memory])
    assert result == {"saved": 1}
    request.assert_called_once_with("POST", "/api/v1/windows/archive", body=expected)


def test_api_adapter_uses_existing_bearer_token_and_returns_api_json(monkeypatch):
    monkeypatch.setenv("PORT", "19999")
    monkeypatch.setenv("MEMORY_API_TOKEN", "unit-test-token")
    response_body = {"count": 0, "memories": []}
    response = type("Response", (), {"json": lambda self: response_body})()
    with patch.object(mcp_module.httpx, "Client") as client_type:
        client_type.return_value.__enter__.return_value.request.return_value = response
        result = mcp_module._request("GET", "/api/v1/context/recent", params={"days": 14})
    assert result is response_body
    client_type.return_value.__enter__.return_value.request.assert_called_once_with(
        "GET",
        "/api/v1/context/recent",
        params={"days": 14},
        json=None,
        headers={"Authorization": "Bearer unit-test-token"},
    )
