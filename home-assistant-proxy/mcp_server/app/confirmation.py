"""In-memory confirmation token store for high-risk service calls."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict

CONFIRMATION_TTL_SECONDS: int = 60


@dataclass
class PendingConfirmation:
    domain: str
    service: str
    target: dict | None
    data: dict | None
    expires_at: float  # monotonic timestamp


@dataclass
class ConfirmationStore:
    _store: Dict[str, PendingConfirmation] = field(default_factory=dict)

    def issue(
        self,
        domain: str,
        service: str,
        target: dict | None,
        data: dict | None,
    ) -> str:
        """Create and store a new confirmation token; return the token string."""
        self._purge_expired()
        token = str(uuid.uuid4())
        self._store[token] = PendingConfirmation(
            domain=domain,
            service=service,
            target=target,
            data=data,
            expires_at=time.monotonic() + CONFIRMATION_TTL_SECONDS,
        )
        return token

    def consume(
        self,
        token: str,
        domain: str,
        service: str,
    ) -> PendingConfirmation | None:
        """
        Validate and remove a token.

        Returns the ``PendingConfirmation`` if the token is valid, unexpired,
        and matches the given domain + service; otherwise returns ``None``.
        """
        self._purge_expired()
        pending = self._store.pop(token, None)
        if pending is None:
            return None
        if pending.domain != domain or pending.service != service:
            # Put it back — caller passed wrong domain/service
            self._store[token] = pending
            return None
        return pending

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._store.items() if v.expires_at <= now]
        for k in expired:
            del self._store[k]


# Module-level singleton shared across the application lifetime.
confirmation_store = ConfirmationStore()
