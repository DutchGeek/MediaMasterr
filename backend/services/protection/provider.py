from __future__ import annotations

from abc import ABC, abstractmethod

from .models import (
    ProtectionItemRecord,
    ProtectionProviderDefinition,
    ProtectionProviderStatus,
    ProtectionRuleRecord,
    ProtectionStatistics,
)


class ProtectionProvider(ABC):
    """Common abstraction for all Protection providers."""

    provider_name: str

    @abstractmethod
    def getDefinition(self) -> ProtectionProviderDefinition:
        """Return provider metadata used to render authentication UI."""

    @abstractmethod
    async def connect(self) -> ProtectionProviderStatus:
        """Connect to provider and return current status."""

    @abstractmethod
    async def testConnection(self) -> ProtectionProviderStatus:
        """Validate provider connection details without mutating data."""

    @abstractmethod
    async def sync(self) -> ProtectionProviderStatus:
        """Trigger a provider synchronization run."""

    @abstractmethod
    async def getProtectedItems(self) -> list[ProtectionItemRecord]:
        """Return currently protected items."""

    @abstractmethod
    async def getProtectionRules(self) -> list[ProtectionRuleRecord]:
        """Return protection rules from this provider."""

    @abstractmethod
    async def getStatistics(self) -> ProtectionStatistics:
        """Return aggregate protection statistics."""
