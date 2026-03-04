"""Shared pytest fixtures."""
from __future__ import annotations

import pytest

from app.config import Settings


@pytest.fixture()
def default_settings(monkeypatch):
    """Return a Settings instance with open (empty) allowlists."""
    s = Settings(
        home_assistant_url="http://localhost",
        access_token=None,
        allowed_entities=[],
        allowed_domains=[],
        confirmation_domains=[],
        log_level="debug",
    )
    monkeypatch.setattr("app.policy.settings", s)
    monkeypatch.setattr("app.ha_tools.ha_client", None)  # guard: tests must mock ha_client
    return s


@pytest.fixture()
def restricted_settings(monkeypatch):
    """Settings with a narrow allowlist and lock in confirmation tier."""
    s = Settings(
        home_assistant_url="http://localhost",
        access_token=None,
        allowed_entities=["light.kitchen"],
        allowed_domains=["light"],
        confirmation_domains=["lock"],
        log_level="debug",
    )
    monkeypatch.setattr("app.policy.settings", s)
    return s
