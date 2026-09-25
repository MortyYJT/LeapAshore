from __future__ import annotations

import os
import re
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .models import KnowledgeSearchRequest
from .services.knowledge_rag import retrieve_official_knowledge

_ALLOWED_PROPOSALS = {"create_application_task", "update_application_choice", "update_profile"}
_OPAQUE_REF = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

mcp = FastMCP(
    "OfferPilot official knowledge and action proposals",
    instructions="Use only published OfferPilot official facts. Tool actions create proposals only; a separate user confirmation is required before execution.",
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=max(1, min(int(os.getenv("MCP_PORT", "8765")), 65535)),
    streamable_http_path="/mcp",
    json_response=True,
)


@mcp.tool(
    name="search_approved_facts",
    description="Search the locally available, reviewed official OfferPilot program facts and return citations.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
def search_approved_facts(query: str, program_slugs: list[str] | None = None) -> dict[str, Any]:
    response = retrieve_official_knowledge(KnowledgeSearchRequest(
        query=query,
        program_slugs=program_slugs or [],
        top_k=5,
    ))
    return {
        "retrieval_version": response.retrieval_version,
        "coverage_notice": response.coverage_notice,
        "hits": [
            {
                "chunk_id": hit.chunk_id,
                "program_slug": hit.program_slug,
                "program_name": hit.program_name,
                "section": hit.section,
                "content": hit.content,
                "source_id": hit.source.id,
                "source_title": hit.source.title,
                "source_url": hit.source.url,
                "source_version_id": hit.source.version_id,
                "content_hash": hit.source.content_hash,
                "verified_at": hit.source.verified_at,
            }
            for hit in response.hits
        ],
    }


@mcp.tool(
    name="propose_confirmed_action",
    description="Prepare an allowlisted application action proposal. This tool never writes data or submits an application.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
def propose_confirmed_action(action_type: str, resource_ref: str | None = None) -> dict[str, Any]:
    if action_type not in _ALLOWED_PROPOSALS:
        raise ValueError("unsupported action proposal")
    if resource_ref is not None and not _OPAQUE_REF.fullmatch(resource_ref):
        raise ValueError("invalid opaque resource reference")
    return {
        "action_type": action_type,
        "resource_ref": resource_ref,
        "state": "awaiting_user_confirmation",
        "requires_confirmation": True,
        "executed": False,
    }


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
