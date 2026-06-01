from pydantic import BaseModel, Field
from datetime import datetime


# --- Project ---

class ProjectCreate(BaseModel):
    name: str
    path: str
    aws_profile: str = "default"
    design_priority: str = "balanced"  # performance, balanced, cost
    schema_path: str | None = None  # optional SQL schema file path

class ProjectUpdate(BaseModel):
    name: str | None = None
    path: str | None = None
    aws_profile: str | None = None
    design_priority: str | None = None
    schema_path: str | None = None

class ProjectResponse(BaseModel):
    id: int
    name: str
    path: str
    aws_profile: str | None
    design_priority: str | None
    schema_path: str | None
    created_at: datetime | None
    updated_at: datetime | None
    model_config = {"from_attributes": True}


# --- Entity ---

class EntityResponse(BaseModel):
    id: int
    project_id: int
    name: str
    sql_table: str | None
    average_row_size_kb: float
    fields: str | None
    estimated_field_total_bytes: int | None
    relationships_json: dict | None
    notes: str | None
    selected: bool
    model_config = {"from_attributes": True}

class EntityUpdate(BaseModel):
    average_row_size_kb: float | None = None
    selected: bool | None = None
    notes: str | None = None


# --- Access Pattern ---

class AccessPatternResponse(BaseModel):
    id: int
    project_id: int
    pattern_id: str
    name: str
    operation: str
    source_entities: list[str] | None
    requests_per_hour: int
    avg_items_returned: int
    source_code: str | None
    notes: str | None
    classification: str | None
    source: str | None = None
    model_config = {"from_attributes": True}

class AccessPatternUpdate(BaseModel):
    requests_per_hour: int | None = None
    avg_items_returned: int | None = None
    notes: str | None = None

class AccessPatternCreate(BaseModel):
    name: str
    source_entities: list[str]
    requests_per_hour: int = Field(..., gt=0)
    avg_items_returned: int = 1
    source_code: str | None = None


# --- Write Pattern ---

class WritePatternResponse(BaseModel):
    id: int
    project_id: int
    pattern_id: str
    name: str
    operation: str
    target_entities: list[str] | None
    requests_per_hour: int
    items_per_transaction: int
    source_code: str | None
    notes: str | None
    classification: str | None
    source: str | None = None
    model_config = {"from_attributes": True}

class WritePatternUpdate(BaseModel):
    requests_per_hour: int | None = None
    items_per_transaction: int | None = None
    notes: str | None = None

class WritePatternCreate(BaseModel):
    name: str
    target_entities: list[str]
    requests_per_hour: int = Field(..., gt=0)
    items_per_transaction: int = 1
    source_code: str | None = None


# --- Migration Scope ---

class MigrationScopeRequest(BaseModel):
    mode: str  # full, microservice, hybrid
    selected_entities: list[str]

class MigrationScopeResponse(BaseModel):
    id: int
    project_id: int
    mode: str
    selected_entities: list[str] | None
    excluded_entities: list[str] | None
    model_config = {"from_attributes": True}


# --- Pipeline ---

class PipelineRunRequest(BaseModel):
    extract: bool = False
    model: bool = True
    validate_phase: bool = True
    metrics: bool = True

class PipelineRunResponse(BaseModel):
    id: int
    project_id: int
    status: str
    phases_config: dict | None
    current_phase: int
    total_phases: int
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    model_config = {"from_attributes": True}

class PipelineResultResponse(BaseModel):
    id: int
    run_id: int
    phase: int
    phase_name: str | None
    output_type: str | None
    content: str | None
    created_at: datetime | None
    model_config = {"from_attributes": True}


# --- Model Override ---

class ModelOverrideCreate(BaseModel):
    entity_name: str
    override_type: str  # separate, flatten, custom_key, custom_gsi
    description: str
    details: dict | None = None

class ModelOverrideUpdate(BaseModel):
    description: str | None = None
    active: bool | None = None
    details: dict | None = None

class ModelOverrideResponse(BaseModel):
    id: int
    project_id: int
    entity_name: str
    override_type: str
    description: str
    details: dict | None
    active: bool
    created_at: datetime | None
    model_config = {"from_attributes": True}


# --- Validation ---

class ValidationResult(BaseModel):
    valid: bool
    reason: str | None = None
