from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.db import SessionLocal

router = APIRouter(prefix="/api", tags=["Health"])


class HealthStatus(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"status": "ok", "database": "connected", "version": "0.3.0"}]}
    )

    status: Literal["ok"] = Field(description="Always 'ok' — the process is up and answering requests.")
    database: Literal["connected", "error"] = Field(
        description="Result of a real `SELECT 1` against the database, checked on every call."
    )
    version: str = Field(description="The running API version.")


@router.get(
    "/health",
    response_model=HealthStatus,
    summary="Check API and database health",
    response_description="The API is up. `database` reflects whether it can currently reach Postgres.",
    tags=["Health"],
    operation_id="get_health",
)
def health() -> HealthStatus:
    """
    Always returns **200**, even when the database is unreachable — `database`
    switches to `"error"` instead, so the UI can render a degraded state
    rather than treating this endpoint itself as down.
    """
    database_status = "connected"
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database_status = "error"
    finally:
        db.close()

    return HealthStatus(status="ok", database=database_status, version="0.3.0")
