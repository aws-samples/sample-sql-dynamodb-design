from sqlalchemy.orm import Session
from backend.db.models import Project


class ProjectRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, name: str, path: str, aws_profile: str = "default", design_priority: str = "balanced", schema_path: str | None = None) -> Project:
        project = Project(name=name, path=path, aws_profile=aws_profile, design_priority=design_priority, schema_path=schema_path)
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def get_by_id(self, project_id: int) -> Project | None:
        return self.db.query(Project).filter(Project.id == project_id).first()

    def get_all(self) -> list[Project]:
        return self.db.query(Project).order_by(Project.created_at.desc()).all()

    def update(self, project_id: int, **kwargs) -> Project | None:
        project = self.get_by_id(project_id)
        if not project:
            return None
        for key, value in kwargs.items():
            if hasattr(project, key):
                setattr(project, key, value)
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete(self, project_id: int) -> bool:
        project = self.get_by_id(project_id)
        if not project:
            return False
        self.db.delete(project)
        self.db.commit()
        return True
