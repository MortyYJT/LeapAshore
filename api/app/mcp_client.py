import os
from urllib.parse import urlparse

from langchain_mcp_adapters.client import MultiServerMCPClient

_INTERNAL_HOSTS = {"localhost", "127.0.0.1", "::1", "mcp-agent"}


def connection_from_env() -> dict[str, str]:
    url = os.getenv("MCP_SERVER_URL", "").strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or (host not in _INTERNAL_HOSTS and not host.endswith((".internal", ".local"))):
        raise ValueError("MCP server URL must use an internal host")
    if parsed.path not in {"", "/mcp"}:
        raise ValueError("MCP server URL path must be /mcp")
    return {"transport": "streamable_http", "url": url.rstrip("/") + ("/mcp" if parsed.path == "" else "")}


async def load_offerpilot_mcp_tools() -> list:
    if os.getenv("MCP_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        return []
    connection = connection_from_env()
    client = MultiServerMCPClient({"offerpilot": connection}, handle_tool_errors=True)
    tools = await client.get_tools(server_name="offerpilot")
    allowed = {"search_approved_facts", "propose_confirmed_action"}
    if {tool.name for tool in tools} != allowed:
        raise RuntimeError("MCP tool registry does not match the approved allowlist")
    return tools
