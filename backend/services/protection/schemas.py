from __future__ import annotations

from pydantic import BaseModel, Field


class ProtectionAuthFieldDefinitionResponse(BaseModel):
    name: str
    label: str
    required: bool
    secret: bool = False


class ProtectionAuthenticationDefinitionResponse(BaseModel):
    type: str
    fields: list[ProtectionAuthFieldDefinitionResponse]


class ProtectionProviderDefinitionResponse(BaseModel):
    provider: str
    display_name: str
    authentication: ProtectionAuthenticationDefinitionResponse


class ProtectionConfigRequest(BaseModel):
    provider: str = Field(default="reclaimerr")
    auth_method: str = Field(default="web_login")
    base_url: str = Field(default="")
    username: str = Field(default="")
    password: str = Field(default="")
    enabled: bool = Field(default=True)


class ProtectionConfigResponse(BaseModel):
    provider: str
    auth_method: str
    base_url: str
    username: str
    password_configured: bool
    configured_auth_fields: list[str]
    enabled: bool


class ProtectionStatusResponse(BaseModel):
    connected: bool
    authenticated: bool
    provider: str
    auth_method: str
    connection_status: str
    authentication_status: str
    base_url: str | None
    provider_version: str | None
    last_login: str | None
    last_sync: str | None
    capabilities: list[str]
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
