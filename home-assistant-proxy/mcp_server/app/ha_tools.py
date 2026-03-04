"""Home Assistant MCP tool implementations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List

from .confirmation import CONFIRMATION_TTL_SECONDS, confirmation_store
from .ha_client import ha_client
from .policy import PolicyDecision, evaluate_entity, evaluate_service
from .schemas import EntityState, ToolCall, ToolResponse

ToolHandler = Callable[[dict], Awaitable[ToolResponse]]


class ToolExecutionError(Exception):
    """Raised when a tool fails in a user-facing way."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: Dict
    handler: ToolHandler


async def execute_tool(call: ToolCall) -> ToolResponse:
    definition = _TOOL_REGISTRY.get(call.tool)
    if not definition:
        raise ToolExecutionError(404, f"Unknown tool '{call.tool}'")

    arguments = call.arguments or {}
    return await definition.handler(arguments)


def describe_tools() -> List[Dict]:
    """Return MCP-style tool metadata without handlers."""
    return [
        {
            "name": definition.name,
            "description": definition.description,
            "input_schema": definition.input_schema,
        }
        for definition in _TOOL_REGISTRY.values()
    ]


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
            # Issue a new token and ask the caller to confirm.
            token = confirmation_store.issue(domain, service, target, data)
            raise ToolExecutionError(
                409,
                (
                    f"confirmation_required|token={token}"
                    f"|expires_in={CONFIRMATION_TTL_SECONDS}"
                    f"|reason={decision.reason or 'High-risk service requires confirmation'}"
                ),
            )
        # Validate the supplied token.
        pending = confirmation_store.consume(confirmation_token, domain, service)
        if pending is None:
            raise ToolExecutionError(
                403,
                "Invalid, expired, or mismatched confirmation_token. "
                "Request a new token by calling without confirmation_token.",
            )
        # Use target/data from the original token (prevents replay with different args).
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


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

_TOOL_REGISTRY: Dict[str, ToolDefinition] = {
    "ha_list_entities": ToolDefinition(
        name="ha_list_entities",
        description="List policy-approved Home Assistant entities (optionally by domain).",
        input_schema={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Optional Home Assistant domain filter (e.g. 'light').",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=_handle_list_entities,
    ),
    "ha_get_state": ToolDefinition(
        name="ha_get_state",
        description="Fetch the latest state for a single Home Assistant entity (policy enforced).",
        input_schema={
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "Fully qualified entity_id (e.g. 'light.kitchen').",
                }
            },
            "required": ["entity_id"],
            "additionalProperties": False,
        },
        handler=_handle_get_state,
    ),
    "ha_list_areas": ToolDefinition(
        name="ha_list_areas",
        description="List all Home Assistant areas (rooms/zones) with their IDs and names.",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        handler=_handle_list_areas,
    ),
    "ha_call_service": ToolDefinition(
        name="ha_call_service",
        description=(
            "Call a Home Assistant service (write operation). "
            "Subject to domain allowlist and confirmation requirements for high-risk domains. "
            "If a 409 is returned, re-send the same call with the provided confirmation_token."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "HA domain (e.g. 'light', 'switch', 'lock').",
                },
                "service": {
                    "type": "string",
                    "description": "Service name (e.g. 'turn_on', 'turn_off', 'lock').",
                },
                "target": {
                    "type": "object",
                    "description": (
                        "Target selector. May contain entity_id, area_id, or device_id "
                        "(each a string or list of strings)."
                    ),
                    "additionalProperties": True,
                },
                "data": {
                    "type": "object",
                    "description": "Extra service data (e.g. brightness, temperature).",
                    "additionalProperties": True,
                },
                "confirmation_token": {
                    "type": "string",
                    "description": (
                        "Confirmation token returned in a previous 409 response. "
                        "Required for high-risk service calls."
                    ),
                },
            },
            "required": ["domain", "service"],
            "additionalProperties": False,
        },
        handler=_handle_call_service,
    ),
}
