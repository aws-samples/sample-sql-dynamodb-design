from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

Base = declarative_base()


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    path = Column(String(500), nullable=False)
    aws_profile = Column(String(100), default="default")
    design_priority = Column(String(20), default="balanced")  # performance, balanced, cost
    schema_path = Column(String(500), nullable=True)  # optional path to SQL schema file (DDL, stored procs, triggers)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    entities = relationship("Entity", back_populates="project", cascade="all, delete-orphan")
    access_patterns = relationship("AccessPattern", back_populates="project", cascade="all, delete-orphan")
    write_patterns = relationship("WritePattern", back_populates="project", cascade="all, delete-orphan")
    migration_scope = relationship("MigrationScope", back_populates="project", uselist=False, cascade="all, delete-orphan")
    pipeline_runs = relationship("PipelineRun", back_populates="project", cascade="all, delete-orphan")
    model_overrides = relationship("ModelOverride", back_populates="project", cascade="all, delete-orphan")


class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(String(100), nullable=False)
    sql_table = Column(String(100))
    average_row_size_kb = Column(Float, default=0.5)
    fields = Column(Text)
    estimated_field_total_bytes = Column(Integer)
    relationships_json = Column(JSON)
    notes = Column(Text)
    selected = Column(Boolean, default=True)

    project = relationship("Project", back_populates="entities")


class AccessPattern(Base):
    __tablename__ = "access_patterns"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    pattern_id = Column(String(10), nullable=False)  # AP-001
    name = Column(String(255), nullable=False)
    operation = Column(String(10), default="READ")
    source_entities = Column(JSON)  # ["User", "Profile"]
    requests_per_hour = Column(Integer, default=0)
    avg_items_returned = Column(Integer, default=1)
    source_code = Column(Text)
    notes = Column(Text)
    source = Column(String(20), default="extractor")  # "extractor" or "user"
    classification = Column(String(20))  # in_scope, cross_boundary, excluded

    project = relationship("Project", back_populates="access_patterns")


class WritePattern(Base):
    __tablename__ = "write_patterns"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    pattern_id = Column(String(10), nullable=False)  # WP-001
    name = Column(String(255), nullable=False)
    operation = Column(String(10), default="WRITE")
    target_entities = Column(JSON)  # ["Order", "OrderItem"]
    requests_per_hour = Column(Integer, default=0)
    items_per_transaction = Column(Integer, default=1)
    source_code = Column(Text)
    notes = Column(Text)
    source = Column(String(20), default="extractor")  # "extractor" or "user"
    classification = Column(String(20))

    project = relationship("Project", back_populates="write_patterns")


class MigrationScope(Base):
    __tablename__ = "migration_scopes"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, unique=True)
    mode = Column(String(20), default="full")  # full, microservice, hybrid
    selected_entities = Column(JSON)  # ["User", "Product", ...]
    excluded_entities = Column(JSON)

    project = relationship("Project", back_populates="migration_scope")


class ModelOverride(Base):
    __tablename__ = "model_overrides"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    entity_name = Column(String(100), nullable=False)
    override_type = Column(String(50), nullable=False)  # separate, flatten, custom_key, custom_gsi
    description = Column(Text, nullable=False)  # Human-readable description of the override
    details = Column(JSON)  # Structured details (e.g., {"related_entity": "Profile", "reason": "..."})
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="model_overrides")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    status = Column(String(20), default="pending")  # pending, running, completed, failed
    phases_config = Column(JSON)  # {"extract": true, "model": true, ...}
    current_phase = Column(Integer, default=0)
    total_phases = Column(Integer, default=4)
    error_message = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    project = relationship("Project", back_populates="pipeline_runs")
    results = relationship("PipelineResult", back_populates="run", cascade="all, delete-orphan")


class PipelineResult(Base):
    __tablename__ = "pipeline_results"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("pipeline_runs.id"), nullable=False)
    phase = Column(Integer, nullable=False)  # 1-4
    phase_name = Column(String(50))  # extract, model, validate, metrics
    output_type = Column(String(50))  # access_patterns_md, model_md, model_json, validation_md, capacity_md
    content = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    run = relationship("PipelineRun", back_populates="results")
