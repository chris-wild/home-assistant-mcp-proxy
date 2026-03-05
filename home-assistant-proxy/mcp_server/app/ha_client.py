"""Async client for the Home Assistant REST API with retry logic."""
from __future__ import annotations

import asyncio
import json
import logging
import random

import httpx

from .config import settings

logger = logging.getLogger(__name__)

# Retry configuration
_MAX_RETRIES = 3
_BASE_DELAY = 0.5  # seconds
_JITTER_MAX = 0.1  # seconds


class HomeAssistantClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.home_assistant_url,
            headers=self._auth_headers,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    @property
    def _auth_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.access_token:
            headers["Authorization"] = f"Bearer {settings.access_token}"
        return headers

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal retry helper
    # ------------------------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Execute an HTTP request with exponential back-off retries.

        Retries on ``httpx.TransportError`` (network-level failures) and on
        HTTP 5xx responses.  Raises on the final attempt.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.request(method, path, **kwargs)
                if response.status_code >= 500 and attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "HA returned %s on attempt %d, retrying",
                        response.status_code,
                        attempt + 1,
                    )
                    await self._backoff(attempt)
                    continue
                response.raise_for_status()
                return response
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "Transport error on attempt %d: %s — retrying",
                        attempt + 1,
                        exc,
                    )
                    await self._backoff(attempt)
                else:
                    raise
        # Should not be reachable, but keeps type checkers happy.
        raise last_exc  # type: ignore[misc]

    @staticmethod
    async def _backoff(attempt: int) -> None:
        delay = _BASE_DELAY * (2**attempt) + random.uniform(0, _JITTER_MAX)
        await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def list_entities(self) -> list[dict]:
        response = await self._request("GET", "/api/states")
        return response.json()

    async def list_scenes(self) -> list[dict]:
        response = await self._request("GET", "/api/states")
        return [e for e in response.json() if e.get("entity_id", "").startswith("scene.")]

    async def get_state(self, entity_id: str) -> dict:
        response = await self._request("GET", f"/api/states/{entity_id}")
        return response.json()

    async def list_areas(self) -> list[dict]:
        """Return a list of ``{"id": ..., "name": ...}`` dicts via the HA template endpoint.

        The ``areas()`` Jinja helper and ``area_name()`` function are standard
        Home Assistant template helpers available since HA 2021.x.
        """
        template = (
            "["
            "{%- for aid in areas() -%}"
            '{"id":"{{ aid }}","name":"{{ area_name(aid) }}"}'
            "{%- if not loop.last -%},{%- endif -%}"
            "{%- endfor -%}"
            "]"
        )
        response = await self._request("POST", "/api/template", json={"template": template})
        # The template endpoint returns plain text, even for JSON output.
        return json.loads(response.text)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def call_service(
        self,
        domain: str,
        service: str,
        target: dict | None = None,
        data: dict | None = None,
    ) -> dict:
        """Call a Home Assistant service and return the (possibly empty) response body.

        ``target`` may contain ``entity_id``, ``area_id``, or ``device_id``.
        ``data`` holds any extra service-specific payload.
        """
        body: dict = {}
        if target:
            body.update(target)
        if data:
            body.update(data)

        response = await self._request(
            "POST", f"/api/services/{domain}/{service}", json=body
        )
        # HA returns 200 with a list of affected states, or 200 with an empty body.
        content = response.text.strip()
        return {"result": json.loads(content) if content else []}


ha_client = HomeAssistantClient()
