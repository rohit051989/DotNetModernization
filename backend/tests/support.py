"""Shared test fixtures.

Tests create the engagement they need rather than relying on one the demo
data happens to contain: `scripts/reset-demo.ps1` clears every engagement,
and engagement data is the client's, not the catalog's (CLAUDE.md rule 6).
"""

from pathlib import Path

from sqlalchemy.orm import Session

from app import models

TEST_ENGAGEMENT_ID = "t-engagement-linux"
TEST_NON_LINUX_ENGAGEMENT_ID = "t-engagement-aks"


def ensure_test_engagement(db: Session) -> models.Engagement:
    """A Linux / OpenShift, lift-and-shift engagement — what the decision
    warnings in the item tests key on. Created if missing and flushed, so a
    test running inside a rolled-back transaction leaves nothing behind."""
    engagement = db.get(models.Engagement, TEST_ENGAGEMENT_ID)
    if engagement is None:
        engagement = models.Engagement(
            id=TEST_ENGAGEMENT_ID,
            client_name="Test engagement (Linux)",
            target_platform="Linux / OpenShift Container Platform 4",
            default_posture="lift-and-shift",
        )
        db.add(engagement)
        db.flush()
    return engagement


def ensure_non_linux_engagement(db: Session) -> models.Engagement:
    """An engagement whose target_platform does not name Linux — the
    counterpart for "the Linux warning fires on Linux engagements only"."""
    engagement = db.get(models.Engagement, TEST_NON_LINUX_ENGAGEMENT_ID)
    if engagement is None:
        engagement = models.Engagement(
            id=TEST_NON_LINUX_ENGAGEMENT_ID,
            client_name="Test engagement (AKS)",
            target_platform="Azure Kubernetes Service",
            default_posture="lift-and-shift",
        )
        db.add(engagement)
        db.flush()
    return engagement


class CommittedTestEngagement:
    """For tests whose session commits: creates the engagement if it is
    missing and removes it afterwards — only if this test created it, and
    only once the test's own rows are gone."""

    def __init__(self, db: Session):
        self.db = db
        self.created = db.get(models.Engagement, TEST_ENGAGEMENT_ID) is None
        self.engagement = ensure_test_engagement(db)
        db.commit()

    def remove(self) -> None:
        if not self.created:
            return
        engagement = self.db.get(models.Engagement, TEST_ENGAGEMENT_ID)
        if engagement is not None:
            self.db.delete(engagement)
            self.db.commit()


# ---------- sample applications, scanned in this run's own schema (release 7) ----------

SAMPLE_APPS = Path(__file__).resolve().parents[3] / "sampleapps"
SAMPLES_ENGAGEMENT_ID = "t-engagement-samples"
_scanned: dict[str, models.Repository | None] = {}


def scanned_sample(folder: str) -> "models.Repository | None":
    """A sample application from `sampleapps` beside this repository, registered in this test run's schema and
    discovered once per run by the real job (tests/__init__.py). None when the sample is not on this machine.

    Tests that need a scanned repository use this rather than whatever happens to be scanned in a live database. The
    scan is offline: package lookups are answered from this run's lookup cache only (lookup_offline) and the public
    comparison is off, so no feed is contacted; what a lookup would have said does not matter to these tests."""
    if folder in _scanned:
        return _scanned[folder]
    path = SAMPLE_APPS / folder
    if not path.is_dir():
        _scanned[folder] = None
        return None

    from unittest import mock

    from app.config import settings
    from app.db import SessionLocal
    from app.repositories import service as repositories_service
    from app.repositories.schemas import RegisterLocalPathRequest
    from app.workflow.runtime import service as runtime

    db = SessionLocal()
    try:
        engagement = db.get(models.Engagement, SAMPLES_ENGAGEMENT_ID)
        if engagement is None:
            engagement = models.Engagement(id=SAMPLES_ENGAGEMENT_ID, client_name="Test engagement (samples)",
                                           target_platform="Linux / OpenShift Container Platform 4", default_posture="lift-and-shift")
            db.add(engagement)
            db.commit()
        # A sample with a git origin is registered with it, as a person would: registration verifies the two match.
        import subprocess

        origin = subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"], capture_output=True, text=True)
        clone_url = origin.stdout.strip() if origin.returncode == 0 and origin.stdout.strip() else None
        repo = repositories_service.register_local_path(db, engagement, RegisterLocalPathRequest(
            source_type="local_path", local_path=str(path), **({"clone_url": clone_url} if clone_url else {})))
        db.commit()
        with mock.patch.object(settings, "compare_public_nuget_feed", False):
            execution = runtime.launch_job(db, "phase0-repository-discovery", {
                "engagement_id": SAMPLES_ENGAGEMENT_ID, "repository_id": str(repo.id), "ingest_token": repo.ingest_token,
                "lookup_offline": True, "prepare_conversion": False,
            }, triggered_by="manual")
            db.commit()
        if execution.batch_status != "COMPLETED":
            raise AssertionError(f"discovery of the sample {folder} did not complete: {execution.exit_message}")
        db.refresh(repo)
        db.expunge(repo)
        _scanned[folder] = repo
        return repo
    finally:
        db.close()
