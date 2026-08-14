# 18 — API Conventions

Applies to every endpoint, existing and future. Retrofit the current API to comply
before adding more, because the surface roughly doubles in E7.

---

## Part A — OpenAPI documentation is mandatory

The generated `/docs` page is the contract another developer integrates against.
An endpoint list without descriptions is not documentation.

### Every route decorator carries

```python
@router.post(
    "/engagements/{engagement_id}/repositories/register",
    response_model=RegisterRepositoryResponse,
    status_code=202,
    summary="Register a repository from a local folder path",
    response_description="Accepted. Discovery has been launched; track it via job_execution_id.",
    tags=["Repositories"],
    responses={
        409: {"description": "Duplicate clone URL, folder name, or path; or the path nests inside an existing registration"},
        422: {"description": "Path does not exist, is relative, is a system location, or the clone URL is malformed"},
        501: {"description": "source_type git_clone is not yet implemented"},
    },
)
```

- **`summary`** — one line, imperative, under 60 characters. Shows in the collapsed list.
- **`response_description`** — what a success actually means, not "Successful Response".
- **`responses`** — document every non-200 status the handler can return, with the
  condition that causes it. This is the part that saves an integrator the most time.
- **`tags`** — group by router: `Health`, `Patterns`, `Target States`, `Engagements`,
  `Decisions`, `Catalog`, `Repositories`, `Workflow Steps`, `Workflow Jobs`,
  `Workflow Executions`, `Dashboard`.

### Longer explanation goes in the docstring

The handler docstring becomes the `description` field and supports markdown. Use it
where behaviour is not obvious from the summary:

```python
async def register_repository(...):
    """
    Registers an existing repository folder and immediately launches
    `phase0-repository-discovery` for it.

    The folder is read **in place** and never copied or modified. The clone URL you
    supply is verified against the folder's git remote; a mismatch is reported but
    does not block registration.

    Returns 202 rather than 201 because discovery runs asynchronously. Poll
    `GET /api/repositories/{id}` to follow progress.
    """
```

### Every Pydantic field carries a description

```python
class RegisterRepositoryRequest(BaseModel):
    local_path: str = Field(
        description="Absolute path to the repository folder on the machine running the platform.",
        examples=["D:\\repos\\order-management"],
    )
    clone_url: str = Field(
        description="Canonical repository URL. Identifies the repository independently of its location on disk. Verified against the folder's git remote where present.",
        examples=["https://github.com/example/order-management.git"],
    )
    criticality: Criticality = Field(
        default=Criticality.medium,
        description="Business criticality. Feeds review tier assignment at lifecycle step 10.",
    )
```

This applies to response models too — an integrator reading the response schema
should not have to guess what `clone_url_verification: "mismatch"` implies.

### Request and response examples

Attach a realistic example to every non-trivial request and response model via
`model_config = {"json_schema_extra": {"examples": [...]}}`. `/docs` renders these
as prefilled "Try it out" payloads, which makes the API explorable rather than
merely listed.

### App-level metadata

```python
app = FastAPI(
    title="Modernization Platform API",
    version="0.2.0",
    description="Control plane for .NET legacy modernization: pattern catalog, "
                "repository inventory, and the lifecycle orchestration engine.",
    openapi_tags=[
        {"name": "Patterns", "description": "Master catalog pattern definitions. Client-agnostic."},
        {"name": "Decisions", "description": "Engagement-specific target state decisions."},
        {"name": "Workflow Jobs", "description": "Job definitions and launching. A job is a lifecycle phase."},
        {"name": "Workflow Executions", "description": "Run history. One execution is one attempt at a job instance."},
        # ... one entry per tag
    ],
)
```

The tag descriptions are where the master-versus-client and definition-versus-run
distinctions get explained once, rather than repeated on every route.

### Stable operation ids

Set `operation_id` explicitly on every route (`register_repository`,
`list_engagement_decisions`). FastAPI's generated ids include the path and change
whenever a route moves, which breaks any generated client.

---

## Part B — Path conventions

Two rules, applied consistently.

**Rule 1 — collections nest under their owner; single resources stay flat.**

```
GET  /api/engagements/{eid}/decisions          list within an engagement
GET  /api/decisions/{decision_id}              one decision, globally unique id
```

A `decision_id` is unique on its own. Nesting it under parents adds redundancy and
raises "what if the path segments disagree with the record" — which then needs
validation and a new error case. Flat is correct for single-resource access.

**Rule 2 — when a resource is a singleton under a composite key, the path expresses
that key.**

This is where the current API is wrong. A decision record is one-per
`(engagement, pattern)`, enforced by a partial unique index. Passing `pattern_id` in
a request body hides the real identity.

### Required changes

| Current | Change to | Why |
|---|---|---|
| `POST /api/engagements/{eid}/decisions` with `pattern_id` in body | `PUT /api/engagements/{eid}/patterns/{pid}/decision` | Upsert of a singleton. Identity fully in the path |
| — | `GET /api/engagements/{eid}/patterns/{pid}/decision` | Fetch the live decision for a pattern. Returns 404 when none |
| `PUT /api/decisions/{decision_id}` | keep | Editing a specific record, including historical ones |
| `GET /api/engagements/{eid}/decisions` | keep | Collection listing |
| `POST /api/decisions/{decision_id}/supersede` | keep | Acts on one specific row |

The frontend decision panel always has both `engagement_id` and `pattern_id` in
context, so this change simplifies the client as well. Update the decision panel
calls accordingly; do not leave deprecated aliases behind at this stage.

### Workflow paths — canonical stays flat, add scoped reads

Do **not** nest executions under engagements and repositories. The engagement is a
job *parameter*, not an owner: `trackB-wave` is scoped to a wave and has no
`repository_id` at all, so a path shape that assumes one would be wrong for most
future jobs.

Keep canonical:

```
GET  /api/workflow/executions/{execution_id}
GET  /api/workflow/executions/{execution_id}/steps
POST /api/workflow/executions/{execution_id}/resume
POST /api/workflow/executions/{execution_id}/stop
```

Add filtering, so the flat collection is usable:

```
GET /api/workflow/executions?job_name=&batch_status=&engagement_id=&repository_id=&limit=&offset=
```

`engagement_id` and `repository_id` filter by matching inside
`wf_job_instances.parameters`. Document that they only match jobs which declare
those parameters.

Add scoped read routes for navigation — these are convenience views over the same
data, and the UI uses them directly:

```
GET /api/repositories/{repository_id}/executions      already specced in doc 15
GET /api/engagements/{eid}/executions                  add
```

### Job parameter discoverability

Add:

```
GET /api/workflow/jobs/{job_name}/parameters

→ 200
{
  "job_name": "phase0-repository-discovery",
  "definition_version": 1,
  "parameters": [
    {
      "name": "engagement_id",
      "type": "string",
      "required": true,
      "default": null,
      "description": "The engagement this run belongs to."
    },
    {
      "name": "repository_id",
      "type": "string",
      "required": true,
      "default": null,
      "description": "UUID of the registered repository to analyse."
    },
    {
      "name": "ingest_token",
      "type": "string",
      "required": true,
      "default": null,
      "description": "UUID generated per registration or rescan. Makes each rescan a distinct job instance rather than a restart of the previous one."
    }
  ]
}
```

Read from the active job definition. This is how E9's launch form builds its inputs
without hardcoding per-job knowledge, and it is the answer to the launch body
appearing as an empty object.

Extend the job definition format to allow an optional `description` on each
parameter, and populate it in `phase0-repository-discovery.yaml`. Update
`12-JOB-DEFINITION-FORMAT.md`.

Keep the launch body dynamic — `{"parameters": {...}}` — but attach a worked example
to the request model so `/docs` shows a realistic payload rather than `{}`:

```json
{
  "parameters": {
    "engagement_id": "client-a-ocp4",
    "repository_id": "3f2b8c14-9d7e-4a51-b6c2-8e1d4f70a9b3",
    "ingest_token": "c81d4e2f-6a3b-4f19-9c7d-2e5a8b1f30c6"
  }
}
```

Validation errors on launch must name the offending parameter and say whether it was
missing, unknown, or the wrong type — pointing at
`GET /api/workflow/jobs/{job_name}/parameters` in the message.

---

## Part C — Error response shape

One shape everywhere, documented once at app level:

```json
{
  "detail": [
    { "field": "clone_url", "message": "…", "code": "EMBEDDED_CREDENTIALS" }
  ]
}
```

- `422` — validation and business-rule failures
- `409` — referential or uniqueness refusals, message naming what blocks the action
- `404` — not found
- `501` — recognised but not implemented, listing what is supported instead

Register the error model as a shared component so every route's `responses` entry
references the same schema rather than redefining it.

---

## Part D — Retrofit scope

Apply Parts A through C to the existing API before starting E7:

- [ ] App-level title, version, description, and `openapi_tags` with descriptions
- [ ] `summary`, `response_description`, `tags`, `operation_id` and documented
      `responses` on every existing route
- [ ] Docstrings on routes whose behaviour is not self-evident, particularly master
      versus client catalog scoping, soft delete versus deprecate, and the
      forcing-factor rule
- [ ] `Field(description=...)` on every request and response model field
- [ ] Examples on every non-trivial request and response model
- [ ] Decision endpoints restructured per Part B, frontend updated
- [ ] `GET /api/workflow/jobs/{job_name}/parameters` added
- [ ] Launch request example added
- [ ] Execution list filters added
- [ ] `GET /api/engagements/{eid}/executions` added
- [ ] Shared error model registered and referenced

### Verification

```powershell
python - <<'PY'
import json, urllib.request
spec = json.load(urllib.request.urlopen("http://127.0.0.1:8001/openapi.json"))
missing = []
for path, ops in spec["paths"].items():
    for method, op in ops.items():
        if not op.get("summary"):     missing.append(f"{method.upper()} {path} — no summary")
        if not op.get("tags"):        missing.append(f"{method.upper()} {path} — no tags")
        if not op.get("operationId"): missing.append(f"{method.upper()} {path} — no operationId")
print(f"operations: {sum(len(o) for o in spec['paths'].values())}")
print("\n".join(missing) if missing else "all operations documented")
PY
```

Zero output from the missing list is the gate.
