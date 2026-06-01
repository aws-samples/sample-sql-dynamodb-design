from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.repositories import OverrideRepository
from backend.api.schemas import ModelOverrideCreate, ModelOverrideUpdate, ModelOverrideResponse

router = APIRouter(prefix="/projects/{project_id}/overrides", tags=["overrides"])


@router.get("", response_model=list[ModelOverrideResponse])
def list_overrides(project_id: int, active_only: bool = True, db: Session = Depends(get_db)):
    repo = OverrideRepository(db)
    return repo.get_by_project(project_id, active_only=active_only)


@router.post("", response_model=ModelOverrideResponse)
def create_override(project_id: int, req: ModelOverrideCreate, db: Session = Depends(get_db)):
    repo = OverrideRepository(db)
    return repo.create(
        project_id=project_id,
        entity_name=req.entity_name,
        override_type=req.override_type,
        description=req.description,
        details=req.details
    )


@router.patch("/{override_id}", response_model=ModelOverrideResponse)
def update_override(project_id: int, override_id: int, req: ModelOverrideUpdate,
                    db: Session = Depends(get_db)):
    repo = OverrideRepository(db)
    updates = req.model_dump(exclude_unset=True)
    result = repo.update(override_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Override not found")
    return result


@router.delete("/{override_id}")
def delete_override(project_id: int, override_id: int, db: Session = Depends(get_db)):
    repo = OverrideRepository(db)
    if not repo.delete(override_id):
        raise HTTPException(status_code=404, detail="Override not found")
    return {"ok": True}
