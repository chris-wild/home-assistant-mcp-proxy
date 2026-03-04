"""Unit tests for HA tool handlers (ha_client and policy are mocked)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.confirmation import ConfirmationStore
from app.ha_tools import (
    ToolExecutionError,
    _handle_call_service,
    _handle_get_state,
    _handle_list_areas,
    _handle_list_entities,
)
from app.policy import PolicyDecision, PolicyResult
from app.schemas import ToolResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _allow():
    return PolicyResult(PolicyDecision.ALLOW)


def _deny(reason="Denied"):
    return PolicyResult(PolicyDecision.DENY, reason)


def _confirm(reason="Confirmation required"):
    return PolicyResult(PolicyDecision.REQUIRE_CONFIRMATION, reason)


# ---------------------------------------------------------------------------
# ha_list_entities
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_entities_returns_allowed(monkeypatch):
    entities = [
        {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
        {"entity_id": "lock.front", "state": "locked", "attributes": {}},
    ]
    monkeypatch.setattr("app.ha_tools.ha_client", AsyncMock(list_entities=AsyncMock(return_value=entities)))
    monkeypatch.setattr(
        "app.ha_tools.evaluate_entity",
        lambda entity_id, domain: _allow() if domain == "light" else _deny(),
    )

    result = await _handle_list_entities({})
    assert result.status == "ok"
    assert isinstance(result.data, list)
    assert len(result.data) == 1
    assert result.data[0]["entity_id"] == "light.kitchen"


@pytest.mark.asyncio
async def test_list_entities_domain_filter(monkeypatch):
    entities = [
        {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
        {"entity_id": "light.bedroom", "state": "off", "attributes": {}},
        {"entity_id": "switch.fan", "state": "off", "attributes": {}},
    ]
    monkeypatch.setattr("app.ha_tools.ha_client", AsyncMock(list_entities=AsyncMock(return_value=entities)))
    monkeypatch.setattr("app.ha_tools.evaluate_entity", lambda **_: _allow())

    result = await _handle_list_entities({"domain": "light"})
    ids = [e["entity_id"] for e in result.data]
    assert "light.kitchen" in ids
    assert "light.bedroom" in ids
    assert "switch.fan" not in ids


@pytest.mark.asyncio
async def test_list_entities_bad_domain_type(monkeypatch):
    with pytest.raises(ToolExecutionError) as exc_info:
        await _handle_list_entities({"domain": 42})
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# ha_get_state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_state_success(monkeypatch):
    raw = {"entity_id": "light.kitchen", "state": "on", "attributes": {"brightness": 200}}
    monkeypatch.setattr("app.ha_tools.ha_client", AsyncMock(get_state=AsyncMock(return_value=raw)))
    monkeypatch.setattr("app.ha_tools.evaluate_entity", lambda **_: _allow())

    result = await _handle_get_state({"entity_id": "light.kitchen"})
    assert result.status == "ok"
    assert result.data["state"] == "on"


@pytest.mark.asyncio
async def test_get_state_missing_entity_id():
    with pytest.raises(ToolExecutionError) as exc_info:
        await _handle_get_state({})
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_state_denied(monkeypatch):
    monkeypatch.setattr("app.ha_tools.evaluate_entity", lambda **_: _deny("Entity not in allowlist"))
    with pytest.raises(ToolExecutionError) as exc_info:
        await _handle_get_state({"entity_id": "lock.front"})
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_state_requires_confirmation(monkeypatch):
    monkeypatch.setattr("app.ha_tools.evaluate_entity", lambda **_: _confirm())
    with pytest.raises(ToolExecutionError) as exc_info:
        await _handle_get_state({"entity_id": "lock.front"})
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# ha_list_areas
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_areas_success(monkeypatch):
    areas = [{"id": "living_room", "name": "Living Room"}, {"id": "kitchen", "name": "Kitchen"}]
    monkeypatch.setattr("app.ha_tools.ha_client", AsyncMock(list_areas=AsyncMock(return_value=areas)))

    result = await _handle_list_areas({})
    assert result.status == "ok"
    assert len(result.data) == 2
    assert result.data[0]["id"] == "living_room"


# ---------------------------------------------------------------------------
# ha_call_service
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_service_allowed(monkeypatch):
    monkeypatch.setattr("app.ha_tools.evaluate_service", lambda **_: _allow())
    monkeypatch.setattr(
        "app.ha_tools.ha_client",
        AsyncMock(call_service=AsyncMock(return_value={"result": []})),
    )

    result = await _handle_call_service(
        {"domain": "light", "service": "turn_on", "target": {"entity_id": "light.kitchen"}}
    )
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_call_service_denied(monkeypatch):
    monkeypatch.setattr("app.ha_tools.evaluate_service", lambda **_: _deny("Domain not in allowlist"))
    with pytest.raises(ToolExecutionError) as exc_info:
        await _handle_call_service({"domain": "shell", "service": "run"})
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_call_service_confirmation_flow(monkeypatch):
    monkeypatch.setattr("app.ha_tools.evaluate_service", lambda **_: _confirm("High-risk"))

    # Fresh store so tokens don't bleed between tests.
    fresh_store = ConfirmationStore()
    monkeypatch.setattr("app.ha_tools.confirmation_store", fresh_store)

    # --- Step 1: no token → 409 with a new token ---
    with pytest.raises(ToolExecutionError) as exc_info:
        await _handle_call_service({"domain": "lock", "service": "lock"})
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert "confirmation_required" in detail

    # Extract token from detail string (format: "confirmation_required|token=<uuid>|...")
    token = next(
        part.split("=", 1)[1]
        for part in detail.split("|")
        if part.startswith("token=")
    )

    # --- Step 2: with valid token → success ---
    monkeypatch.setattr(
        "app.ha_tools.ha_client",
        AsyncMock(call_service=AsyncMock(return_value={"result": []})),
    )
    result = await _handle_call_service(
        {"domain": "lock", "service": "lock", "confirmation_token": token}
    )
    assert result.status == "ok"

    # --- Step 3: replay same token → 403 ---
    with pytest.raises(ToolExecutionError) as exc_info:
        await _handle_call_service(
            {"domain": "lock", "service": "lock", "confirmation_token": token}
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_call_service_missing_domain():
    with pytest.raises(ToolExecutionError) as exc_info:
        await _handle_call_service({"service": "turn_on"})
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_call_service_missing_service():
    with pytest.raises(ToolExecutionError) as exc_info:
        await _handle_call_service({"domain": "light"})
    assert exc_info.value.status_code == 400
