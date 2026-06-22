from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.api.routes.protected import (
    delete_protection_entry,
    update_protection_duration,
)
from backend.database import Base
from backend.database.models import ProtectedMedia, ReclaimRule, Series, User
from backend.enums import MediaType, UserRole
from backend.models.protect import UpdateProtectionDurationRequest


def test_rule_managed_protection_rejects_direct_update_and_delete() -> None:
    async def run() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_maker = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

        async with session_maker() as db:
            admin = User(
                username="admin",
                password_hash="hash",
                role=UserRole.ADMIN,
                permissions=[],
            )
            rule = ReclaimRule(
                name="Protect series",
                media_type=MediaType.SERIES,
                enabled=True,
                target_scope="series",
                definition={
                    "version": 1,
                    "root": {
                        "type": "group",
                        "op": "and",
                        "children": [
                            {
                                "type": "condition",
                                "field": "media.size",
                                "operator": "greater_than",
                                "value": 0,
                            }
                        ],
                    },
                },
                action={"outcome": "protect"},
            )
            series = Series(title="Managed Series", tmdb_id=90001, size=100)
            db.add_all([admin, rule, series])
            await db.flush()
            entry = ProtectedMedia(
                media_type=MediaType.SERIES,
                series_id=series.id,
                protected_by_user_id=None,
                source="rule",
                source_rule_id=rule.id,
                reason="Managed by rule",
            )
            db.add(entry)
            await db.commit()

            with pytest.raises(HTTPException) as update_error:
                await update_protection_duration(
                    entry.id,
                    UpdateProtectionDurationRequest(duration_days=30),
                    admin,
                    db,
                )
            assert update_error.value.status_code == 409

            with pytest.raises(HTTPException) as delete_error:
                await delete_protection_entry(entry.id, admin, db)
            assert delete_error.value.status_code == 409

        await engine.dispose()

    asyncio.run(run())
