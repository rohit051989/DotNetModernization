"""Creating an engagement: one client program, with the .NET target framework its estate moves to.

The API (POST /api/engagements) and the command line (python -m app.engagements.cli create) both call `create`, so
the two check exactly the same things.
"""
import re

from sqlalchemy.orm import Session

from app import models

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# A modern .NET target framework moniker: net8.0, net10.0. The estate moves to one of these.
TARGET_FRAMEWORK_RE = re.compile(r"^net(\d+)\.\d+$")
MIN_TARGET_MAJOR = 5


class EngagementError(Exception):
    """A problem with the request, in the API's error shape. `status_code`: 422 for a bad value, 409 for an id in
    use."""

    def __init__(self, status_code: int, field: str, message: str, code: str):
        super().__init__(message)
        self.status_code = status_code
        self.field = field
        self.code = code


def id_from_name(name: str) -> str:
    """The id a name suggests: lower case, words joined by hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:63].strip("-")


def check(engagement_id: str, client_name: str, target_framework: str) -> None:
    if not client_name.strip():
        raise EngagementError(422, "client_name", "The client name is required.", "NAME_REQUIRED")
    if not ID_RE.match(engagement_id):
        raise EngagementError(422, "id", f"'{engagement_id}' is not a valid id: use lower-case letters, digits and "
                                         "hyphens, starting with a letter or digit, at most 63 characters.", "INVALID_ID")
    match = TARGET_FRAMEWORK_RE.match(target_framework)
    if match is None or int(match.group(1)) < MIN_TARGET_MAJOR:
        raise EngagementError(422, "target_framework", f"'{target_framework}' is not a modern .NET target framework: "
                                                       "use a moniker such as net8.0 or net10.0.", "INVALID_TARGET_FRAMEWORK")


def create(db: Session, engagement_id: str, client_name: str, target_framework: str = "net10.0",
           description: str | None = None, target_platform: str | None = None,
           default_posture: str = "lift-and-shift") -> models.Engagement:
    """Adds the engagement and flushes; the caller commits. Raises EngagementError."""
    engagement_id = engagement_id.strip()
    client_name = client_name.strip()
    target_framework = target_framework.strip()
    check(engagement_id, client_name, target_framework)
    if db.get(models.Engagement, engagement_id) is not None:
        raise EngagementError(409, "id", f"Engagement '{engagement_id}' already exists", "DUPLICATE_ID")
    engagement = models.Engagement(
        id=engagement_id, client_name=client_name, description=description, target_platform=target_platform,
        default_posture=default_posture, target_framework=target_framework,
    )
    db.add(engagement)
    db.flush()
    return engagement
