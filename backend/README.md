# Backend

FastAPI + SQLAlchemy + Alembic over PostgreSQL. Full setup is in
`docs/01-ENVIRONMENT-SETUP.md`; this is the day-to-day reference.

## Run the API

Run it from your own terminal, from `backend/`, so you can restart it and read its logs
directly:

```powershell
cd backend; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --port 8001
```

Start it from `backend/`, not the repository root. `.env` (`DATABASE_URL` and the rest)
and `RUNS_DIR=./runs` are resolved relative to the current directory, so starting it
anywhere else silently uses the wrong database settings and run folder.

- `--reload` restarts on code changes. Drop it to match what the workflow engine sees
  (background job runs are in-process and do not survive a restart; see CLAUDE.md
  "Operating model").
- Stop with Ctrl+C. The API is at http://127.0.0.1:8001, the OpenAPI UI at
  http://127.0.0.1:8001/docs.
- Restart after running migrations or the seed, and after republishing a step
  binary, so the process picks up the new state.

## Database, seed and tests

```powershell
cd backend; .\.venv\Scripts\Activate.ps1; alembic upgrade head
```

```powershell
cd backend; .\.venv\Scripts\Activate.ps1; python -m app.seed
```

The seed is idempotent. It loads the pattern catalog, lifecycle steps, signal registry,
pattern → item migration and authored catalog items, in that order.

```powershell
cd backend; .\.venv\Scripts\Activate.ps1; python -m unittest discover -s tests
```
