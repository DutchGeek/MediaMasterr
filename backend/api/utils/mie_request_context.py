from __future__ import annotations

from fastapi import Request

from backend.services.mie.request_context import MieRequestContext


def get_mie_request_context(request: Request) -> MieRequestContext:
    ctx = getattr(request.state, "mie_request_context", None)
    if isinstance(ctx, MieRequestContext):
        return ctx
    ctx = MieRequestContext()
    request.state.mie_request_context = ctx
    return ctx
