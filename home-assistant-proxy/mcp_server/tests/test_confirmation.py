"""Unit tests for the confirmation token store."""
from __future__ import annotations

import time

import pytest

from app.confirmation import CONFIRMATION_TTL_SECONDS, ConfirmationStore


@pytest.fixture()
def store():
    return ConfirmationStore()


def test_issue_and_consume_success(store):
    token = store.issue("lock", "lock", {"entity_id": "lock.front"}, None)
    assert isinstance(token, str) and len(token) > 0

    pending = store.consume(token, "lock", "lock")
    assert pending is not None
    assert pending.domain == "lock"
    assert pending.service == "lock"
    assert pending.target == {"entity_id": "lock.front"}


def test_consume_removes_token(store):
    token = store.issue("lock", "lock", None, None)
    store.consume(token, "lock", "lock")
    # Second consume must return None (token already removed).
    assert store.consume(token, "lock", "lock") is None


def test_wrong_domain_returns_none(store):
    token = store.issue("lock", "lock", None, None)
    result = store.consume(token, "light", "lock")
    assert result is None
    # Token still valid for the correct domain/service.
    assert store.consume(token, "lock", "lock") is not None


def test_wrong_service_returns_none(store):
    token = store.issue("lock", "lock", None, None)
    result = store.consume(token, "lock", "unlock")
    assert result is None


def test_unknown_token_returns_none(store):
    assert store.consume("not-a-real-token", "lock", "lock") is None


def test_expired_token_returns_none(store):
    token = store.issue("lock", "lock", None, None)
    # Manually expire the token.
    store._store[token].expires_at = time.monotonic() - 1
    assert store.consume(token, "lock", "lock") is None


def test_purge_removes_expired_on_issue(store):
    token = store.issue("lock", "lock", None, None)
    store._store[token].expires_at = time.monotonic() - 1
    # Issuing a new token triggers purge.
    store.issue("light", "turn_on", None, None)
    assert token not in store._store


def test_multiple_tokens_independent(store):
    t1 = store.issue("lock", "lock", None, None)
    t2 = store.issue("light", "turn_on", None, None)
    assert store.consume(t1, "lock", "lock") is not None
    assert store.consume(t2, "light", "turn_on") is not None
