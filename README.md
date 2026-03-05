# Home Assistant MCP Proxy

A lightweight MCP server that sits in front of Home Assistant, giving Openclaw agents safe, auditable, policy-enforced access to your home.

Rather than letting an agent call the Home Assistant API directly, all requests flow through this server which enforces allowlists, blocks high-risk actions, requires explicit confirmation tokens for sensitive operations, and emits structured audit logs for every call.

---

## Architecture

```
Openclaw agent  (or any MCP client)
      |
      | MCP / Streamable HTTP  → http://<ha-ip>:8745/mcp
      v
HA MCP Proxy  ──  policy engine  ──  audit log
      |
      v
Home Assistant REST API
```

Runs as a **Home Assistant Add-on** — installed directly from the HA UI, no separate infrastructure needed.

---

## Installation

1. In Home Assistant go to **Settings → Apps**
2. Click the **Install app** button (bottom right)
3. Tap the **⋮ menu** (top right) and select **Repositories**
4. Enter the repository URL and click **Add**:
   ```
   https://github.com/chris-wild/home-assistant-mcp-proxy
   ```
5. Find **Home Assistant MCP Proxy** in the store and click **Install**
6. Go to the **Configuration** tab and fill in your settings (see below)
7. Start the add-on — it listens on port **8745**

Verify it's running:
```bash
curl http://<your-ha-ip>:8745/health
```

Connect any MCP client to:
```
http://<your-ha-ip>:8745/mcp
```

---

## Known Issues

### Re-installation doesn't pick up the latest version 🐛

When updating to a new version, simply uninstalling and reinstalling the add-on is **not sufficient** — HA caches the repository and will reinstall the old image.

To force a clean install:
1. Uninstall the add-on (tick **Delete all data** if prompted)
2. Go to **Settings → Apps → ⋮ menu → Repositories** and remove the repository
3. Re-add the repository URL and reinstall the add-on

---

## Configuration

Set these options in the add-on Configuration tab:

| Option | Default | Description |
|---|---|---|
| `access_token` | _(empty)_ | Long-lived HA access token (create one at **Profile → Security**) |
| `home_assistant_url` | `http://supervisor/core` | HA URL — leave as default when running as an add-on |
| `allowed_domains` | `["light"]` | Domains the agent is allowed to read or control |
| `allowed_entities` | `[]` | Specific entity allowlist — leave empty to allow all entities within permitted domains |
| `confirmation_required_for` | `["lock"]` | Domains that require a confirmation token before any service call executes |
| `log_level` | `info` | Logging verbosity: `debug`, `info`, `warning`, `error`, `critical` |

---

## Tools

### `ha_list_entities`
List all policy-approved entities, optionally filtered by domain.

```json
{ "domain": "light" }
```

### `ha_get_state`
Fetch the current state of a single entity.

```json
{ "entity_id": "light.kitchen" }
```

### `ha_list_areas`
List all Home Assistant areas (rooms/zones) with their IDs and names.

```json
{}
```

### `ha_list_scenes`
List all policy-approved Home Assistant scenes.

```json
{}
```

### `ha_call_service`
Call a Home Assistant service. Subject to domain allowlists and confirmation requirements.

```json
{
  "domain": "light",
  "service": "turn_on",
  "target": { "entity_id": "light.kitchen" },
  "data": { "brightness": 200 }
}
```

For high-risk domains (e.g. `lock`), the first call returns a `409` with a `confirmation_token`. Re-send the same call with that token to execute:

```json
{
  "domain": "lock",
  "service": "lock",
  "target": { "entity_id": "lock.front_door" },
  "confirmation_token": "<token from 409 response>"
}
```

Confirmation tokens expire after **60 seconds**.

---

## Policy engine

Every tool call is evaluated before hitting Home Assistant:

| Decision | Behaviour |
|---|---|
| **Allow** | Domain/entity is in the allowlist — request proceeds |
| **Deny** | Domain/entity not in any allowlist — 403 returned, nothing called |
| **Require confirmation** | Domain is in `confirmation_required_for` — 409 returned with a short-lived token; caller must re-submit with the token to execute |

`confirmation_required_for` domains take precedence over `allowed_domains` — they are implicitly permitted but gated, so you don't need to list them in both.

---

## Audit logging

Every tool call emits a structured JSON log record:

```json
{
  "asctime": "2026-03-04T13:02:39",
  "levelname": "INFO",
  "name": "mcp.audit",
  "message": "tool_call",
  "request_id": "3f9a1b2c-...",
  "tool": "ha_call_service",
  "arguments": { "domain": "light", "service": "turn_on" },
  "decision": "allowed",
  "ha_status": 200,
  "latency_ms": 42.1
}
```

Sensitive argument keys (`token`, `access_token`, `password`, etc.) are automatically redacted.

---

## Development

```bash
cd home-assistant-proxy/mcp_server

# Create a virtual environment and install deps
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # unit-test deps (no mcp)

# Run unit tests
.venv/bin/python -m pytest tests/ -v

# Local smoke test — compiles, imports, boots uvicorn, hits /health
# (requires Python 3.10+ because of the mcp dependency)
pip install -r requirements.txt
PYTHON_BIN=.venv/bin/python3 ./scripts/local-verify.sh

# Interactive MCP inspector (opens http://localhost:6274)
fastmcp dev app/mcp_server.py
```

---

## Roadmap

- **More tools** — `ha_activate_scene`, `ha_trigger_automation`, `ha_get_history`
- **Area filtering** — `ha_list_entities(area_id=...)`
- **API authentication** — bearer token on the proxy endpoint itself
- **Supervisor token** — use the injected `SUPERVISOR_TOKEN` instead of a manually configured access token
- **Live HA health check** — `/health` that actually pings the HA API
