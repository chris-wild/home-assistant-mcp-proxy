"""Unit tests for the policy engine."""
from __future__ import annotations

import pytest

from app.policy import PolicyDecision, evaluate_entity, evaluate_service


# ---------------------------------------------------------------------------
# evaluate_entity — open allowlists (empty = allow all)
# ---------------------------------------------------------------------------

def test_entity_open_allowlist_allows(default_settings):
    result = evaluate_entity(entity_id="light.kitchen", domain="light")
    assert result.decision == PolicyDecision.ALLOW


def test_entity_no_args_allows(default_settings):
    result = evaluate_entity()
    assert result.decision == PolicyDecision.ALLOW


# ---------------------------------------------------------------------------
# evaluate_entity — restricted allowlists
# ---------------------------------------------------------------------------

def test_entity_in_allowlist_allows(restricted_settings):
    result = evaluate_entity(entity_id="light.kitchen", domain="light")
    assert result.decision == PolicyDecision.ALLOW


def test_entity_not_in_entity_allowlist_denies(restricted_settings):
    result = evaluate_entity(entity_id="light.bathroom", domain="light")
    assert result.decision == PolicyDecision.DENY
    assert "allowlist" in result.reason.lower()


def test_domain_not_in_domain_allowlist_denies(restricted_settings):
    result = evaluate_entity(entity_id="switch.fan", domain="switch")
    assert result.decision == PolicyDecision.DENY


def test_confirmation_domain_requires_confirmation(restricted_settings):
    result = evaluate_entity(entity_id="lock.front_door", domain="lock")
    assert result.decision == PolicyDecision.REQUIRE_CONFIRMATION
    assert result.reason is not None


# ---------------------------------------------------------------------------
# evaluate_service
# ---------------------------------------------------------------------------

def test_service_allowed_domain(restricted_settings):
    result = evaluate_service(domain="light", service="turn_on")
    assert result.decision == PolicyDecision.ALLOW


def test_service_denied_domain(restricted_settings):
    result = evaluate_service(domain="switch", service="turn_on")
    assert result.decision == PolicyDecision.DENY


def test_service_confirmation_domain(restricted_settings):
    result = evaluate_service(domain="lock", service="lock")
    assert result.decision == PolicyDecision.REQUIRE_CONFIRMATION


def test_service_open_allowlist(default_settings):
    # When allowed_domains is empty, everything is allowed.
    result = evaluate_service(domain="anything", service="do_stuff")
    assert result.decision == PolicyDecision.ALLOW


def test_policy_decision_is_enum():
    """PolicyDecision members must be proper enum members."""
    assert isinstance(PolicyDecision.ALLOW, PolicyDecision)
    assert PolicyDecision.ALLOW == "allow"
