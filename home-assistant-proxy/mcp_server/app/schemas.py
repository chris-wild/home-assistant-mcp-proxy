"""Pydantic schemas for MCP tool inputs/outputs."""
from __future__ import annotations

from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    tool: str
    arguments: Dict = Field(default_factory=dict)


class EntityState(BaseModel):
    entity_id: str
    state: str
    attributes: Dict = Field(default_factory=dict)


class ToolResponse(BaseModel):
    status: str
    data: Optional[Union[Dict, List]] = None
    detail: Optional[str] = None


class ConfirmationRequiredResponse(BaseModel):
    """Structured body for 409 Confirmation Required responses."""

    status: str = "requires_confirmation"
    confirmation_token: str
    expires_in: int
    reason: str
