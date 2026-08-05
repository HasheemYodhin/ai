"""
CRUD + run-log API for user-configured agent hooks (dabba.utils.hook_manager).

Mounted at /v1/hooks — used by the web frontend's Hooks settings page and
by the same events the CLI eventually wires up too.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dabba.utils.hook_manager import VALID_EVENTS, get_hook_manager


class CreateHookRequest(BaseModel):
    event: str
    command: str
    matcher: str = ""
    timeout: int = 30
    enabled: bool = True


class UpdateHookRequest(BaseModel):
    event: Optional[str] = None
    command: Optional[str] = None
    matcher: Optional[str] = None
    timeout: Optional[int] = None
    enabled: Optional[bool] = None


def create_hooks_router() -> APIRouter:
    router = APIRouter(prefix="/v1/hooks", tags=["hooks"])
    manager = get_hook_manager()

    @router.get("")
    async def list_hooks():
        return {"hooks": manager.list(), "events": sorted(VALID_EVENTS)}

    @router.post("", status_code=201)
    async def create_hook(req: CreateHookRequest):
        try:
            return manager.create(
                event=req.event,
                command=req.command,
                matcher=req.matcher,
                timeout=req.timeout,
                enabled=req.enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/{hook_id}")
    async def update_hook(hook_id: str, req: UpdateHookRequest):
        try:
            return manager.update(hook_id, req.model_dump(exclude_unset=True))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/{hook_id}", status_code=204)
    async def delete_hook(hook_id: str):
        if not manager.delete(hook_id):
            raise HTTPException(status_code=404, detail="Unknown hook id")

    @router.get("/runs")
    async def recent_runs(limit: int = 50):
        return {"runs": manager.recent_runs(limit)}

    return router
