from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.repositories import ScopeRepository, EntityRepository, PatternRepository
from backend.api.schemas import MigrationScopeRequest, MigrationScopeResponse

router = APIRouter(prefix="/projects/{project_id}/scope", tags=["scope"])


@router.get("/", response_model=MigrationScopeResponse | None)
def get_scope(project_id: int, db: Session = Depends(get_db)):
    repo = ScopeRepository(db)
    return repo.get_by_project(project_id)


@router.put("/", response_model=MigrationScopeResponse)
def set_scope(project_id: int, req: MigrationScopeRequest, db: Session = Depends(get_db)):
    scope_repo = ScopeRepository(db)
    entity_repo = EntityRepository(db)
    pattern_repo = PatternRepository(db)

    # Get all entity names for excluded list
    all_entities = entity_repo.get_by_project(project_id)
    all_names = {e.name for e in all_entities}
    selected_set = set(req.selected_entities)
    excluded = sorted(all_names - selected_set)

    # Save scope
    scope = scope_repo.create_or_update(
        project_id=project_id,
        mode=req.mode,
        selected_entities=req.selected_entities,
        excluded_entities=excluded
    )

    # Update entity selection flags
    entity_repo.update_selection(project_id, req.selected_entities)

    # Reclassify patterns
    pattern_repo.classify_access_patterns(project_id, selected_set)
    pattern_repo.classify_write_patterns(project_id, selected_set)

    return scope
