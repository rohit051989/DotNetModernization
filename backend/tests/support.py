"""Shared test fixtures.

Tests create the engagement they need rather than relying on one the demo
data happens to contain: `scripts/reset-demo.ps1` clears every engagement,
and engagement data is the client's, not the catalog's (CLAUDE.md rule 6).
"""

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
