"""FastAPI application — hosts the FastMCP server plus the /health endpoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .audit import configure_logging
from .config import settings
from .ha_client import ha_client
from .mcp_server import mcp

logger = logging.getLogger(__name__)

# Build the FastMCP ASGI app; all MCP traffic is handled at /mcp.
mcp_app = mcp.http_app(path="/mcp")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    logger.info("Starting Home Assistant MCP server")
    async with mcp_app.lifespan(app):
        try:
            yield
        finally:
            logger.info("Shutting down Home Assistant MCP server")
            await ha_client.close()


app = FastAPI(
    title="Home Assistant MCP Proxy",
    version="0.4.2",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Mount the FastMCP ASGI app at root so /mcp is reachable directly.
app.mount("/", mcp_app)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "allowed_domains": settings.allowed_domains,
        "allowed_entities": settings.allowed_entities,
    }
