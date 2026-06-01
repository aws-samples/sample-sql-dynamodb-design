from sqlalchemy.orm import Session
from backend.db.models import ModelOverride


class OverrideRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_project(self, project_id: int, active_only: bool = True) -> list[ModelOverride]:
        q = self.db.query(ModelOverride).filter(ModelOverride.project_id == project_id)
        if active_only:
            q = q.filter(ModelOverride.active == True)
        return q.order_by(ModelOverride.created_at.desc()).all()

    def create(self, project_id: int, entity_name: str, override_type: str,
               description: str, details: dict = None) -> ModelOverride:
        override = ModelOverride(
            project_id=project_id,
            entity_name=entity_name,
            override_type=override_type,
            description=description,
            details=details or {},
            active=True
        )
        self.db.add(override)
        self.db.commit()
        self.db.refresh(override)
        return override

    def update(self, override_id: int, **kwargs) -> ModelOverride | None:
        override = self.db.query(ModelOverride).filter(ModelOverride.id == override_id).first()
        if not override:
            return None
        for k, v in kwargs.items():
            if hasattr(override, k):
                setattr(override, k, v)
        self.db.commit()
        self.db.refresh(override)
        return override

    def delete(self, override_id: int) -> bool:
        override = self.db.query(ModelOverride).filter(ModelOverride.id == override_id).first()
        if not override:
            return False
        self.db.delete(override)
        self.db.commit()
        return True
