from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.api.routes.media import get_series
from backend.database import Base
from backend.database.models import Series, User
from backend.enums import UserRole


def _admin_user() -> User:
    return User(
        username="admin",
        password_hash="hash",
        role=UserRole.ADMIN,
        permissions=[],
    )


def test_get_series_watching_filter_returns_paginated_response() -> None:
    async def run() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_maker = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )

        async with session_maker() as db:
            admin = _admin_user()
            db.add(admin)
            db.add(
                Series(
                    title="Watching Series",
                    tmdb_id=7001,
                    last_viewed_at=datetime.now(UTC),
                    view_count=4,
                )
            )
            await db.commit()

            response = await get_series(
                admin,
                db,
                page=1,
                per_page=50,
                sort_by="title",
                sort_order="asc",
                search=None,
                candidates_only=False,
                arr_tag=None,
                decision_state="watching",
            )

            assert response.total == 1
            assert response.items[0].title == "Watching Series"
            assert response.items[0].status.decision is not None

        await engine.dispose()

    asyncio.run(run())