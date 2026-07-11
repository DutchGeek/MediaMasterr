from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ProtectionAuthFieldDefinition:
    name: str
    label: str
    required: bool
    secret: bool = False


@dataclass(slots=True)
class ProtectionAuthenticationDefinition:
    type: str
    fields: list[ProtectionAuthFieldDefinition]


@dataclass(slots=True)
class ProtectionProviderDefinition:
    provider: str
    display_name: str
    authentication: ProtectionAuthenticationDefinition


@dataclass(slots=True)
class ProtectionProviderStatus:
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


@dataclass(slots=True)
class ProtectionStatistics:
    connected: bool
    provider: str
    protected_files: int
    protected_size: int
    active_rules: int
    last_sync: str | None


@dataclass(slots=True)
class ProtectionRuleRecord:
    rule: str
    source: str
    protected_items: int
    status: str
    last_updated: str | None


@dataclass(slots=True)
class ProtectionItemRecord:
    path: str
    reason: str
    provider: str
    expiration: str | None
    status: str
