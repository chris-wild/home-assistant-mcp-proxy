# Home Assistant Proxy Architecture (with MCP)

## Current status
- **Done:** FastAPI MCP proxy runs locally with `/health`, `/mcp/tools`, `/mcp/tools/call`, and implements `ha_list_entities` + `ha_get_state` against the policy-aware HA client. Local smoke test (`mcp_server/scripts/local-verify.sh`) validates builds and endpoint health.
- **Blocked:** Packaging as a Home Assistant add-on (repo scaffold + Docker image) is waiting on the final MCP server scaffolding, policy engine wiring, and add-on configuration schema decisions.
- **Next steps:** (1) Scaffold the HA add-on repository and Docker packaging, (2) finish MCP server policy/validation modules with structured audit logging, (3) introduce the restricted `ha_call_service` tooling once allowlists + confirmation flow are codified.

## Milestone 2 status
- FastAPI MCP proxy exposes `/health`, `/mcp/tools`, and `/mcp/tools/call`.
- `ha_list_entities` and `ha_get_state` tools hit Home Assistant via the policy-aware async client.
- A local smoke-test script (`home-assistant-proxy/mcp_server/scripts/local-verify.sh`) compiles sources, verifies imports, and boots uvicorn long enough to hit `/health`.

### Quick verification
```bash
cd home-assistant-proxy/mcp_server
./scripts/local-verify.sh
```

## Checklist item 1: Plan to build and deploy a lightweight MCP server as a Home Assistant plugin

### Goal
Ship a lightweight, API-first MCP server as a Home Assistant add-on/plugin for HAOS/Home Assistant Green, with strict guardrails and a minimal tool surface for safe automation.

### Architecture (implementation-ready)
- **Runtime**: MCP server (Node.js or Python) running inside a Home Assistant add-on container.
- **Control path**: `Agent/Client -> MCP server -> Home Assistant REST/WebSocket API`.
- **Policy layer** (inside MCP server): schema validation, allow/deny rules, risk tiering, confirmation requirement for high-risk actions.
- **Audit layer**: structured logs for every tool call (request ID, tool args, decision, HA response, latency).
- **Optional maintenance path**: fixed-purpose maintenance tools only (no arbitrary shell), enabled only when needed.

### Packaging approach for HAOS / Home Assistant Green
- Build as a **Home Assistant Add-on** (Docker image + add-on `config.yaml`).
- Publish via a **custom add-on repository** (GitHub repo URL) to allow install/upgrade from HA UI.
- Add-on options (UI-configurable): HA URL/token (or supervisor auth proxy), allowed entities/domains, log level, confirmation policy.
- Use small base image (e.g., Python slim or distroless Node) and run as non-root where possible.
- Version with SemVer; ship immutable image tags and changelog per release.

### Minimal MCP tool surface (v1)
- `ha_get_state(entity_id)`
- `ha_list_entities(area_id?)`
- `ha_list_areas()`
- `ha_call_service(domain, service, target, data)` (**restricted to allowlisted low-risk domains/entities**)

Keep v1 intentionally small; expand only after telemetry and policy review.

### Deployment steps
1. Scaffold add-on repo (`repository.yaml`, add-on folder, Dockerfile, `config.yaml`).
2. Implement MCP server + HA client + JSON schema validation.
3. Add policy config (allowlist/denylist/risk tiers).
4. Build and publish image (GHCR or similar).
5. Add repository in Home Assistant -> install add-on -> configure options.
6. Start add-on and verify health endpoint + MCP handshake.
7. Run smoke tests (read tools, then low-risk write tool).
8. Enable for real workflows gradually (read-only first, then controlled writes).

### Testing plan
- **Unit tests**: tool schemas, policy decisions, argument normalization.
- **Integration tests**: mocked HA API responses + real HA dev instance.
- **E2E tests**: install add-on on HAOS/Green test device, run scripted MCP calls.
- **Security tests**: verify denied high-risk actions, rejected unknown fields, no policy bypass.
- **Resilience tests**: HA unavailable/timeouts/retries/circuit-breaker behavior.

### Rollback plan
- Keep previous known-good add-on image tag.
- If issues occur: downgrade add-on version from HA UI/repository tag.
- Switch MCP server to **read-only mode** via config flag during incident.
- Disable add-on entirely if needed; automations revert to existing HA-native paths.
- Preserve logs for incident review before re-enabling.

### Key risks and mitigations
- **Over-broad action permissions** -> strict allowlists + default deny.
- **High-risk actions executed without intent** -> explicit confirmation tokens for risky services.
- **Token/secret leakage** -> store in HA secrets/add-on options, redact logs.
- **Operational drift (new entities/services)** -> periodic policy review and test suite updates.
- **Add-on instability on low-power hardware** -> lightweight runtime, resource limits, health checks.

## Executive recommendation

Use **MCP as the primary control interface** between YesMan and Home Assistant, with a strict **API-first MCP server** in front of Home Assistant. Keep direct SSH **out of normal automation paths** and expose only a tiny set of auditable, restricted maintenance actions behind MCP when absolutely necessary.

In short:
- **YesMan ↔ MCP server ↔ Home Assistant APIs** for all routine control/state operations.
- **Optional MCP maintenance tools ↔ SSH wrapper** for break-glass/admin tasks only.
- No free-form remote shell available to YesMan.

This gives safer autonomy, better observability, and easier policy enforcement than direct HA API calls or direct SSH from the agent.

---

## Why MCP fits this integration

MCP gives a structured tool contract between an LLM agent (YesMan) and external systems. For Home Assistant, that means:

1. **Clear tool boundaries**
   - Explicit tools like `ha_get_entity_state`, `ha_call_service`, `ha_list_areas`.
   - Less prompt ambiguity vs “generate HTTP requests dynamically.”

2. **Policy + guardrails in one place**
   - Allowlist entities/domains/services.
   - Per-tool validation and risk classification.
   - Confirmation requirements for sensitive actions.

3. **Auditability by default**
   - Every call has: actor, tool, arguments, result, timestamp.
   - Much better than shell transcripts or ad hoc API logs.

4. **Portability and future-proofing**
   - YesMan can reuse a common tool protocol.
   - HA-specific logic stays in MCP server adapters.

5. **Least privilege made practical**
   - MCP server holds limited HA token scopes and service policies.
   - Agent never sees broad infrastructure credentials.

---

## Target architecture

```text
YesMan (LLM agent)
   |
   | MCP tool calls
   v
HA MCP Server (policy + validation + audit)
   |\
   | \-- Home Assistant REST/WebSocket API (primary path)
   |
   \---- Restricted maintenance tools (optional)
           -> controlled command runner
           -> SSH to host/container only for approved diagnostics/recovery
```

### Primary path (default)
- Use HA REST/WebSocket APIs for:
  - Reading entity states
  - Calling services
  - Triggering scripts/scenes/automations
  - Subscribing to selected events (if needed)

### Maintenance path (exception)
- Only for cases APIs cannot handle (e.g., integration stuck, supervised service check).
- Implement as **fixed-purpose MCP tools** (not arbitrary command execution).
- Example: `ha_maintenance_check_core_health`, `ha_maintenance_restart_addon_x`.

---

## API-first MCP server design

## 1) Tool surface design

Expose a minimal, composable tool set:

- `ha_get_state(entity_id)`
- `ha_get_states(filter?)`
- `ha_call_service(domain, service, target, data)`
- `ha_list_entities(area_id?)`
- `ha_list_areas()`
- `ha_get_history(entity_id, start, end)` (optional)

Prefer a small number of strongly validated tools over many overlapping tools.

## 2) Validation and normalization

- Normalize entity IDs and areas to canonical form.
- Validate types/ranges (brightness 0-255, temperature bounds, etc.).
- Reject unknown keys by default; permit only schema-allowed fields.
- Add idempotency keys where possible to avoid duplicate actions.

## 3) Policy engine

Implement policy before API dispatch:

- **Allowlist**: only permitted domains/entities/services.
- **Denylist**: high-risk actions (alarm disarm, door unlock, alarm panel code changes).
- **Contextual controls**:
  - time-of-day restrictions,
  - presence-aware constraints,
  - environment constraints (e.g., don’t run noisy actions overnight).
- **Risk tiers**:
  - low: read state, set lights
  - medium: thermostat mode changes, routines
  - high: locks/security/power-critical

High-risk tier should require explicit user confirmation token.

## 4) Observability and audit

Log all MCP requests/responses with:
- request ID / correlation ID
- user intent text (if available)
- tool name + arguments (redacted where needed)
- decision outcome (allowed/blocked/requires-confirmation)
- HA response status and latency

Ship logs to a queryable store and keep retention policy (e.g., 30-90 days).

## 5) Resilience patterns

- Retries with jitter for transient HA/API failures.
- Circuit breaker if HA unavailable.
- Graceful fallback responses (“cannot complete now, HA unreachable”).
- Timeouts per tool call, plus global budget per user request.

---

## Should SSH sit behind MCP?

**Yes, but only as restricted maintenance tools—not as a general control plane.**

### Recommended SSH stance

1. No generic `run_command` tool.
2. No interactive shell tool.
3. Provide only tightly scoped operations mapped to specific commands/scripts.
4. Run commands via non-privileged account where possible.
5. Use `sudo` for narrow whitelisted commands only (NOPASSWD for explicit list).
6. Capture stdout/stderr + exit code in audit logs.

### Good candidates for SSH-backed MCP tools

- Check HA process/add-on health
- Restart one known service/add-on
- Collect specific diagnostics bundle
- Validate disk space / DB growth thresholds

### Bad candidates

- Arbitrary shell execution
- File browsing/editing from agent prompts
- Package installation/upgrade without explicit human approval

---

## Pros / Cons of MCP-centric approach

## Pros
- Strong separation of concerns (agent vs system integration logic)
- Better safety through central policy enforcement
- Consistent auditing and incident review trail
- Easier to test deterministic behavior tool-by-tool
- Lower blast radius than direct SSH or unconstrained API use

## Cons
- Extra component to build/operate (MCP server)
- Initial schema/policy design effort can be significant
- Potential latency overhead vs direct API
- Requires ongoing policy maintenance as HA setup evolves

Mitigation: keep first version small (core tools + simple allowlists), then iterate.

---

## Phased rollout plan

## Phase 0 — Design and threat modeling (1-2 days)
- Define core use cases and disallowed actions.
- Classify risk tiers by entity/service.
- Identify minimum HA permissions and token scopes.
- Decide confirmation UX for high-risk actions.

Deliverables:
- Tool contract draft
- Policy matrix (allow/deny/confirm)
- Logging schema

## Phase 1 — Read-only MCP foundation (2-4 days)
- Implement MCP server skeleton.
- Add read-only tools: state/entity/area listing.
- Add auth, input validation, basic audit logging.
- Integrate YesMan in read-only mode.

Gate to next phase:
- Stable read behavior under normal load
- No policy bypasses in tests

## Phase 2 — Low-risk write controls (3-5 days)
- Add controlled `ha_call_service` for low-risk domains (lights/media scenes).
- Enforce per-domain/entity allowlists.
- Add retries/timeouts and improved error mapping.

Gate:
- Action success/error rates acceptable
- Full traceability from intent to HA result

## Phase 3 — Confirmation + high-risk workflow (2-4 days)
- Add explicit user confirmation flow for high-risk actions.
- Implement expiring confirmation tokens.
- Block execution without valid confirmation artifacts.

Gate:
- Security acceptance tests pass (no high-risk action without confirmation)

## Phase 4 — Restricted maintenance tools over SSH (optional, 2-4 days)
- Add 2-3 fixed-purpose maintenance MCP tools only.
- Back them with reviewed scripts/commands.
- Harden host access, sudoers whitelist, and audit exports.

Gate:
- Break-glass tasks demonstrably useful
- No arbitrary command path exposed

## Phase 5 — Hardening and operations (ongoing)
- Alerting on denied high-risk attempts and repeated failures.
- Periodic policy review as HA entities/services change.
- Chaos tests for HA unavailability and partial failure.

---

## Implementation checklist

- [ ] MCP server scaffold created
- [ ] HA API client module with retries/timeouts
- [ ] JSON schema validation for all tools
- [ ] Policy engine (allow/deny/confirm tiers)
- [ ] Structured audit logs + correlation IDs
- [ ] Redaction rules for sensitive fields
- [ ] Read-only tools implemented and tested
- [ ] Low-risk write tool implemented with allowlists
- [ ] Confirmation workflow for high-risk actions
- [ ] Optional SSH maintenance tools (fixed-purpose only)
- [ ] Runbooks for incidents and rollback

---

## Final position

For YesMan ↔ Home Assistant integration, **MCP should be the control plane**.

Use an **API-first MCP server** for normal operations and policy enforcement. Treat SSH as a **restricted maintenance backstop** exposed only through narrowly scoped MCP tools. This balances autonomy with safety and gives a clean path from prototype to production-grade reliability.