"""A page of a list, served by the database (app.results): the lists that grow with a repository are never sent
whole. Each is a query producing one row per item with its JSON, the text its filter box matches, and the columns it
is sorted by; this wraps it with the filter, the counts and the page.

The UI's paged list (frontend/src/components/PagedList.tsx) asks for 20 at a time, more on request, and sends the
filter box's text as `q`: a case-insensitive substring of what the person sees for an item.
"""
from typing import Any

from fastapi import Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

PAGE = 20
MOST = 500


class PageOut(BaseModel):
    total: int = Field(description="Items in the list, before the filter box's text (after any other filter).")
    matching: int = Field(description="Items the filter box's text matches; the total when there is none.")
    offset: int
    items: list[Any]


class PageParams:
    """The query parameters every paged list takes."""

    def __init__(
        self,
        q: str = Query("", description="What the filter box holds: a case-insensitive substring of an item's names."),
        offset: int = Query(0, ge=0),
        limit: int = Query(PAGE, ge=1, le=MOST),
    ):
        self.q, self.offset, self.limit = q.strip(), offset, limit


def like(q: str) -> str:
    """A LIKE pattern for a substring, its wildcards escaped."""
    escaped = q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def page(db: Session, source: str, params: dict, page_params: PageParams, order: str, where: str = "true") -> PageOut:
    """`source` selects `item` (jsonb), `search` (text, lower case) and the sort columns `order` names. `where`
    filters it before the counts (a checkbox, a choice); the filter box's text then narrows `matching`."""
    sql = f"""
        with src as ({source}),
        base as (select * from src where {where}),
        hit as (select * from base where :q = '' or search like :pattern escape '\\')
        select (select count(*) from base) as total,
               (select count(*) from hit) as matching,
               coalesce((select jsonb_agg(item order by n) from (
                   select item, row_number() over (order by {order}) as n
                   from hit order by {order} offset :offset limit :limit) shown), '[]'::jsonb) as items
    """
    row = db.execute(text(sql), {**params, "q": page_params.q, "pattern": like(page_params.q),
                                 "offset": page_params.offset, "limit": page_params.limit}).one()
    return PageOut(total=row.total, matching=row.matching, offset=page_params.offset, items=row.items)
