from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.repositories import EntityRepository
from backend.api.schemas import EntityResponse, EntityUpdate

router = APIRouter(prefix="/projects/{project_id}/entities", tags=["entities"])


@router.get("/", response_model=list[EntityResponse])
def list_entities(project_id: int, db: Session = Depends(get_db)):
    repo = EntityRepository(db)
    return repo.get_by_project(project_id)


@router.get("/selected", response_model=list[EntityResponse])
def list_selected_entities(project_id: int, db: Session = Depends(get_db)):
    repo = EntityRepository(db)
    return repo.get_selected(project_id)


@router.patch("/{entity_id}", response_model=EntityResponse)
def update_entity(project_id: int, entity_id: int, req: EntityUpdate, db: Session = Depends(get_db)):
    repo = EntityRepository(db)
    entity = repo.update(entity_id, **req.model_dump(exclude_unset=True))
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.put("/selection")
def update_entity_selection(project_id: int, selected_names: list[str], db: Session = Depends(get_db)):
    repo = EntityRepository(db)
    repo.update_selection(project_id, selected_names)
    return {"detail": f"Updated selection: {len(selected_names)} entities selected"}
