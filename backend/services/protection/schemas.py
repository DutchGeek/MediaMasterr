from __future__ import annotations

from pydantic import BaseModel, Field


class ProtectionConfigRequest(BaseModel):
    provider: str = Field(default="reclaimerr")
    base_url: str = Field(default="")
    api_key: str = Field(default="")
    enabled: bool = Field(default=True)


class ProtectionConfigResponse(BaseModel):
    provider: str
    base_url: str
    api_key_configured: bool
    enabled: bool


class ProtectionStatusResponse(BaseModel):
    connected: bool
    provider: str
    connection_status: str
    base_url: str | None
    last_sync: str | None
    message: str | None


class ProtectionStatsResponse(BaseModel):
    connected: bool
    provider: str
    protected_files: int
    protected_size: int
    active_rules: int
    last_sync: str | None


class ProtectionRuleResponse(BaseModel):
    rule: str
    source: str
    protected_items: int
    status: str
    last_updated: str | None


class ProtectionItemResponse(BaseModel):
    path: str
    reason: str
    provider: str
    expiration: str | None
    status: str
