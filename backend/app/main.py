from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.routers import (
    catalog,
    decisions,
    engagement_patterns,
    engagements,
    health,
    patterns,
    target_states,
    workflow_executions,
    workflow_jobs,
    workflow_steps,
)

app = FastAPI(title="Modernization Platform — Pattern Catalog", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = [str(part) for part in err["loc"] if part not in ("body", "query", "path")]
        errors.append({"field": ".".join(loc) or "__root__", "message": err["msg"]})
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    return JSONResponse(
        status_code=409,
        content={"detail": f"Database constraint violation: {exc.orig}"},
    )


app.include_router(health.router)
app.include_router(patterns.router)
app.include_router(target_states.router)
app.include_router(engagements.router)
app.include_router(engagement_patterns.router)
app.include_router(decisions.router)
app.include_router(catalog.router)
app.include_router(workflow_steps.router)
app.include_router(workflow_jobs.router)
app.include_router(workflow_executions.router)
