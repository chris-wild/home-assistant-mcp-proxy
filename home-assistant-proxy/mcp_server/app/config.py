"""Configuration helpers for the MCP server."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Settings:
    home_assistant_url: str = "http://supervisor/core"
    access_token: str | None = None
    allowed_entities: List[str] = field(default_factory=list)
    allowed_domains: List[str] = field(default_factory=lambda: ["light"])
    confirmation_domains: List[str] = field(default_factory=list)
    log_level: str = os.getenv("MCP_LOG_LEVEL", "info")

    @staticmethod
    def _parse_list(raw: str | None) -> List[str]:
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(item) for item in data]
        except json.JSONDecodeError:
            pass
        return [item.strip() for item in raw.split(",") if item.strip()]

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            home_assistant_url=os.getenv("MCP_HOME_ASSISTANT_URL", "http://supervisor/core"),
            access_token=os.getenv("MCP_HOME_ASSISTANT_TOKEN"),
            allowed_entities=cls._parse_list(os.getenv("MCP_ALLOWED_ENTITIES")),
            allowed_domains=cls._parse_list(os.getenv("MCP_ALLOWED_DOMAINS")) or ["light"],
            confirmation_domains=cls._parse_list(os.getenv("MCP_CONFIRMATION_DOMAINS")),
            log_level=os.getenv("MCP_LOG_LEVEL", "info"),
        )


settings = Settings.load()
