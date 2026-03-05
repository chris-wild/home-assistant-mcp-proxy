"""FastMCP server — proper MCP protocol transport over Streamable HTTP.

This module wires the existing tool handler functions (_handle_*) into a
FastMCP server instance.  All business logic (policy, HA client, confirmation
tokens, audit logging) lives in the other app modules and is unchanged.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from fastmcp import FastMCP

from .audit import emit_tool_audit
from .ha_tools import (
    ToolExecutionError,
    _handle_call_service,
    _handle_get_state,
    _handle_list_areas,
    _handle_list_entities,
    _handle_list_scenes,
)

mcp = FastMCP("Home Assistant MCP Proxy")


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------

async def _audited(tool_name: str, arguments: dict, coro):
    """Run *coro*, emit an audit record, and propagate any exception."""
    request_id = str(uuid.uuid4())
    start = time.perf_counter()
    decision = "allowed"
    ha_status: Optional[int] = None
    try:
        return await coro
    except ToolExecutionError as exc:
        decision = {
            403: "denied",
            409: "requires_confirmation",
        }.get(exc.status_code, "error")
        ha_status = exc.status_code
        raise
    finally:
        emit_tool_audit(
            request_id=request_id,
            tool=tool_name,
            arguments=arguments,
            decision=decision,
            ha_status=ha_status,
            latency_ms=(time.perf_counter() - start) * 1000,
        )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool
async def ha_get_state(entity_id: str) -> dict:
    """Fetch the current state of a single Home Assistant entity.

    Policy is enforced: denied entities return an error; entities in a
    confirmation-required domain return an error with a confirmation token.
    """
    args = {"entity_id": entity_id}
    result = await _audited("ha_get_state", args, _handle_get_state(args))
    return result.data


@mcp.tool
async def ha_list_entities(domain: str = "") -> list:
    """List policy-approved Home Assistant entities.

    Optionally filter by domain (e.g. 'light', 'switch').
    Entities in denied or confirmation-required domains are silently excluded.
    """
    args = {"domain": domain} if domain else {}
    result = await _audited("ha_list_entities", args, _handle_list_entities(args))
    return result.data


@mcp.tool
async def ha_list_areas() -> list:
    """List all Home Assistant areas (rooms/zones) with their IDs and names."""
    result = await _audited("ha_list_areas", {}, _handle_list_areas({}))
    return result.data


@mcp.tool
async def ha_list_scenes() -> list:
    """List all policy-approved Home Assistant scenes.

    Returns scenes with their entity_id, state, and attributes.
    Scenes in denied domains are silently excluded.
    """
    result = await _audited("ha_list_scenes", {}, _handle_list_scenes({}))
    return result.data


@mcp.tool
async def ha_call_service(
    domain: str,
    service: str,
    target: dict = None,
    data: dict = None,
    confirmation_token: str = "",
) -> dict:
    """Call a Home Assistant service.

    Subject to domain allowlist and confirmation requirements.

    For high-risk domains (e.g. 'lock') the first call returns an error
    containing a confirmation token.  Re-call with that token in
    *confirmation_token* to execute.  Tokens expire after 60 seconds.

    Args:
        domain: HA domain, e.g. 'light', 'switch', 'lock'.
        service: Service name, e.g. 'turn_on', 'lock'.
        target: Optional target selector — may contain entity_id, area_id,
                or device_id (each a string or list of strings).
        data: Optional extra service data, e.g. {'brightness': 200}.
        confirmation_token: Token from a previous confirmation-required error.
    """
    args: dict = {"domain": domain, "service": service}
    if target:
        args["target"] = target
    if data:
        args["data"] = data
    if confirmation_token:
        args["confirmation_token"] = confirmation_token

    result = await _audited("ha_call_service", args, _handle_call_service(args))
    return result.data
