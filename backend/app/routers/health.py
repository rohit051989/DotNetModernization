from fastapi import APIRouter
from sqlalchemy import text

from app.db import SessionLocal

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict:
    database_status = "connected"
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database_status = "error"
    finally:
        db.close()

    return {"status": "ok", "database": database_status, "version": "0.1.0"}
