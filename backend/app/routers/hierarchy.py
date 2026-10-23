"""Read-only endpoints for the repository's Dependency graph tab: its dependency graph (37-DEPENDENCY-HIERARCHY.md Part
E). The dependency-hierarchy step owns every row read. The UI asks for the roots, then each node's children when it is
expanded, a page of 20 at a time."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.errors import ErrorResponse, error
from app.hierarchy import service
from app.hierarchy.schemas import ChildrenOut, HierarchyOut, NodeDetailOut, SearchOut

router = APIRouter(prefix="/api/repositories/{repository_id}/hierarchy", tags=["Dependency graph"])

_NOT_FOUND = {"model": ErrorResponse, "description": "No repository, or no node, exists with this id."}
_NOT_SCANNED = {"model": ErrorResponse, "description": "dependency-hierarchy has not run yet for this repository."}
_RESPONSES = {404: _NOT_FOUND, 409: _NOT_SCANNED}

TransitiveQuery = Query(False, description="Include packages' own dependencies (package to package edges).")
ShowQuery = Query("all", pattern="^(all|internal|external|projects)$",
                  description="all; internal (projects and internal packages); external (projects and external packages); projects.")


def _view(transitive: bool, show: str) -> service.View:
    return service.View(transitive=transitive, show=show)


def _run(db: Session, repository_id: uuid.UUID, call):
    repo = db.get(models.Repository, repository_id)
    if repo is None or repo.deleted_at is not None:
        raise error(404, f"Repository '{repository_id}' not found", code="NOT_FOUND")
    try:
        return call()
    except service.NotScanned as exc:
        raise error(409, "The dependency hierarchy has not been built for this repository yet: rescan it.", code="NOT_SCANNED") from exc
    except service.NodeNotFound as exc:
        raise error(404, f"Node '{exc}' is not in this repository's dependency graph", field="node", code="NOT_FOUND") from exc


@router.get("", response_model=HierarchyOut, summary="A repository's dependency graph: its summary and roots",
            operation_id="get_repository_hierarchy", responses=_RESPONSES)
def get_hierarchy(repository_id: uuid.UUID, transitive: bool = TransitiveQuery, show: str = ShowQuery, db: Session = Depends(get_db)):
    """The roots are the projects no other project in the repository references — usually the applications."""
    return _run(db, repository_id, lambda: service.overview(db, repository_id, _view(transitive, show)))


@router.get("/children", response_model=ChildrenOut, summary="One node's children, a page at a time",
            operation_id="get_repository_hierarchy_children", responses=_RESPONSES)
def get_children(repository_id: uuid.UUID, node: str = Query(..., description="The node's id, e.g. project:src/Web/Web.csproj."),
                 transitive: bool = TransitiveQuery, show: str = ShowQuery,
                 offset: int = Query(0, ge=0), limit: int = Query(service.PAGE, ge=1, le=500), db: Session = Depends(get_db)):
    return _run(db, repository_id, lambda: service.children(db, repository_id, node, _view(transitive, show), offset, limit))


@router.get("/search", response_model=SearchOut, summary="Find nodes by name, each with its path from a root",
            operation_id="search_repository_hierarchy", responses=_RESPONSES)
def search(repository_id: uuid.UUID, q: str = Query(..., min_length=1, max_length=200), transitive: bool = TransitiveQuery,
           show: str = ShowQuery, db: Session = Depends(get_db)):
    return _run(db, repository_id, lambda: service.search(db, repository_id, q, _view(transitive, show)))


@router.get("/node", response_model=NodeDetailOut, summary="One node's details: its parents and work items",
            operation_id="get_repository_hierarchy_node", responses=_RESPONSES)
def get_node(repository_id: uuid.UUID, node: str = Query(...), transitive: bool = TransitiveQuery, show: str = ShowQuery,
             db: Session = Depends(get_db)):
    return _run(db, repository_id, lambda: service.node_detail(db, repository_id, node, _view(transitive, show)))
