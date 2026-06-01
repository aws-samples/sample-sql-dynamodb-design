import axios from 'axios';

const api = axios.create({ baseURL: '/api' });

// --- Types ---

export interface Project {
  id: number;
  name: string;
  path: string;
  aws_profile: string | null;
  design_priority: string | null;
  schema_path: string | null;
  created_at: string;
}

export interface Entity {
  id: number;
  project_id: number;
  name: string;
  sql_table: string | null;
  average_row_size_kb: number;
  fields: string | null;
  estimated_field_total_bytes: number | null;
  relationships_json: Record<string, string> | null;
  notes: string | null;
  selected: boolean;
}

export interface AccessPattern {
  id: number;
  project_id: number;
  pattern_id: string;
  name: string;
  operation: string;
  source_entities: string[];
  requests_per_hour: number;
  avg_items_returned: number;
  source_code: string | null;
  notes: string | null;
  classification: string | null;
  source: string | null;
}

export interface WritePattern {
  id: number;
  project_id: number;
  pattern_id: string;
  name: string;
  operation: string;
  target_entities: string[];
  requests_per_hour: number;
  items_per_transaction: number;
  source_code: string | null;
  notes: string | null;
  classification: string | null;
  source: string | null;
}

export interface AccessPatternCreate {
  name: string;
  source_entities: string[];
  requests_per_hour: number;
  avg_items_returned?: number;
  source_code?: string;
}

export interface WritePatternCreate {
  name: string;
  target_entities: string[];
  requests_per_hour: number;
  items_per_transaction?: number;
  source_code?: string;
}

export interface MigrationScope {
  id: number;
  project_id: number;
  mode: string;
  selected_entities: string[];
  excluded_entities: string[];
}

export interface PipelineRun {
  id: number;
  project_id: number;
  status: string;
  phases_config: Record<string, boolean>;
  current_phase: number;
  total_phases: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface PipelineResult {
  id: number;
  run_id: number;
  phase: number;
  phase_name: string;
  output_type: string;
  content: string;
}

export interface ModelOverride {
  id: number;
  project_id: number;
  entity_name: string;
  override_type: string;
  description: string;
  details: Record<string, any> | null;
  active: boolean;
  created_at: string;
}

// --- API calls ---

export const projectsApi = {
  list: () => api.get<Project[]>('/projects'),
  create: (data: { name: string; path: string; aws_profile: string; design_priority?: string; schema_path?: string | null }) => api.post<Project>('/projects', data),
  get: (id: number) => api.get<Project>(`/projects/${id}`),
  delete: (id: number) => api.delete(`/projects/${id}`),
  awsProfiles: () => api.get<string[]>('/projects/utils/aws-profiles'),
  browseDirs: (path: string, includeFiles?: string) => api.get<{ current: string; parent: string; dirs: { name: string; path: string }[]; files?: { name: string; path: string }[] }>('/projects/utils/browse-dirs', { params: { path, include_files: includeFiles || '' } }),
  validateBedrock: (profile: string, region?: string) =>
    api.post<{
      profile: string; region: string; credentials_valid: boolean; account_id?: string; ready: boolean;
      models: Record<string, { model_id: string; accessible: boolean; used_by: string; required: boolean; error: string | null }>;
      instructions: string[];
    }>('/projects/utils/validate-bedrock', null, { params: { profile, region: region || 'us-east-1' } }),
};

export const entitiesApi = {
  list: (projectId: number) => api.get<Entity[]>(`/projects/${projectId}/entities`),
  update: (projectId: number, entityId: number, data: Partial<Entity>) =>
    api.patch<Entity>(`/projects/${projectId}/entities/${entityId}`, data),
  updateSelection: (projectId: number, names: string[]) =>
    api.put(`/projects/${projectId}/entities/selection`, names),
};

export const patternsApi = {
  listAccess: (projectId: number, classification?: string) =>
    api.get<AccessPattern[]>(`/projects/${projectId}/patterns/access`, { params: { classification } }),
  createAccess: (projectId: number, data: AccessPatternCreate) =>
    api.post<AccessPattern>(`/projects/${projectId}/patterns/access`, data),
  updateAccess: (projectId: number, patternId: number, data: Partial<AccessPattern>) =>
    api.patch<AccessPattern>(`/projects/${projectId}/patterns/access/${patternId}`, data),
  listWrite: (projectId: number, classification?: string) =>
    api.get<WritePattern[]>(`/projects/${projectId}/patterns/write`, { params: { classification } }),
  createWrite: (projectId: number, data: WritePatternCreate) =>
    api.post<WritePattern>(`/projects/${projectId}/patterns/write`, data),
  updateWrite: (projectId: number, patternId: number, data: Partial<WritePattern>) =>
    api.patch<WritePattern>(`/projects/${projectId}/patterns/write/${patternId}`, data),
  deleteAccess: (projectId: number, patternId: number) =>
    api.delete(`/projects/${projectId}/patterns/access/${patternId}`),
  deleteWrite: (projectId: number, patternId: number) =>
    api.delete(`/projects/${projectId}/patterns/write/${patternId}`),
};

export const scopeApi = {
  get: (projectId: number) => api.get<MigrationScope>(`/projects/${projectId}/scope`),
  set: (projectId: number, data: { mode: string; selected_entities: string[] }) =>
    api.put<MigrationScope>(`/projects/${projectId}/scope`, data),
};

export const pipelineApi = {
  extractUrl: (projectId: number) =>
    `/api/projects/${projectId}/pipeline/extract`,
  createRun: (projectId: number, phases: { extract: boolean; model: boolean; validate_phase: boolean; metrics: boolean }) =>
    api.post<PipelineRun>(`/projects/${projectId}/pipeline/run`, phases),
  getRun: (projectId: number, runId: number) =>
    api.get<PipelineRun>(`/projects/${projectId}/pipeline/run/${runId}`),
  getResults: (projectId: number, runId: number) =>
    api.get<PipelineResult[]>(`/projects/${projectId}/pipeline/run/${runId}/results`),
  listRuns: (projectId: number) =>
    api.get<PipelineRun[]>(`/projects/${projectId}/pipeline/runs`),
  streamUrl: (projectId: number, runId: number) =>
    `/api/projects/${projectId}/pipeline/run/${runId}/stream`,
  getLatestResult: (projectId: number, outputType: string) =>
    api.get<PipelineResult>(`/projects/${projectId}/pipeline/results/latest/${outputType}`),
  getConsensusReport: (projectId: number) =>
    api.get<PipelineResult>(`/projects/${projectId}/pipeline/results/latest/consensus_report`),
  importFiles: (projectId: number) =>
    api.post<{ imported: string[]; run_id: number }>(`/projects/${projectId}/pipeline/import-files`),
  listLogs: (projectId: number) =>
    api.get<{ logs: { filename: string; size_bytes: number; modified: number }[] }>(`/projects/${projectId}/pipeline/logs`),
  downloadLogUrl: (projectId: number, filename: string) =>
    `/api/projects/${projectId}/pipeline/logs/${filename}`,
  getSummary: (projectId: number) =>
    api.get<{ entities: number; access_patterns: number; write_patterns: number; last_extract_completed_at: string | null; confidence_score: number | null; rounds_executed: number | null; has_data: boolean }>(`/projects/${projectId}/pipeline/summary`),
};

export const overridesApi = {
  list: (projectId: number, activeOnly: boolean = true) =>
    api.get<ModelOverride[]>(`/projects/${projectId}/overrides`, { params: { active_only: activeOnly } }),
  create: (projectId: number, data: { entity_name: string; override_type: string; description: string; details?: Record<string, any> }) =>
    api.post<ModelOverride>(`/projects/${projectId}/overrides`, data),
  update: (projectId: number, overrideId: number, data: Partial<ModelOverride>) =>
    api.patch<ModelOverride>(`/projects/${projectId}/overrides/${overrideId}`, data),
  delete: (projectId: number, overrideId: number) =>
    api.delete(`/projects/${projectId}/overrides/${overrideId}`),
};

export const logApi = {
  getLevel: () => api.get<{ level: string }>('/log-level'),
  setLevel: (level: string) => api.post<{ level: string }>(`/log-level?level=${level}`),
};
