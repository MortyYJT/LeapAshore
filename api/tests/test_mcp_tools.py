import asyncio

import pytest

from app.mcp_server import mcp, propose_confirmed_action, search_approved_facts


def test_mcp_official_knowledge_tool_returns_citations_from_local_corpus() -> None:
    result = search_approved_facts("UNSW 双非学生需要多少均分", ["unsw-master-it"])
    assert result["hits"]
    assert all(hit["source_url"].startswith("https://") for hit in result["hits"])


def test_mcp_write_capability_only_creates_confirmation_proposal() -> None:
    proposal = propose_confirmed_action("create_application_task", "opaque-resource-1")
    assert proposal["state"] == "awaiting_user_confirmation"
    assert proposal["requires_confirmation"] is True
    assert proposal["executed"] is False
    with pytest.raises(ValueError, match="unsupported action"):
        propose_confirmed_action("submit_application", "resource")


def test_mcp_tools_advertise_read_only_and_closed_world_annotations() -> None:
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    assert set(tools) == {"search_approved_facts", "propose_confirmed_action"}
    assert all(tool.annotations.readOnlyHint for tool in tools.values())
    assert all(tool.annotations.openWorldHint is False for tool in tools.values())


def test_langchain_mcp_client_tool_load_uses_only_private_server_host(monkeypatch) -> None:
    from app.mcp_client import connection_from_env

    monkeypatch.setenv("MCP_SERVER_URL", "http://mcp-agent:8765/mcp")
    assert connection_from_env() == {"transport": "streamable_http", "url": "http://mcp-agent:8765/mcp"}
    monkeypatch.setenv("MCP_SERVER_URL", "https://external.example/mcp")
    with pytest.raises(ValueError, match="internal"):
        connection_from_env()


def test_mcp_client_is_off_by_default(monkeypatch) -> None:
    from app.mcp_client import load_offerpilot_mcp_tools

    monkeypatch.delenv("MCP_ENABLED", raising=False)
    assert asyncio.run(load_offerpilot_mcp_tools()) == []
