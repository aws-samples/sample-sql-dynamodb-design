from sqlalchemy import func
from sqlalchemy.orm import Session
from backend.db.models import AccessPattern, WritePattern


class PatternRepository:
    def __init__(self, db: Session):
        self.db = db

    # --- Access Patterns ---

    def create_access_pattern(self, project_id: int, **kwargs) -> AccessPattern:
        pattern = AccessPattern(project_id=project_id, **kwargs)
        self.db.add(pattern)
        self.db.commit()
        self.db.refresh(pattern)
        return pattern

    def bulk_create_access_patterns(self, project_id: int, patterns: list[dict]) -> list[AccessPattern]:
        db_patterns = []
        for data in patterns:
            pattern = AccessPattern(project_id=project_id, **data)
            self.db.add(pattern)
            db_patterns.append(pattern)
        self.db.commit()
        for p in db_patterns:
            self.db.refresh(p)
        return db_patterns

    def get_access_patterns(self, project_id: int) -> list[AccessPattern]:
        return (self.db.query(AccessPattern)
                .filter(AccessPattern.project_id == project_id)
                .order_by(AccessPattern.pattern_id)
                .all())

    def get_access_pattern_by_id(self, pattern_id: int) -> AccessPattern | None:
        return self.db.query(AccessPattern).filter(AccessPattern.id == pattern_id).first()

    def update_access_pattern(self, pattern_id: int, **kwargs) -> AccessPattern | None:
        pattern = self.get_access_pattern_by_id(pattern_id)
        if not pattern:
            return None
        for key, value in kwargs.items():
            if hasattr(pattern, key):
                setattr(pattern, key, value)
        self.db.commit()
        self.db.refresh(pattern)
        return pattern

    def classify_access_patterns(self, project_id: int, selected_entities: set[str]) -> None:
        patterns = self.get_access_patterns(project_id)
        for p in patterns:
            entities = set(p.source_entities or [])
            in_scope = entities & selected_entities
            out_scope = entities - selected_entities
            if not in_scope:
                p.classification = "excluded"
            elif out_scope:
                p.classification = "cross_boundary"
            else:
                p.classification = "in_scope"
        self.db.commit()

    def get_next_access_pattern_id(self, project_id: int) -> str:
        """Return next sequential AP-NNN id for the given project."""
        max_id = (
            self.db.query(func.max(AccessPattern.pattern_id))
            .filter(AccessPattern.project_id == project_id)
            .scalar()
        )
        if max_id:
            next_num = int(max_id.split("-")[1]) + 1
        else:
            next_num = 1
        return f"AP-{next_num:03d}"

    def delete_access_patterns(self, project_id: int) -> int:
        count = self.db.query(AccessPattern).filter(AccessPattern.project_id == project_id).delete()
        self.db.commit()
        return count

    def delete_extractor_access_patterns(self, project_id: int) -> int:
        """Delete only extractor-sourced access patterns for the given project."""
        count = (
            self.db.query(AccessPattern)
            .filter(AccessPattern.project_id == project_id, AccessPattern.source == "extractor")
            .delete()
        )
        self.db.commit()
        return count

    # --- Write Patterns ---

    def create_write_pattern(self, project_id: int, **kwargs) -> WritePattern:
        pattern = WritePattern(project_id=project_id, **kwargs)
        self.db.add(pattern)
        self.db.commit()
        self.db.refresh(pattern)
        return pattern

    def bulk_create_write_patterns(self, project_id: int, patterns: list[dict]) -> list[WritePattern]:
        db_patterns = []
        for data in patterns:
            pattern = WritePattern(project_id=project_id, **data)
            self.db.add(pattern)
            db_patterns.append(pattern)
        self.db.commit()
        for p in db_patterns:
            self.db.refresh(p)
        return db_patterns

    def get_write_patterns(self, project_id: int) -> list[WritePattern]:
        return (self.db.query(WritePattern)
                .filter(WritePattern.project_id == project_id)
                .order_by(WritePattern.pattern_id)
                .all())

    def update_write_pattern(self, pattern_id: int, **kwargs) -> WritePattern | None:
        pattern = self.db.query(WritePattern).filter(WritePattern.id == pattern_id).first()
        if not pattern:
            return None
        for key, value in kwargs.items():
            if hasattr(pattern, key):
                setattr(pattern, key, value)
        self.db.commit()
        self.db.refresh(pattern)
        return pattern

    def classify_write_patterns(self, project_id: int, selected_entities: set[str]) -> None:
        patterns = self.get_write_patterns(project_id)
        for p in patterns:
            entities = set(p.target_entities or [])
            in_scope = entities & selected_entities
            out_scope = entities - selected_entities
            if not in_scope:
                p.classification = "excluded"
            elif out_scope:
                p.classification = "cross_boundary"
            else:
                p.classification = "in_scope"
        self.db.commit()

    def delete_write_patterns(self, project_id: int) -> int:
        count = self.db.query(WritePattern).filter(WritePattern.project_id == project_id).delete()
        self.db.commit()
        return count

    def get_next_write_pattern_id(self, project_id: int) -> str:
        """Return next sequential WP-NNN id for the given project."""
        max_id = (
            self.db.query(func.max(WritePattern.pattern_id))
            .filter(WritePattern.project_id == project_id)
            .scalar()
        )
        if max_id:
            next_num = int(max_id.split("-")[1]) + 1
        else:
            next_num = 1
        return f"WP-{next_num:03d}"

    def delete_user_access_pattern(self, pattern_id: int) -> bool:
        """Delete a single user-sourced access pattern. Returns False if not found or not user-sourced."""
        pattern = self.db.query(AccessPattern).filter(AccessPattern.id == pattern_id, AccessPattern.source == "user").first()
        if not pattern:
            return False
        self.db.delete(pattern)
        self.db.commit()
        return True

    def delete_user_write_pattern(self, pattern_id: int) -> bool:
        """Delete a single user-sourced write pattern. Returns False if not found or not user-sourced."""
        pattern = self.db.query(WritePattern).filter(WritePattern.id == pattern_id, WritePattern.source == "user").first()
        if not pattern:
            return False
        self.db.delete(pattern)
        self.db.commit()
        return True

    def delete_extractor_write_patterns(self, project_id: int) -> int:
        """Delete only extractor-sourced write patterns for the given project."""
        count = (
            self.db.query(WritePattern)
            .filter(WritePattern.project_id == project_id, WritePattern.source == "extractor")
            .delete()
        )
        self.db.commit()
        return count
