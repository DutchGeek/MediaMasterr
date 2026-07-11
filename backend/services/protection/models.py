from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ProtectionProviderStatus:
    connected: bool
    provider: str
    connection_status: str
    base_url: str | None
    last_sync: str | None
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
