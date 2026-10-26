"""Editors installed on this machine, and opening a file in Visual Studio (app.editors)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import editors
from app.db import get_db
from app.errors import ErrorResponse, error

router = APIRouter(prefix="/api/editors", tags=["Editors"])


class Editor(BaseModel):
    id: str = Field(description="'vscode', or 'visual_studio:<installation>' for each Visual Studio installation.")
    kind: str = Field(description="'vscode' or 'visual_studio'.")
    label: str = Field(description="VS Code, or the installation's full name, such as 'Visual Studio Enterprise 2026'.")
    opens_at_line: bool
    installation: str | None = Field(default=None, description="Visual Studio only: the installation id to open with.")
    version: str | None = Field(default=None, description="Visual Studio only: its version, such as 18.0.11205.157.")


class EditorsOut(BaseModel):
    editors: list[Editor] = Field(description="The editors installed on the machine the platform runs on: VS Code, "
                                              "then each Visual Studio installation, newest first. Copying a file's "
                                              "path and line is always possible, and is not listed.")


class OpenIn(BaseModel):
    path: str = Field(description="The file's absolute path.")
    line: int = Field(default=1, ge=1)
    installation: str | None = Field(default=None, description="The Visual Studio installation to open it in, from "
                                                               "GET /api/editors; the newest when omitted.")


class OpenOut(BaseModel):
    opened: bool
    at_line: bool = Field(description="False when the file is open but the caret could not be moved to the line.")
    message: str


@router.get("", response_model=EditorsOut, summary="The editors installed on this machine", operation_id="list_editors")
def list_editors():
    return EditorsOut(editors=[Editor(**e) for e in editors.available()])


@router.post("/visual-studio/open", response_model=OpenOut, summary="Open a file in Visual Studio at a line",
             operation_id="open_in_visual_studio",
             responses={403: {"model": ErrorResponse, "description": "The path is outside every registered repository, "
                                                                      "conversion worktree and RUNS_DIR, or not a file."},
                        409: {"model": ErrorResponse, "description": "Visual Studio, or the installation named, is not offered on this machine."}})
def open_in_visual_studio(payload: OpenIn, db: Session = Depends(get_db)):
    """A browser cannot open a file in Visual Studio; the backend, on the same machine in the person's session, does.
    Only a file inside a registered repository, a conversion worktree or RUNS_DIR is opened."""
    try:
        return OpenOut(**editors.open_in_visual_studio(db, payload.path, payload.line, payload.installation))
    except editors.PathNotAllowed as exc:
        raise error(403, str(exc), field="path", code="PATH_NOT_ALLOWED") from exc
    except editors.EditorNotAvailable as exc:
        raise error(409, str(exc), code="EDITOR_NOT_AVAILABLE") from exc
