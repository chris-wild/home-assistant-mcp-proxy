"""Structured JSON audit logging for MCP tool calls."""
from __future__ import annotations

import logging
import logging.config
from typing import Any

from pythonjsonlogger import jsonlogger  # type: ignore[import-untyped]

# Keys whose values are replaced before writing to logs.
_REDACTED_KEYS = frozenset(
    {"token", "confirmation_token", "password", "access_token", "authorization", "secret"}
)

_AUDIT_LOGGER = logging.getLogger("mcp.audit")


def configure_logging(log_level: str = "info") -> None:
    """Set up root and audit loggers to emit JSON records."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric_level)


def _redact(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *arguments* with sensitive values replaced."""
    return {
        k: "<redacted>" if k.lower() in _REDACTED_KEYS else v
        for k, v in arguments.items()
    }


def emit_tool_audit(
    *,
    request_id: str,
    tool: str,
    arguments: dict[str, Any],
    decision: str,
    ha_status: int | None,
    latency_ms: float,
) -> None:
    """Emit one structured audit record per tool invocation."""
    _AUDIT_LOGGER.info(
        "tool_call",
        extra={
            "request_id": request_id,
            "tool": tool,
            "arguments": _redact(arguments),
            "decision": decision,
            "ha_status": ha_status,
            "latency_ms": round(latency_ms, 2),
        },
    )
