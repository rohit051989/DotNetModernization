"""Shared error response shape — see 18-API-CONVENTIONS.md Part C.

Every error response from this API, regardless of status code, uses one
shape: a list under `detail`, even when there is exactly one problem and even
when it isn't about a single field. Route handlers should raise via `error()`
or `errors()` below rather than constructing `HTTPException` directly, so the
shape never drifts.
"""

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "field": "clone_url",
                    "message": "Embedded credentials are not allowed in a clone URL.",
                    "code": "EMBEDDED_CREDENTIALS",
                }
            ]
        }
    )

    field: str | None = Field(
        default=None,
        description=(
            "The request field this error concerns, or null when the error isn't "
            "about one field — a 404, or a referential conflict spanning several."
        ),
    )
    message: str = Field(description="Human-readable explanation, safe to show a user.")
    code: str | None = Field(
        default=None,
        description=(
            "A short machine-readable slug for this failure (e.g. 'NOT_FOUND', "
            "'DUPLICATE_CLONE_URL'), for callers that want to branch on it instead "
            "of parsing `message`."
        ),
    )


class ErrorResponse(BaseModel):
    """The body of every non-2xx response in this API — 404, 409, 422 and 501
    alike. Registered once as a shared OpenAPI component and referenced from
    every route's `responses`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "detail": [
                        {
                            "field": "clone_url",
                            "message": "Embedded credentials are not allowed in a clone URL.",
                            "code": "EMBEDDED_CREDENTIALS",
                        }
                    ]
                }
            ]
        }
    )

    detail: list[ErrorDetail] = Field(description="One or more problems with the request.")


def error(status_code: int, message: str, field: str | None = None, code: str | None = None) -> HTTPException:
    """Builds an HTTPException whose body matches ErrorResponse. Use for the
    common case of a single problem."""
    return HTTPException(status_code=status_code, detail=[{"field": field, "message": message, "code": code}])


def errors(status_code: int, items: list[dict]) -> HTTPException:
    """Same shape, for routes that can report more than one problem at once
    (e.g. decision-record validation, job-launch parameter checks). Each item
    should have `message` and may include `field` and `code`."""
    return HTTPException(status_code=status_code, detail=items)
