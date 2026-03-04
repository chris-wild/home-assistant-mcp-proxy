"""FastAPI application exposing MCP-compatible tool endpoints."""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .audit import configure_logging, emit_tool_audit
from .config import settings
from .ha_client import ha_client
from .ha_tools import ToolExecutionError, describe_tools, execute_tool
from .schemas import ToolCall, ToolResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    logger.info("Starting Home Assistant MCP server")
    try:
        yield
    finally:
        logger.info("Shutting down Home Assistant MCP server")
        await ha_client.close()


app = FastAPI(
    title="Home Assistant MCP Proxy",
    version="0.3.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Audit middleware — attaches a correlation ID and emits one structured log
# record per request to /mcp/tools/call.
# ---------------------------------------------------------------------------

class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()

        response: Response = await call_next(request)

        # Only emit detailed audit records for tool-call requests.
        if request.url.path == "/mcp/tools/call":
            latency_ms = (time.perf_counter() - start) * 1000
            emit_tool_audit(
                request_id=request_id,
                tool=getattr(request.state, "tool_name", "unknown"),
                arguments=getattr(request.state, "tool_arguments", {}),
                decision=getattr(request.state, "policy_decision", "unknown"),
                ha_status=response.status_code,
                latency_ms=latency_ms,
            )

        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(AuditMiddleware)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "allowed_domains": settings.allowed_domains,
        "allowed_entities": settings.allowed_entities,
    }


@app.get("/mcp/tools")
async def list_tools() -> dict:
    return {"tools": describe_tools()}


@app.post("/mcp/tools/call", response_model=ToolResponse)
async def call_tool(call: ToolCall, request: Request) -> ToolResponse:
    # Stash metadata on the request state so the middleware can log it.
    request.state.tool_name = call.tool
    request.state.tool_arguments = call.arguments or {}
    request.state.policy_decision = "pending"

    try:
        result = await execute_tool(call)
        request.state.policy_decision = "allowed"
        return result
    except ToolExecutionError as exc:
        if exc.status_code == 403:
            request.state.policy_decision = "denied"
        elif exc.status_code == 409:
            request.state.policy_decision = "requires_confirmation"
        else:
            request.state.policy_decision = "error"
        logger.warning(
            "Tool execution error",
            extra={"tool": call.tool, "status_code": exc.status_code, "detail": exc.detail},
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
