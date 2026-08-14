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

app = FastAPI(
    title="Modernization Platform API",
    version="0.3.0",
    description=(
        "Control plane for .NET legacy modernization at fleet scale: the reusable "
        "pattern catalog, engagement-scoped decisions, and the lifecycle "
        "orchestration engine.\n\n"
        "**Errors.** Every non-2xx response — 404, 409, 422, 501 — uses one shape, "
        "documented once as the `ErrorResponse` component:\n\n"
        '```json\n{"detail": [{"field": "clone_url", "message": "...", "code": "EMBEDDED_CREDENTIALS"}]}\n```\n\n'
        "`field` is null when the error isn't about one field (a 404, or a "
        "conflict spanning several records). `code` is a short machine-readable "
        "slug for callers that want to branch on it instead of parsing `message`."
    ),
    openapi_tags=[
        {"name": "Health", "description": "Liveness and database connectivity check."},
        {
            "name": "Patterns",
            "description": (
                "Master catalog pattern definitions — the reusable, client-agnostic IP "
                "shared by every engagement. Edited in one place only; a change here is "
                "visible to every engagement that uses the client catalog."
            ),
        },
        {
            "name": "Target States",
            "description": (
                "Master catalog modernization destinations for a pattern. Client-agnostic, "
                "like patterns — an engagement's specific choice among them is recorded "
                "separately, as a decision record."
            ),
        },
        {
            "name": "Engagements",
            "description": (
                "One client program. Owns nothing in the master catalog; an engagement "
                "consumes it through the client catalog and records its own decisions."
            ),
        },
        {
            "name": "Client Catalog",
            "description": (
                "The master catalog as seen and acted on by one engagement: master pattern "
                "data merged with that engagement's scope overlay (active/deferred, "
                "client-scoped soft delete via `engagement_patterns`). Editing here never "
                "changes the master catalog or any other engagement — see "
                "02-DATA-MODEL.md's master-vs-client separation. These routes never write "
                "to `patterns` or `target_state_options`."
            ),
        },
        {
            "name": "Decisions",
            "description": (
                "An engagement's chosen (or in-progress) target state option for a pattern. "
                "At most one live decision per (engagement, pattern) — enforced by a partial "
                "unique index; superseding one frees the slot for a new decision without "
                "destroying the history."
            ),
        },
        {
            "name": "Catalog",
            "description": (
                "Deterministic export/import of the master catalog — and, optionally, one "
                "engagement's overlay and decisions — as versionable, diffable JSON, so it "
                "can be committed to git and reviewed as a pull request."
            ),
        },
        {
            "name": "Workflow Steps",
            "description": (
                "The registry of known lifecycle steps and their contracts (`consumes` / "
                "`produces` artifact types, adapter configuration). A step must be "
                "registered here before any job definition can reference it."
            ),
        },
        {
            "name": "Workflow Jobs",
            "description": (
                "Job **definitions** — the declarative YAML describing a job's steps and "
                "flow, plus launching new runs from them. A definition is static and "
                "versioned; launching it produces a run — see Workflow Executions."
            ),
        },
        {
            "name": "Workflow Executions",
            "description": (
                "Job **runs**. A job instance is a job name plus one specific set of "
                "parameters; an execution is one attempt at that instance. Re-launching "
                "with identical parameters resumes the same instance as a new execution "
                "rather than starting over."
            ),
        },
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """FastAPI/Pydantic's own request-shape errors (missing field, wrong
    type, ...), remapped onto this API's one error shape rather than
    FastAPI's default `{"detail": [{"loc": ..., "msg": ..., "type": ...}]}`."""
    detail = []
    for err in exc.errors():
        loc = [str(part) for part in err["loc"] if part not in ("body", "query", "path")]
        detail.append({"field": ".".join(loc) or None, "message": err["msg"], "code": err["type"]})
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    """Backstop for a constraint violation no route-level check caught —
    surfaces as a readable 409 instead of a 500 stack trace."""
    return JSONResponse(
        status_code=409,
        content={
            "detail": [
                {
                    "field": None,
                    "message": f"Database constraint violation: {exc.orig}",
                    "code": "INTEGRITY_ERROR",
                }
            ]
        },
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
