#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$ROOT_DIR"

echo "[1/3] Compiling sources"
"$PYTHON_BIN" -m compileall app >/dev/null

echo "[2/3] Import check"
"$PYTHON_BIN" - <<'PY'
import importlib
import sys

module = importlib.import_module("app.main")
print("Loaded:", module.app.title)
PY

echo "[3/3] Uvicorn smoke test"
"$PYTHON_BIN" - <<'PY'
import asyncio
import contextlib
import socket
import httpx
import uvicorn

from app.main import app

async def run_smoke_test():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        host, port = sock.getsockname()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    async def _run_server():
        await server.serve()

    task = asyncio.create_task(_run_server())
    while not server.started:
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient() as client:
        response = await client.get(f"http://127.0.0.1:{port}/health", timeout=5.0)
        response.raise_for_status()
        print("Health:", response.json())

    server.should_exit = True
    await task

asyncio.run(run_smoke_test())
PY

echo "All verification steps passed."
