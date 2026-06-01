from sqlalchemy.orm import Session
from backend.db.models import Entity


class EntityRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, project_id: int, **kwargs) -> Entity:
        entity = Entity(project_id=project_id, **kwargs)
        self.db.add(entity)
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def bulk_create(self, project_id: int, entities: list[dict]) -> list[Entity]:
        db_entities = []
        for data in entities:
            entity = Entity(project_id=project_id, **data)
            self.db.add(entity)
            db_entities.append(entity)
        self.db.commit()
        for e in db_entities:
            self.db.refresh(e)
        return db_entities

    def get_by_project(self, project_id: int) -> list[Entity]:
        return self.db.query(Entity).filter(Entity.project_id == project_id).order_by(Entity.name).all()

    def get_selected(self, project_id: int) -> list[Entity]:
        return self.db.query(Entity).filter(Entity.project_id == project_id, Entity.selected == True).all()

    def get_by_id(self, entity_id: int) -> Entity | None:
        return self.db.query(Entity).filter(Entity.id == entity_id).first()

    def update(self, entity_id: int, **kwargs) -> Entity | None:
        entity = self.get_by_id(entity_id)
        if not entity:
            return None
        for key, value in kwargs.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def update_selection(self, project_id: int, selected_names: list[str]) -> None:
        entities = self.get_by_project(project_id)
        for entity in entities:
            entity.selected = entity.name in selected_names
        self.db.commit()

    def delete_by_project(self, project_id: int) -> int:
        count = self.db.query(Entity).filter(Entity.project_id == project_id).delete()
        self.db.commit()
        return count
