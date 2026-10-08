import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.routers import (
    catalog,
    catalog_items,
    dashboard,
    decisions,
    estate,
    engagement_patterns,
    engagements,
    health,
    item_decisions,
    patterns,
    repositories,
    signal_registry,
    step_policies,
    structure,
    surface,
    target_states,
    test_coverage,
    workflow_artifacts,
    workflow_capabilities,
    workflow_executions,
    validation_queue,
    workflow_jobs,
    workflow_policy,
    workflow_steps,
)


def _reconcile_orphaned_executions() -> None:
    """Marks any execution left `STARTING`/`STARTED` by a previous process as
    `FAILED`, with the step that was in flight. `BackgroundTasks` execution is in-memory and does not survive a
    process restart — without this, an execution whose background task was
    killed mid-run would show as permanently stuck rather than as a clear,
    restartable failure. See 15-REPOSITORY-INGEST-UI.md Part E."""
    from app import models
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        orphaned = (
            db.query(models.WfJobExecution)
            .filter(models.WfJobExecution.batch_status.in_(["STARTING", "STARTED"]))
            .all()
        )
        if not orphaned:
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        for execution in orphaned:
            execution.batch_status = "FAILED"
            execution.exit_status = "FAILED"
            execution.exit_message = "orphaned by engine restart"
            execution.ended_at = now
            # Steps commit as they go, so completed steps are already
            # COMPLETED; only the one in flight is left STARTED. Failing it
            # is what makes a resume rerun it and carry the rest forward.
            for step in db.query(models.WfStepExecution).filter(
                models.WfStepExecution.job_execution_id == execution.id,
                models.WfStepExecution.batch_status.in_(["STARTING", "STARTED"]),
            ):
                step.batch_status = "FAILED"
                step.exit_status = "FAILED"
                step.exit_message = "orphaned by engine restart"
                step.ended_at = now
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _reconcile_orphaned_executions()
    yield

app = FastAPI(
    title="Modernization Platform API",
    version="0.4.0",
    lifespan=lifespan,
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
            "name": "Item Catalog",
            "description": (
                "The item & conversion model's master catalog (28-ITEM-AND-CONVERSION-MODEL.md): "
                "catalog items (things that need work, with detection and scope), their "
                "resolutions, the extractor declarations and signal registry they depend on, "
                "and coverage views. `state` is computed from signal readiness and never "
                "settable. Runs alongside the pattern catalog until cut-over."
            ),
        },
        {
            "name": "Item Decisions",
            "description": (
                "An engagement's chosen resolution per catalog item. Client-scoped: writes "
                "only `engagement_decisions`, never the item catalog."
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
        {
            "name": "Step Policies",
            "description": (
                "Engagement-scoped overrides disabling a lifecycle step — configuration, not "
                "design. Absence of a row means enabled. Disabling a step whose non-optional "
                "output another step still requires is refused unless the dependents are "
                "disabled in the same request — see 22-STEP-SEQUENCING-AND-POLICY.md Part C."
            ),
        },
        {
            "name": "Workflow Artifacts",
            "description": (
                "Files a step produced and registered with the engine. `content` and "
                "`download` both re-verify the on-disk checksum against the recorded "
                "one before serving anything — drift is a real finding, never served "
                "silently. See 20-WORKFLOW-OBSERVABILITY-UI.md."
            ),
        },
        {
            "name": "Repositories",
            "description": (
                "Engagement-scoped registration of local repository folders — the entry "
                "point to phase 0. The repository already exists on the operating machine; "
                "there is no file upload. Registering one launches "
                "`phase0-repository-discovery` for it automatically. See "
                "15-REPOSITORY-INGEST-UI.md."
            ),
        },
        {
            "name": "Dashboard",
            "description": (
                "Engagement-scoped, read-only modernization status, repository by "
                "repository. `null` fields are sections no implemented step produces "
                "yet — never a fabricated zero. See 16-DASHBOARD-SPEC.md."
            ),
        },
        {
            "name": "Estate",
            "description": (
                "Engagement-wide results of lifecycle step 11: the endpoint register, "
                "package estate, dependency graph and context map, with the "
                "conversation annotations people keep on each host. See "
                "31-STEP-011-ESTATE-DEPENDENCY-MAP.md."
            ),
        },
        {
            "name": "Solution Discovery",
            "description": (
                "Read-only results of lifecycle step 2: solutions, projects, project "
                "references, and supporting artifacts found per repository. Structural "
                "facts only — nothing here is interpreted as an application or a pattern "
                "yet. See 19-STEP-002-SOLUTION-DISCOVERY.md."
            ),
        },
        {
            "name": "Surface",
            "description": (
                "Read-only results of lifecycle step 4: what can call a repository's "
                "applications — HTTP routes, WCF, ASMX, gRPC and SignalR operations, "
                "WebForms pages, consumers, hosted services, scheduled jobs and mains. "
                "See 29-STEPS-004-005-INVENTORIES.md Part D."
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
app.include_router(step_policies.router)
app.include_router(decisions.router)
app.include_router(catalog.router)
app.include_router(signal_registry.router)
app.include_router(catalog_items.router)
app.include_router(item_decisions.router)
app.include_router(workflow_steps.router)
app.include_router(workflow_capabilities.router)
app.include_router(validation_queue.router)
app.include_router(workflow_jobs.router)
app.include_router(workflow_executions.router)
app.include_router(workflow_policy.router)
app.include_router(workflow_artifacts.router)
app.include_router(repositories.router)
app.include_router(structure.router)
app.include_router(surface.router)
app.include_router(dashboard.router)
app.include_router(estate.router)
app.include_router(test_coverage.router)
