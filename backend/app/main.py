from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal

app = FastAPI(title="Modernization Platform — Pattern Catalog", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    database_status = "connected"
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database_status = "error"
    finally:
        db.close()

    return {"status": "ok", "database": database_status, "version": app.version}
