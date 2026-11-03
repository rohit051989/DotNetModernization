"""Whether a repository's machine can build and test its baseline on the repository's own frameworks
(36-COPILOT-ENHANCED-CONVERSION.md Part P; app.toolchain). Read by everyone: on the machine the repository is
registered on, checked now (and recorded when it changed); elsewhere, as that machine last recorded it.
"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.toolchain import service

router = APIRouter(prefix="/api", tags=["Toolchain"])


class ToolchainItemOut(BaseModel):
    kind: str = Field(description="sdk, runtime, reference-assemblies, netfx-runtime or web-targets.")
    label: str = Field(description="What it is, in plain words: \"the .NET 8 runtime (x64)\".")
    for_: str = Field(alias="for", description="build: the baseline cannot build without it; test: its tests cannot run.")
    projects: list[str] = Field(description="The projects in scope that need it, by path.")
    detail: str = Field(description="What this machine has instead, and where.")

    model_config = {"populate_by_name": True}


class ToolchainOut(BaseModel):
    checked: bool = Field(description="False before the repository's machine has ever checked.")
    ready: bool | None = None
    summary: str
    missing: list[ToolchainItemOut] = []
    present: list[ToolchainItemOut] = []
    host: str | None = Field(None, description="The machine that checked.")
    checked_at: str | None = None
    held_on: str | None = Field(None, description="Set when the repository is registered on another machine: what is "
                                                  "shown is what that machine last found.")


@router.get(
    "/repositories/{repository_id}/toolchain",
    response_model=ToolchainOut,
    response_model_by_alias=True,
    summary="Whether the repository's machine has the runtimes and build tools its baseline needs",
    operation_id="get_repository_toolchain",
    responses={404: {"model": ErrorResponse, "description": "No repository exists with this id."}},
)
def get_repository_toolchain(repository_id: uuid.UUID, db: Session = Depends(get_db)):
    from app.results import held

    repository = db.get(models.Repository, repository_id)
    if repository is None or repository.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    result, row, _ = service.current(db, repository)
    held_on = held.repository_where(db, repository) if held.elsewhere(repository.registered_host) else None
    if result is None:
        return ToolchainOut(checked=False, held_on=held_on,
                            summary="Not checked yet: the machine it is registered on checks after its next discovery.")
    return ToolchainOut(checked=True, ready=result["ready"], summary=result["summary"],
                        missing=[ToolchainItemOut(**m) for m in result["missing"]],
                        present=[ToolchainItemOut(**p) for p in result["present"]],
                        host=row.host if row else None,
                        checked_at=row.checked_at.isoformat(timespec="seconds") if row else None, held_on=held_on)
