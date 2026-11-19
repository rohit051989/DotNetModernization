"""The Artifactory tab's API — the Artifactory repositories an engagement's scans ask (docs/39-ARTIFACTORY.md).

The list is shared by everyone on the database. It never holds a credential: an artifactory's login comes from NuGet.config,
else from the environment of the machine that scans (NuGetPackageSourceCredentials_<name>, or ARTIFACTORY_TOKEN, or
ARTIFACTORY_USERNAME and ARTIFACTORY_PASSWORD, which backend/.env may supply). The status route only says which method the
machine has, never a value.
"""
import datetime
import re
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.auth import actor as actors
from app.config import artifactory_method, settings
from app.db import get_db
from app.errors import ErrorResponse, error

router = APIRouter(prefix="/api/engagements", tags=["Artifactory"])

_NOT_FOUND = {"model": ErrorResponse, "description": "No engagement or artifactory exists with this id."}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")


def normalise_url(url: str) -> str:
    """The URL as the duplicate check and the scan's lookup cache see it: scheme and host in lower case, no user
    information, query or fragment, no trailing slash. Raises ValueError for anything but an absolute http(s) URL."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("Enter an absolute http or https URL, for example https://host/artifactory/api/nuget/v3/index.json.")
    host = parts.hostname.lower()
    if ":" in host:                      # an IPv6 literal
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme.lower()}://{host}{port}{parts.path.rstrip('/')}"


def default_name(url: str) -> str:
    """A name from the URL: its host and last path segments that say what the artifactory is, without the index file."""
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s and s.lower() not in ("index.json", "v3", "v2", "api", "nuget")]
    return re.sub(r"[^A-Za-z0-9._-]+", "-", (segments[-1] if segments else parts.hostname or "artifactory"))[:64]


class ArtifactoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(description="The artifactory's NuGet v3 index URL. Credentials in the URL are refused.")
    name: str | None = Field(None, description="The source name; also the name in NuGetPackageSourceCredentials_<name>. "
                                               "Defaults from the URL.")


class ArtifactoryOut(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    created_by: str | None
    created_at: datetime.datetime


class CredentialsStatusOut(BaseModel):
    machine_login: bool = Field(description="Whether this machine's backend has an artifactory login: ARTIFACTORY_TOKEN, or "
                                            "ARTIFACTORY_USERNAME and ARTIFACTORY_PASSWORD. Never their values.")
    method: str = Field("none", description="Which login: 'token' (it wins over a username and password), "
                                            "'username and password' or 'none'. Never a value.")


def _engagement(db: Session, engagement_id: str) -> models.Engagement:
    engagement = db.get(models.Engagement, engagement_id)
    if engagement is None or engagement.deleted_at is not None:
        raise error(404, f"Engagement '{engagement_id}' not found", code="NOT_FOUND")
    return engagement


def _out(row: models.EngagementFeed) -> ArtifactoryOut:
    return ArtifactoryOut(id=row.id, name=row.name, url=row.url, created_by=row.created_by, created_at=row.created_at)


def live_artifactories(db: Session, engagement_id: str) -> list[models.EngagementFeed]:
    return (db.query(models.EngagementFeed)
            .filter(models.EngagementFeed.engagement_id == engagement_id, models.EngagementFeed.deleted_at.is_(None))
            .order_by(models.EngagementFeed.created_at, models.EngagementFeed.name).all())


@router.get("/{engagement_id}/artifactories", response_model=list[ArtifactoryOut], operation_id="list_engagement_artifactories",
            summary="List the engagement's Artifactory repositories", responses={404: _NOT_FOUND})
def list_artifactories(engagement_id: str, db: Session = Depends(get_db)):
    _engagement(db, engagement_id)
    return [_out(r) for r in live_artifactories(db, engagement_id)]


@router.post("/{engagement_id}/artifactories", response_model=ArtifactoryOut, status_code=201,
             operation_id="add_engagement_artifactory", summary="Add an Artifactory repository to the engagement",
             responses={404: _NOT_FOUND, 409: {"model": ErrorResponse, "description": "The artifactory URL or name is already listed."},
                        422: {"model": ErrorResponse, "description": "The URL or name is not valid."}})
def add_artifactory(engagement_id: str, payload: ArtifactoryIn, db: Session = Depends(get_db)):
    """Adds an artifactory the engagement's next scans ask. No login is taken here: NuGet.config or this machine's environment
    supplies it. A URL already listed is refused (409 DUPLICATE_ARTIFACTORY_URL)."""
    _engagement(db, engagement_id)
    if urlsplit(payload.url.strip()).username or urlsplit(payload.url.strip()).password:
        raise error(422, "Leave the login out of the URL: it comes from NuGet.config or the environment.", "url",
                    "EMBEDDED_CREDENTIALS")
    try:
        normalised = normalise_url(payload.url)
    except ValueError as exc:
        raise error(422, str(exc), "url", "INVALID_ARTIFACTORY_URL") from None
    name = (payload.name or "").strip() or default_name(normalised)
    if not _NAME.match(name):
        raise error(422, "A name is letters, digits, dots, dashes, underscores and spaces, up to 64 characters.", "name",
                    "INVALID_ARTIFACTORY_NAME")
    existing = live_artifactories(db, engagement_id)
    if any(f.url_normalised == normalised for f in existing):
        raise error(409, "This artifactory URL is already added to the engagement.", "url", "DUPLICATE_ARTIFACTORY_URL")
    if any(f.name.lower() == name.lower() for f in existing):
        raise error(409, f"An artifactory named '{name}' is already added: choose another name.", "name", "DUPLICATE_ARTIFACTORY_NAME")
    person = actors.current()
    row = models.EngagementFeed(engagement_id=engagement_id, name=name, url=normalised, url_normalised=normalised,
                                created_by=person.label() if person else None)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:               # two people adding the same URL at once: the unique index decides
        db.rollback()
        raise error(409, "This artifactory URL or name is already added to the engagement.", "url", "DUPLICATE_ARTIFACTORY_URL") from None
    db.refresh(row)
    return _out(row)


@router.delete("/{engagement_id}/artifactories/{artifactory_id}", status_code=204, operation_id="remove_engagement_artifactory",
               summary="Remove an Artifactory repository from the engagement", responses={404: _NOT_FOUND})
def remove_artifactory(engagement_id: str, artifactory_id: uuid.UUID, db: Session = Depends(get_db)):
    """Soft delete (CLAUDE.md rule 7): the row stays, and the URL can be added again."""
    _engagement(db, engagement_id)
    row = db.get(models.EngagementFeed, artifactory_id)
    if row is None or row.engagement_id != engagement_id or row.deleted_at is not None:
        raise error(404, "Artifactory not found", code="NOT_FOUND")
    person = actors.current()
    row.deleted_at = datetime.datetime.now(datetime.timezone.utc)
    row.deleted_by = person.label() if person else None
    db.commit()


@router.get("/{engagement_id}/artifactory/credentials-status", response_model=CredentialsStatusOut,
            operation_id="get_artifactory_credentials_status", summary="Whether this machine has an artifactory login",
            responses={404: _NOT_FOUND})
def credentials_status(engagement_id: str, db: Session = Depends(get_db)):
    _engagement(db, engagement_id)
    token = settings.artifactory_token.get_secret_value() if settings.artifactory_token else None
    password = settings.artifactory_password.get_secret_value() if settings.artifactory_password else None
    # As before the token: a username and a non-empty password make the pair.
    method = artifactory_method(token, settings.artifactory_username, password or None)
    return CredentialsStatusOut(machine_login=method != "none", method=method)
