from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.services.memory3d_service import (
    Memory3DEngineUnavailable,
    Memory3DValidationError,
    get_memory3d_service,
)


router = APIRouter()


class ModelNameUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


def service():
    return get_memory3d_service()


@router.get("/status")
async def memory3d_status(_: Dict[str, Any] = Depends(get_current_user)):
    return service().status()


@router.get("/gallery")
async def memory3d_gallery(_: Dict[str, Any] = Depends(get_current_user)):
    return service().gallery()


@router.post("/generate")
async def memory3d_generate(
    file: list[UploadFile] = File(...),
    _: Dict[str, Any] = Depends(get_current_user),
):
    tasks = []
    memory_service = service()
    for upload in file:
        content = await upload.read()
        try:
            tasks.append(memory_service.enqueue_upload(upload.filename or "memory.jpg", content))
        except Memory3DEngineUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        except Memory3DValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "success": True,
        "message": f"{len(tasks)} tasks queued",
        "tasks": tasks,
    }


@router.get("/tasks")
async def memory3d_tasks(_: Dict[str, Any] = Depends(get_current_user)):
    tasks, has_active = service().list_tasks()
    return {"tasks": tasks, "has_active": has_active}


@router.post("/tasks/{task_id}/cancel")
async def memory3d_cancel_task(task_id: str, _: Dict[str, Any] = Depends(get_current_user)):
    try:
        return service().cancel_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/models/{item_id}")
async def memory3d_delete_model(item_id: str, _: Dict[str, Any] = Depends(get_current_user)):
    try:
        service().delete_model(item_id)
    except Memory3DValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"success": True}


@router.patch("/models/{item_id}")
async def memory3d_update_model(
    item_id: str,
    payload: ModelNameUpdate,
    _: Dict[str, Any] = Depends(get_current_user),
):
    try:
        return service().set_model_name(item_id, payload.name)
    except Memory3DValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found") from exc


@router.get("/files/{filename}")
async def memory3d_model_file(filename: str, _: Dict[str, Any] = Depends(get_current_user)):
    try:
        path = service().resolve_output_file(filename)
    except Memory3DValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model file not found") from exc
    media_type = "application/octet-stream"
    return Response(
        content=path.read_bytes(),
        media_type=media_type,
        headers={
            "Content-Length": str(path.stat().st_size),
            "Content-Disposition": f'attachment; filename="{path.name}"',
        },
    )


@router.get("/original/{item_id}")
async def memory3d_original(item_id: str, _: Dict[str, Any] = Depends(get_current_user)):
    try:
        path = service().resolve_original(item_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Original image not found") from exc
    return FileResponse(path, filename=path.name)


@router.get("/thumbnail/{item_id}")
async def memory3d_thumbnail(item_id: str, _: Dict[str, Any] = Depends(get_current_user)):
    try:
        path = service().resolve_thumbnail(item_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail not found") from exc
    return FileResponse(path, media_type="image/jpeg", filename=path.name)
