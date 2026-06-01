import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.repositories import PatternRepository
from backend.api.schemas import (
    AccessPatternCreate, AccessPatternResponse, AccessPatternUpdate,
    WritePatternCreate, WritePatternResponse, WritePatternUpdate,
)
from backend.services.validation_service import PatternValidationService
from backend.services.markdown_writer import append_pattern_to_md

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/patterns", tags=["patterns"])


# --- Access Patterns ---

@router.get("/access", response_model=list[AccessPatternResponse])
def list_access_patterns(project_id: int, classification: str = None, db: Session = Depends(get_db)):
    repo = PatternRepository(db)
    patterns = repo.get_access_patterns(project_id)
    if classification:
        patterns = [p for p in patterns if p.classification == classification]
    return patterns


@router.patch("/access/{pattern_id}", response_model=AccessPatternResponse)
def update_access_pattern(project_id: int, pattern_id: int, req: AccessPatternUpdate, db: Session = Depends(get_db)):
    repo = PatternRepository(db)
    pattern = repo.update_access_pattern(pattern_id, **req.model_dump(exclude_unset=True))
    if not pattern:
        raise HTTPException(status_code=404, detail="Access pattern not found")
    return pattern


@router.post("/access", response_model=AccessPatternResponse, status_code=201)
def create_access_pattern(project_id: int, req: AccessPatternCreate, db: Session = Depends(get_db)):
    try:
        result = PatternValidationService().validate_access_pattern(project_id, req, db)
    except Exception:
        logger.exception("Validation service error")
        raise HTTPException(status_code=503, detail="Validation service unavailable. Please try again.")

    if not result.valid:
        raise HTTPException(status_code=422, detail=result.reason)

    repo = PatternRepository(db)
    pattern_id = repo.get_next_access_pattern_id(project_id)

    pattern = repo.create_access_pattern(
        project_id,
        pattern_id=pattern_id,
        name=req.name,
        operation="READ",
        source_entities=req.source_entities,
        requests_per_hour=req.requests_per_hour,
        avg_items_returned=req.avg_items_returned,
        source_code=req.source_code,
        source="user",
        classification="in_scope",
    )

    append_pattern_to_md(
        {
            "pattern_id": pattern_id,
            "name": req.name,
            "operation": "READ",
            "source_entities": req.source_entities,
            "requests_per_hour": req.requests_per_hour,
            "avg_items_returned": req.avg_items_returned,
            "source_code": req.source_code,
            "source": "User-added",
        },
        pattern_type="access",
    )

    return pattern


# --- Write Patterns ---

@router.get("/write", response_model=list[WritePatternResponse])
def list_write_patterns(project_id: int, classification: str = None, db: Session = Depends(get_db)):
    repo = PatternRepository(db)
    patterns = repo.get_write_patterns(project_id)
    if classification:
        patterns = [p for p in patterns if p.classification == classification]
    return patterns


@router.patch("/write/{pattern_id}", response_model=WritePatternResponse)
def update_write_pattern(project_id: int, pattern_id: int, req: WritePatternUpdate, db: Session = Depends(get_db)):
    repo = PatternRepository(db)
    pattern = repo.update_write_pattern(pattern_id, **req.model_dump(exclude_unset=True))
    if not pattern:
        raise HTTPException(status_code=404, detail="Write pattern not found")
    return pattern


@router.post("/write", response_model=WritePatternResponse, status_code=201)
def create_write_pattern(project_id: int, req: WritePatternCreate, db: Session = Depends(get_db)):
    try:
        result = PatternValidationService().validate_write_pattern(project_id, req, db)
    except Exception:
        logger.exception("Validation service error")
        raise HTTPException(status_code=503, detail="Validation service unavailable. Please try again.")

    if not result.valid:
        raise HTTPException(status_code=422, detail=result.reason)

    repo = PatternRepository(db)
    pattern_id = repo.get_next_write_pattern_id(project_id)

    pattern = repo.create_write_pattern(
        project_id,
        pattern_id=pattern_id,
        name=req.name,
        operation="WRITE",
        target_entities=req.target_entities,
        requests_per_hour=req.requests_per_hour,
        items_per_transaction=req.items_per_transaction,
        source_code=req.source_code,
        source="user",
        classification="in_scope",
    )

    append_pattern_to_md(
        {
            "pattern_id": pattern_id,
            "name": req.name,
            "operation": "WRITE",
            "target_entities": req.target_entities,
            "requests_per_hour": req.requests_per_hour,
            "items_per_transaction": req.items_per_transaction,
            "source_code": req.source_code,
            "source": "User-added",
        },
        pattern_type="write",
    )

    return pattern


@router.delete("/access/{pattern_id}")
def delete_access_pattern(project_id: int, pattern_id: int, db: Session = Depends(get_db)):
    repo = PatternRepository(db)
    if not repo.delete_user_access_pattern(pattern_id):
        raise HTTPException(status_code=404, detail="User pattern not found")
    return {"detail": "Deleted"}


@router.delete("/write/{pattern_id}")
def delete_write_pattern(project_id: int, pattern_id: int, db: Session = Depends(get_db)):
    repo = PatternRepository(db)
    if not repo.delete_user_write_pattern(pattern_id):
        raise HTTPException(status_code=404, detail="User pattern not found")
    return {"detail": "Deleted"}
