"""Home Assistant tool handler functions.

These are pure-logic functions called by the FastMCP tool wrappers in
mcp_server.py.  They have no knowledge of the transport layer.
"""
from __future__ import annotations

from typing import List

from .confirmation import CONFIRMATION_TTL_SECONDS, confirmation_store
from .ha_client import ha_client
from .policy import PolicyDecision, evaluate_entity, evaluate_service
from .schemas import EntityState, ToolResponse


class ToolExecutionError(Exception):
    """Raised when a tool fails in a user-facing way."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------------------
# ha_list_entities
# ---------------------------------------------------------------------------

async def _handle_list_entities(arguments: dict | None) -> ToolResponse:
    domain_filter = (arguments or {}).get("domain")
    if domain_filter and not isinstance(domain_filter, str):
        raise ToolExecutionError(400, "domain must be a string when provided")

    ha_entities = await ha_client.list_entities()
    filtered: List[EntityState] = []
    for entity in ha_entities:
        entity_id = entity.get("entity_id")
        if not isinstance(entity_id, str):
            continue
        domain = _extract_domain(entity_id)
        if domain_filter and domain != domain_filter:
            continue

        decision = evaluate_entity(entity_id=entity_id, domain=domain)
        if decision.decision != PolicyDecision.ALLOW:
            # Require-confirmation or denied entities stay filtered out at this layer.
            continue

        filtered.append(
            EntityState(
                entity_id=entity_id,
                state=str(entity.get("state", "")),
                attributes=entity.get("attributes") or {},
            )
        )

    payload = [item.model_dump() for item in filtered]
    return ToolResponse(status="ok", data=payload, detail=None)


# ---------------------------------------------------------------------------
# ha_get_state
# ---------------------------------------------------------------------------

async def _handle_get_state(arguments: dict | None) -> ToolResponse:
    if not arguments or "entity_id" not in arguments:
        raise ToolExecutionError(400, "entity_id is required")

    entity_id = arguments["entity_id"]
    if not isinstance(entity_id, str):
        raise ToolExecutionError(400, "entity_id must be a string")

    domain = _extract_domain(entity_id)
    decision = evaluate_entity(entity_id=entity_id, domain=domain)
    if decision.decision == PolicyDecision.DENY:
        raise ToolExecutionError(403, decision.reason or "Denied by policy")
    if decision.decision == PolicyDecision.REQUIRE_CONFIRMATION:
        raise ToolExecutionError(409, decision.reason or "Confirmation required")

    state_raw = await ha_client.get_state(entity_id)
    entity_state = EntityState(
        entity_id=state_raw.get("entity_id", entity_id),
        state=str(state_raw.get("state", "")),
        attributes=state_raw.get("attributes") or {},
    )
    return ToolResponse(status="ok", data=entity_state.model_dump(), detail=None)


# ---------------------------------------------------------------------------
# ha_list_areas
# ---------------------------------------------------------------------------

async def _handle_list_areas(arguments: dict | None) -> ToolResponse:  # noqa: ARG001
    """Return all Home Assistant areas — read-only, no policy check needed."""
    areas = await ha_client.list_areas()
    return ToolResponse(status="ok", data=areas, detail=None)


# ---------------------------------------------------------------------------
# ha_list_scenes
# ---------------------------------------------------------------------------

async def _handle_list_scenes(arguments: dict | None) -> ToolResponse:  # noqa: ARG001
    """Return all policy-approved Home Assistant scenes."""
    scenes_raw = await ha_client.list_scenes()
    filtered = []
    for scene in scenes_raw:
        entity_id = scene.get("entity_id")
        if not isinstance(entity_id, str):
            continue
        decision = evaluate_entity(entity_id=entity_id, domain="scene")
        if decision.decision != PolicyDecision.ALLOW:
            continue
        filtered.append({
            "entity_id": entity_id,
            "state": str(scene.get("state", "")),
            "attributes": scene.get("attributes") or {},
        })
    return ToolResponse(status="ok", data=filtered, detail=None)


# ---------------------------------------------------------------------------
# ha_activate_scene
# ---------------------------------------------------------------------------

async def _handle_activate_scene(arguments: dict | None) -> ToolResponse:
    args = arguments or {}
    scene_id = args.get("scene_id")
    if not scene_id or not isinstance(scene_id, str):
        raise ToolExecutionError(400, "scene_id is required and must be a string")
    if not scene_id.startswith("scene."):
        raise ToolExecutionError(400, "scene_id must be a scene entity (e.g. 'scene.movie_night')")

    decision = evaluate_entity(entity_id=scene_id, domain="scene")
    if decision.decision == PolicyDecision.DENY:
        raise ToolExecutionError(403, decision.reason or "Denied by policy")
    if decision.decision == PolicyDecision.REQUIRE_CONFIRMATION:
        raise ToolExecutionError(409, decision.reason or "Confirmation required")

    result = await ha_client.activate_scene(scene_id)
    return ToolResponse(status="ok", data=result, detail=None)


# ---------------------------------------------------------------------------
# ha_call_service
# ---------------------------------------------------------------------------

async def _handle_call_service(arguments: dict | None) -> ToolResponse:
    args = arguments or {}

    domain = args.get("domain")
    service = args.get("service")
    if not domain or not isinstance(domain, str):
        raise ToolExecutionError(400, "domain is required and must be a string")
    if not service or not isinstance(service, str):
        raise ToolExecutionError(400, "service is required and must be a string")

    target = args.get("target")
    data = args.get("data")
    if target is not None and not isinstance(target, dict):
        raise ToolExecutionError(400, "target must be an object when provided")
    if data is not None and not isinstance(data, dict):
        raise ToolExecutionError(400, "data must be an object when provided")

    confirmation_token = args.get("confirmation_token")

    decision = evaluate_service(domain=domain, service=service)

    if decision.decision == PolicyDecision.DENY:
        raise ToolExecutionError(403, decision.reason or "Service call denied by policy")

    if decision.decision == PolicyDecision.REQUIRE_CONFIRMATION:
        if not confirmation_token:
            token = confirmation_store.issue(domain, service, target, data)
            raise ToolExecutionError(
                409,
                (
                    f"confirmation_required|token={token}"
                    f"|expires_in={CONFIRMATION_TTL_SECONDS}"
                    f"|reason={decision.reason or 'High-risk service requires confirmation'}"
                ),
            )
        pending = confirmation_store.consume(confirmation_token, domain, service)
        if pending is None:
            raise ToolExecutionError(
                403,
                "Invalid, expired, or mismatched confirmation_token. "
                "Request a new token by calling without confirmation_token.",
            )
        target = pending.target
        data = pending.data

    result = await ha_client.call_service(domain, service, target=target, data=data)
    return ToolResponse(status="ok", data=result, detail=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_domain(entity_id: str | None) -> str | None:
    if not entity_id or "." not in entity_id:
        return None
    return entity_id.split(".", 1)[0]
