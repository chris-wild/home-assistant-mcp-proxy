"""Policy evaluation for MCP tools."""
from __future__ import annotations

import enum
from dataclasses import dataclass

from .config import settings


class PolicyDecision(str, enum.Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_CONFIRMATION = "require_confirmation"


@dataclass
class PolicyResult:
    decision: PolicyDecision
    reason: str | None = None


def evaluate_entity(entity_id: str | None = None, domain: str | None = None) -> PolicyResult:
    """Evaluate read-access policy for a single entity.

    Precedence:
      1. confirmation_domains — implicitly allowed but gated; checked first so a domain
         listed in both allowed_domains and confirmation_domains isn't accidentally denied.
      2. allowed_entities allowlist (if non-empty).
      3. allowed_domains allowlist (if non-empty).
      4. Default ALLOW.
    """
    # Confirmation domains are treated as implicitly permitted (just require extra step).
    if domain and domain in settings.confirmation_domains:
        return PolicyResult(PolicyDecision.REQUIRE_CONFIRMATION, f"Domain '{domain}' requires confirmation")

    if entity_id and settings.allowed_entities and entity_id not in settings.allowed_entities:
        return PolicyResult(PolicyDecision.DENY, "Entity not in allowlist")

    if domain and settings.allowed_domains and domain not in settings.allowed_domains:
        return PolicyResult(PolicyDecision.DENY, "Domain not in allowlist")

    return PolicyResult(PolicyDecision.ALLOW)


def evaluate_service(domain: str, service: str | None = None) -> PolicyResult:
    """Evaluate write-access policy for a service call.

    Confirmation domains are checked before the allowlist for the same reason as above.
    """
    # Confirmation check first — these domains are allowed but gated.
    if domain in settings.confirmation_domains:
        svc_label = f"{domain}.{service}" if service else domain
        return PolicyResult(
            PolicyDecision.REQUIRE_CONFIRMATION,
            f"Service '{svc_label}' requires explicit confirmation",
        )

    if settings.allowed_domains and domain not in settings.allowed_domains:
        return PolicyResult(PolicyDecision.DENY, f"Domain '{domain}' not in allowed_domains")

    return PolicyResult(PolicyDecision.ALLOW)
