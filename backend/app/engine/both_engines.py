"""Conversions prepared for one engine, brought to both (36-COPILOT-ENHANCED-CONVERSION Part Q, 2026-11-23).

Every conversion is prepared for GitHub Copilot and Claude Code together. One prepared before that has a single engine
(`engine` in its record, no `engines`). When this machine's backend starts, each repository registered on this machine
whose latest conversion is such a one and has not been run (app.engine.convert.unrun) is prepared again, through the
discovery run a rescan starts (what saving a scope does): that refreshes the conversion in place, with both engines'
inputs. One that has been run is left exactly as it is; the next conversion has both.
"""
import logging
import threading
from pathlib import Path

log = logging.getLogger("app.upgrade")


def single_engine_unrun(db) -> list:
    """This machine's repositories whose latest conversion was prepared for one engine and has not been run."""
    from app import models
    from app.results import held
    from app.engine import convert

    out = []
    for repo in db.query(models.Repository).filter(models.Repository.deleted_at.is_(None)).order_by(models.Repository.slug):
        if held.elsewhere(repo.registered_host):
            continue
        latest = (convert.records(repo.engagement_id, repo.slug) or [None])[-1]
        if latest is None or latest.get("engines"):
            continue
        if convert.unrun(Path(latest["worktree"]), latest["baseline"]):
            out.append(repo)
    return out


def prepare_again(db, repo) -> str:
    """Launches the discovery run that prepares the repository's unrun conversion again; returns its execution id."""
    from app.repositories import service as repositories
    from app.workflow.runtime import service as runtime

    token = repositories.start_rescan(repo)
    db.commit()
    execution, instance, definition = runtime.create_execution(db, "phase0-repository-discovery", {
        "engagement_id": repo.engagement_id, "repository_id": str(repo.id), "ingest_token": token,
        "prepare_conversion": True}, triggered_by="manual")
    db.commit()
    runtime.run_execution_in_background(execution.id, instance.id, definition.model_dump(mode="json"))
    return str(execution.id)


def on_start() -> None:
    """At startup, in the background: each single-engine unrun conversion of this machine, prepared again in turn."""
    def work():
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            repos = single_engine_unrun(db)
            for repo in repos:
                log.info("conversion of %s was prepared for one engine and has not been run: preparing it again for both",
                         repo.slug)
                try:
                    prepare_again(db, repo)
                except Exception:                               # one repository's failure never stops the others
                    db.rollback()
                    log.exception("could not prepare the conversion of %s again", repo.slug)
        except Exception:
            log.exception("could not look for conversions prepared for one engine")
        finally:
            db.close()

    threading.Thread(target=work, name="both-engines", daemon=True).start()
