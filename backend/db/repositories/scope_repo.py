from sqlalchemy.orm import Session
from backend.db.models import MigrationScope


class ScopeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_project(self, project_id: int) -> MigrationScope | None:
        return self.db.query(MigrationScope).filter(MigrationScope.project_id == project_id).first()

    def create_or_update(self, project_id: int, mode: str, selected_entities: list[str], excluded_entities: list[str] = None) -> MigrationScope:
        scope = self.get_by_project(project_id)
        if scope:
            scope.mode = mode
            scope.selected_entities = selected_entities
            scope.excluded_entities = excluded_entities or []
        else:
            scope = MigrationScope(
                project_id=project_id,
                mode=mode,
                selected_entities=selected_entities,
                excluded_entities=excluded_entities or []
            )
            self.db.add(scope)
        self.db.commit()
        self.db.refresh(scope)
        return scope
