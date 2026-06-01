import { useState, useEffect, useCallback, useMemo } from 'react';
import { pipelineApi, overridesApi, ModelOverride, entitiesApi, Entity, projectsApi, Project } from '../api/client';

interface Props { projectId: number; runId?: number | null; }
interface CapacityApproach {
  itemSizeKB?: number; parentItemSizeKB?: number; childItemSizeKB?: number; avgChildCount?: number;
  rcuPerRead: number; wcuPerWrite?: number; wcuPerParentWrite?: number; wcuPerChildWrite?: number;
  readsPerHour: number; writesPerHour?: number; parentWritesPerHour?: number; childWritesPerHour?: number;
  totalRcuPerHour: number; totalWcuPerHour: number;
  rcuFormula?: string; wcuFormula?: string; apiCallsPerRead?: number;
}
interface KeyAlternative {
  pkPattern: string; skPattern?: string; description: string;
  pros: string[]; cons: string[];
  estimatedRcuPerHour?: number; estimatedWcuPerHour?: number;
  accessPatterns?: string[];
}
interface KeyDesignAnalysis {
  chosenPK: string; chosenSK?: string;
  alternatives: KeyAlternative[];
  justification: string;
}
interface CapacityAnalysis {
  singleItemApproach?: CapacityApproach; verticalPartitionApproach?: CapacityApproach;
  keyDesignAnalysis?: KeyDesignAnalysis;
  recommendation: string; rationale: string; rcuSavings?: string; wcuSavings?: string;
  priorityRulesApplied?: string[];
}
interface KeyJustificationAlternative {
  keyPattern: string; description: string;
  accessPatterns: string[]; pros: string[]; cons: string[];
  estimatedCostImpact?: string;
}
interface KeyJustification {
  chosen: string; rationale: string;
  accessPatternsDriving: string[];
  alternatives: KeyJustificationAlternative[];
  priorityRulesApplied?: string[];
}
interface KeyDesignJustification {
  pk: KeyJustification;
  sk?: KeyJustification;
}
interface EntityMapping {
  description: string; keyMappings: Record<string, string>; attributes: string[] | Record<string, any>;
  notes: string; estimatedSizeKB: number; capacityAnalysis?: CapacityAnalysis;
  keyDesignJustification?: KeyDesignJustification;
}
interface AccessPatternMap {
  name: string; index: string; pk: string; sk_condition: string; filter: string; note: string;
  original_code?: string; dynamodb_query?: string; dynamodb_query_csharp?: string;
  key_expression?: string; filter_expression?: string; client_side_filter?: string; performance_notes?: string;
  complexity?: string; complexity_rationale?: string;
  dynamodb_limitations?: string;
  rcu_per_request?: number; wcu_per_request?: number;
  items_scanned?: number; items_returned?: number;
  requests_per_hour?: number; estimated_rcu_per_hour?: number; estimated_wcu_per_hour?: number;
  migration_notes?: string; performance_impact?: string;
}
interface GSI {
  indexName: string; partitionKey: string; sortKey: string; projectionType: string;
  projectedAttributes?: string[]; projectionRationale?: string; servedPatterns?: string[];
}
interface DynamoModel {
  tableName: string; billingMode: string;
  primaryKey: { partitionKey: string; sortKey: string };
  gsis: GSI[]; entityMappings: Record<string, EntityMapping>;
  accessPatternMapping: Record<string, AccessPatternMap>;
}
const OUTPUT_TYPES = [
  { key: 'model_md', label: 'DynamoDB Model' }, { key: 'model_json', label: 'Model JSON' },
  { key: 'validation_md', label: 'Validation Report' }, { key: 'capacity_md', label: 'Capacity Analysis' },
  { key: 'access_patterns_md', label: 'Access Patterns' },
];

const HELP_TIPS: Record<string, string> = {
  gsi: 'Global Secondary Index — an alternate key structure that enables queries on non-primary-key attributes. GSI Overloading means reusing the same GSI for multiple entity types by storing different data in the same PK/SK attributes.',
  projection: 'Controls which attributes are copied from the base table to the GSI. KEYS_ONLY = minimal cost, INCLUDE = selected attributes, ALL = full copy (highest write cost). Default should be INCLUDE to minimize write amplification.',
  rcu: 'Read Capacity Unit — 1 RCU = one strongly consistent read (4KB) or two eventually consistent reads (4KB each). Formula: ceil(item_size_kb / 4) × 0.5 for eventually consistent. ANY item ≤ 4 KB = 0.5 RCU (not 1 RCU). Example: 0.9 KB → ceil(0.225) = 1 → 1 × 0.5 = 0.5 RCU. Total RCU/hr = RCU_per_read × reads_per_hour.',
  wcu: 'Write Capacity Unit — 1 WCU = one write up to 1KB. Updates rewrite the entire item. Formula: ceil(item_size_kb / 1). GSI writes add extra WCU cost (write amplification).',
  flatten: 'Flattening merges two 1:1 related entities into a single DynamoDB item, reducing read costs (one query instead of two) but increasing write costs (entire combined item rewritten on any update).',
  complexity: 'Easy = direct key/index lookup. Medium = requires FilterExpression or moderate client-side processing. Hard = requires scan, multi-query join, or heavy client-side processing.',
  keyExpr: 'KeyConditionExpression — the efficient part of a DynamoDB query. Only reads items matching this condition. Supports: =, <, >, <=, >=, BETWEEN, begins_with() on sort key. Does NOT support OR, IN, CONTAINS.',
  filterExpr: 'FilterExpression — applied AFTER reading all items matching the key condition. Still consumes RCUs for all scanned items, but only returns matching ones. Use sparingly on high-frequency patterns.',
  singleTable: 'Single-table design stores multiple entity types in one DynamoDB table using overloaded PK/SK. Reduces API calls, enables transactions across entities, and simplifies infrastructure.',
  writeAmplification: 'Every write to the base table that changes a GSI key or projected attribute triggers a write to that GSI. With ALL projection, every base table write triggers a GSI write. Minimize projections to reduce cost.',
  verticalPartition: 'Vertical partitioning stores related entities as separate items with the same PK but different SK prefixes. Enables independent updates and fine-grained access, but requires multiple reads to fetch all related data.',
};

function HelpTip({ tip }: { tip: string }) {
  const text = HELP_TIPS[tip] || tip;
  return <span title={text} style={{ cursor: 'help', marginLeft: 4, fontSize: '0.75rem', color: 'var(--text-muted)', verticalAlign: 'middle' }}>ℹ️</span>;
}

const DISCLAIMER = '⚠️ These results are AI-generated estimates. Thorough review by a DynamoDB expert is required before using in production. RCU/WCU calculations, modeling decisions, and migration strategies should be validated against actual workload patterns.';

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className="modal-content" onMouseDown={e => e.stopPropagation()}>
        <div className="modal-header">
          <strong style={{ fontSize: '1rem' }}>{title}</strong>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.2rem' }}>&#x2715;</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

interface CapacitySection { title: string; content: string; }
function getEntityCapacitySections(raw: string, entityName: string): CapacitySection[] {
  if (!raw) return [];
  const sections: CapacitySection[] = [];
  const headingRegex = /^(#{2,3})\s+(.+)$/gm;
  const allSections: { title: string; body: string }[] = [];
  let lastIdx = 0, lastTitle = '';
  let match: RegExpExecArray | null;
  while ((match = headingRegex.exec(raw)) !== null) {
    if (lastTitle) allSections.push({ title: lastTitle, body: raw.slice(lastIdx, match.index).trim() });
    lastTitle = match[2]; lastIdx = match.index + match[0].length;
  }
  if (lastTitle) allSections.push({ title: lastTitle, body: raw.slice(lastIdx).trim() });
  const escaped = entityName.replace(/[.*+?^${}()|[\]\\]/g, (ch) => '\\' + ch);
  const wordBoundaryRegex = new RegExp('\\b' + escaped + '\\b', 'i');
  for (const s of allSections) {
    if (wordBoundaryRegex.test(s.title)) {
      sections.push({ title: s.title, content: s.body });
    }
  }
  return sections;
}

function formatInlineMarkdown(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const boldRegex = /\*\*(.+?)\*\*/g;
  let lastIndex = 0, m: RegExpExecArray | null, key = 0;
  while ((m = boldRegex.exec(text)) !== null) {
    if (m.index > lastIndex) parts.push(text.slice(lastIndex, m.index));
    parts.push(<strong key={key++}>{m[1]}</strong>);
    lastIndex = m.index + m[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts.length > 1 ? <>{parts}</> : text;
}

interface ParsedMdTable { headers: string[]; rows: string[][]; }
function parseMarkdownTable(text: string): ParsedMdTable | null {
  const lines = text.split('\n').filter(l => l.trim().startsWith('|'));
  if (lines.length < 2) return null;
  const splitRow = (line: string) => line.split('|').map(c => c.trim()).filter((_, i, arr) => i > 0 && i < arr.length);
  const headers = splitRow(lines[0]);
  const rows = lines.slice(2).map(splitRow);
  return { headers, rows };
}

/** Render markdown content but optionally SKIP comparison tables and their related headings (replaced by JSON-driven UI) */
function renderMarkdownContent(text: string, skipComparisonTable: boolean = false): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const lines = text.split('\n');
  let i = 0;
  let skipUntilNextHeading = false;
  while (i < lines.length) {
    const line = lines[i];

    // When skipping comparison content, hide "Capacity Comparison Table", "Recommendation", and "Total Capacity" sections
    if (skipComparisonTable && line.trim().startsWith('#')) {
      const headingText = line.replace(/^#+\s*/, '').toLowerCase();
      if (headingText.includes('capacity comparison') || headingText.includes('recommendation') || headingText.includes('total capacity')) {
        skipUntilNextHeading = true;
        i++;
        continue;
      } else {
        skipUntilNextHeading = false;
      }
    }
    if (skipUntilNextHeading) { i++; continue; }

    if (line.trim().startsWith('|')) {
      const tl: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) { tl.push(lines[i]); i++; }
      if (skipUntilNextHeading) continue;
      const table = parseMarkdownTable(tl.join('\n'));
      if (table) {
        const isComparisonTable = skipComparisonTable && table.headers.some(h =>
          h.toLowerCase().includes('single item') || h.toLowerCase().includes('vertical partition')
        );
        if (!isComparisonTable) {
          nodes.push(
            <table key={'tbl-' + i} className="data-table" style={{ fontSize: '0.8rem', marginBottom: 12 }}>
              <thead><tr>{table.headers.map((h, hi) => <th key={hi}>{h}</th>)}</tr></thead>
              <tbody>{table.rows.map((row, ri) => (<tr key={ri}>{row.map((cell, ci) => <td key={ci}>{formatInlineMarkdown(cell)}</td>)}</tr>))}</tbody>
            </table>
          );
        }
      }
      continue;
    }
    if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {
      const items: string[] = [];
      while (i < lines.length && (lines[i].trim().startsWith('- ') || lines[i].trim().startsWith('* '))) { items.push(lines[i].trim().replace(/^[-*]\s+/, '')); i++; }
      if (!skipUntilNextHeading) nodes.push(<ul key={'ul-' + i} style={{ paddingLeft: '1.25rem', margin: '0.25rem 0' }}>{items.map((item, idx) => <li key={idx} style={{ fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.6 }}>{formatInlineMarkdown(item)}</li>)}</ul>);
      continue;
    }
    if (line.trim().startsWith('#')) { nodes.push(<h4 key={'h-' + i} style={{ fontSize: '0.85rem', marginTop: 8, marginBottom: 4 }}>{line.replace(/^#+\s*/, '')}</h4>); i++; continue; }
    if (!line.trim()) { i++; continue; }
    nodes.push(<p key={'p-' + i} style={{ fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: 4 }}>{formatInlineMarkdown(line)}</p>);
    i++;
  }
  return nodes;
}

export default function Results({ projectId, runId }: Props) {
  const [activeTab, setActiveTab] = useState('data_model');
  const [results, setResults] = useState<Record<string, string>>({});
  const [model, setModel] = useState<DynamoModel | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedEntity, setExpandedEntity] = useState<string | null>(null);
  const [expandedAP, setExpandedAP] = useState<string | null>(null);
  const [modalEntity, setModalEntity] = useState<string | null>(null);
  const [modalAP, setModalAP] = useState<string | null>(null);
  const [modalKeyJustification, setModalKeyJustification] = useState<{ entity: string; keyType: 'pk' | 'sk' } | null>(null);
  const [overrides, setOverrides] = useState<ModelOverride[]>([]);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [showOverrideForm, setShowOverrideForm] = useState(false);
  const [newOverride, setNewOverride] = useState({ entity_name: '', override_type: 'separate', description: '' });
  const [currentRunId, setCurrentRunId] = useState<number | null>(runId || null);
  const [project, setProject] = useState<Project | null>(null);

  const parseModelJson = useCallback((jsonStr: string): DynamoModel | null => {
    if (!jsonStr) return null;
    try { return JSON.parse(jsonStr); } catch {}
    try {
      const repaired = jsonStr.replace(/\\\\"/g, '\\\\"').replace(/\\\\\\\\"/g, '\\\\"');
      return JSON.parse(repaired);
    } catch {}
    try {
      const start = jsonStr.indexOf('{');
      const cleaned = jsonStr.slice(start)
        .replace(/"dynamodb_query_csharp"\s*:\s*"[^"]*(?:\\.[^"]*)*"/g, (m) => {
          try { JSON.parse('{' + m + '}'); return m; } catch { return '"dynamodb_query_csharp": "(see dynamo_model.md)"'; }
        })
        .replace(/"dynamodb_query"\s*:\s*"[^"]*(?:\\.[^"]*)*"/g, (m) => {
          try { JSON.parse('{' + m + '}'); return m; } catch { return '"dynamodb_query": "(see dynamo_model.md)"'; }
        })
        .replace(/"original_code"\s*:\s*"[^"]*(?:\\.[^"]*)*"/g, (m) => {
          try { JSON.parse('{' + m + '}'); return m; } catch { return '"original_code": "(see access_patterns.md)"'; }
        });
      return JSON.parse(cleaned);
    } catch { return null; }
  }, []);

  const loadRunResults = useCallback(async (targetRunId: number) => {
    setLoading(true);
    setCurrentRunId(targetRunId);
    try {
      const { data: runResults } = await pipelineApi.getResults(projectId, targetRunId);
      const r: Record<string, string> = {};
      for (const res of runResults) {
        if (res.output_type && res.content) r[res.output_type] = res.content;
      }
      setResults(r);
      setModel(parseModelJson(r.model_json || ''));
    } catch { setResults({}); setModel(null); }
    // Batch remaining API calls with Promise.all (single round-trip, single re-render)
    const [ovRes, enRes, projRes] = await Promise.all([
      overridesApi.list(projectId).catch(() => ({ data: [] as ModelOverride[] })),
      entitiesApi.list(projectId).catch(() => ({ data: [] as Entity[] })),
      projectsApi.get(projectId).catch(() => ({ data: null as Project | null })),
    ]);
    setOverrides(ovRes.data);
    setEntities(enRes.data);
    setProject(projRes.data);
    setLoading(false);
  }, [projectId, parseModelJson]);

  useEffect(() => {
    const init = async () => {
      setLoading(true);

      // If a specific runId was passed, load that directly
      if (runId) {
        await loadRunResults(runId);
        return;
      }

      // Otherwise find the latest completed pipeline run
      let allRuns: any[] = [];
      try { const { data } = await pipelineApi.listRuns(projectId); allRuns = data; } catch {}

      // If no runs in DB, try importing from disk files
      if (allRuns.length === 0) {
        try {
          const { data: importResult } = await pipelineApi.importFiles(projectId);
          if (importResult.imported.length > 0) {
            try { const { data } = await pipelineApi.listRuns(projectId); allRuns = data; } catch {}
          }
        } catch {}
      }

      const pipelineRuns = allRuns.filter((r: any) => r.phases_config?.model && r.status === 'completed');
      if (pipelineRuns.length > 0) {
        await loadRunResults(pipelineRuns[0].id);
      } else {
        setLoading(false);
      }
    };
    init();
  }, [projectId, runId, loadRunResults]);

  const getMigrationDifficulty = (ap: AccessPatternMap): { label: string; cls: string } => {
    // Use the complexity field from JSON if available (set by LLM or post-processing)
    const complexity = ap.complexity?.toLowerCase() || '';
    if (complexity === 'hard' || complexity === 'not possible' || complexity.includes('not possible'))
      return { label: 'Hard', cls: 'badge-danger' };
    if (complexity === 'medium') return { label: 'Medium', cls: 'badge-warning' };
    if (complexity === 'easy') return { label: 'Easy', cls: 'badge-success' };

    // Fallback heuristic if complexity field not set
    const idx = ap.index?.toLowerCase() || '';
    const clientSide = ap.client_side_filter?.toLowerCase() || '';
    const filter = ap.filter?.toLowerCase() || '';
    if (idx.includes('scan') || idx.includes('opensearch') || idx.includes('n/a'))
      return { label: 'Hard', cls: 'badge-danger' };
    if (clientSide && clientSide !== 'none') return { label: 'Medium', cls: 'badge-warning' };
    if (filter.includes('or') || filter.includes('contains') || ap.note?.includes('client-side'))
      return { label: 'Medium', cls: 'badge-warning' };
    return { label: 'Easy', cls: 'badge-success' };
  };
  const openEntityModal = useCallback((name: string) => { setModalEntity(name); }, []);
  const openAPModal = useCallback((id: string) => { setModalAP(id); }, []);

  const handleExportPDF = () => {
    const content = ['# SQL to DynamoDB Design Mentor Migration Report\n',
      '> ⚠️ AI-generated estimates. Thorough review by a DynamoDB expert is required before production use.\n',
      '## DynamoDB Data Model\n', results.model_md || '',
      '\n## Validation Report\n', results.validation_md || '', '\n## Capacity Analysis\n', results.capacity_md || ''].join('\n');
    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'sql-to-dynamodb-design-mentor-migration-report.md'; a.click(); URL.revokeObjectURL(url);
  };
  const handleExportSummary = () => {
    if (!model) return;
    const aps = Object.entries(model.accessPatternMapping || {});
    const easy = aps.filter(([,a]) => getMigrationDifficulty(a).label === 'Easy').length;
    const medium = aps.filter(([,a]) => getMigrationDifficulty(a).label === 'Medium').length;
    const hard = aps.filter(([,a]) => getMigrationDifficulty(a).label === 'Hard').length;
    const totalRcu = aps.reduce((sum, [, a]) => sum + (a.estimated_rcu_per_hour || 0), 0);
    const totalWcu = aps.reduce((sum, [, a]) => sum + (a.estimated_wcu_per_hour || 0), 0);
    const summary = [
      '# SQL Server to DynamoDB Migration Proposal\n',
      '> ⚠️ AI-generated estimates. Expert review required before production use.\n',
      `## Overview\n- Single-table: ${model.tableName}, ${model.billingMode}, ${model.gsis.length} GSIs`,
      `- ${Object.keys(model.entityMappings).length} entities, ${aps.length} access patterns`,
      `- Migration complexity: Easy: ${easy}, Medium: ${medium}, Hard: ${hard}`,
      `- Estimated capacity: ${totalRcu.toLocaleString()} RCU/hr, ${totalWcu.toLocaleString()} WCU/hr\n`,
      '## Entity Mappings\n',
      ...Object.entries(model.entityMappings).map(([name, e]) =>
        `### ${name}\n${e.description}\n- Size: ${e.estimatedSizeKB} KB\n- Notes: ${e.notes}\n`
      ),
      '## Access Pattern Summary\n',
      '| Pattern | Complexity | Index | RCU/hr | WCU/hr |',
      '|---------|-----------|-------|--------|--------|',
      ...aps.map(([id, a]) => `| ${id}: ${a.name} | ${getMigrationDifficulty(a).label} | ${a.index} | ${(a.estimated_rcu_per_hour || 0).toLocaleString()} | ${(a.estimated_wcu_per_hour || 0).toLocaleString()} |`),
    ].join('\n');
    const blob = new Blob([summary], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'sql-to-dynamodb-design-mentor-migration-proposal.md'; a.click(); URL.revokeObjectURL(url);
  };
  const handleAddOverride = async () => {
    if (!newOverride.entity_name || !newOverride.description) return;
    try {
      const { data } = await overridesApi.create(projectId, { entity_name: newOverride.entity_name, override_type: newOverride.override_type, description: newOverride.description });
      setOverrides(prev => [data, ...prev]); setNewOverride({ entity_name: '', override_type: 'separate', description: '' }); setShowOverrideForm(false);
    } catch {}
  };
  const handleDeleteOverride = async (id: number) => { try { await overridesApi.delete(projectId, id); setOverrides(prev => prev.filter(o => o.id !== id)); } catch {} };
  const handleToggleOverride = async (id: number, active: boolean) => { try { const { data } = await overridesApi.update(projectId, id, { active }); setOverrides(prev => prev.map(o => o.id === id ? data : o)); } catch {} };
  const overrideTypeLabels: Record<string, string> = { separate: 'Separate', flatten: 'Flatten', custom_key: 'Custom Key', custom_gsi: 'Custom GSI' };
  const entityNames = model ? Object.keys(model.entityMappings) : entities.map(e => e.name);
  if (loading) return <div className="card">Loading results...</div>;

  if (!model) return (
    <div>
      <h2>{'\uD83D\uDCCB'} Migration Results</h2>
      <div className="card">
        <p>No results available for this run. The JSON may be malformed or the pipeline did not complete successfully.</p>
        <p className="text-muted" style={{ marginTop: 8 }}>Go to "Run Pipeline" to select a different run or start a new execution.</p>
        {currentRunId && <p className="text-muted" style={{ marginTop: 4 }}>Run #{currentRunId}</p>}
      </div>
      {results.model_md && (
        <details style={{ marginTop: '0.5rem' }}>
          <summary style={{ cursor: 'pointer', color: 'var(--primary)', fontSize: '0.85rem' }}>View raw model markdown</summary>
          <div className="card" style={{ marginTop: '0.5rem' }}><pre style={{ whiteSpace: 'pre-wrap', fontSize: '0.8rem', maxHeight: 400, overflow: 'auto' }}>{results.model_md}</pre></div>
        </details>
      )}
    </div>
  );

  const renderOverridePanel = () => (
    <div className="card" style={{ borderLeft: '3px solid var(--warning)', marginBottom: '1rem' }}>
      <div className="flex-between">
        <div><strong>{'\uD83D\uDD27'} Model Overrides</strong><span className="text-muted" style={{ marginLeft: 8 }}>{overrides.filter(o => o.active).length} active</span></div>
        <button className="btn btn-secondary" style={{ fontSize: '0.8rem' }} onClick={() => setShowOverrideForm(!showOverrideForm)}>{showOverrideForm ? 'Cancel' : '+ Add Override'}</button>
      </div>
      {overrides.length > 0 && (<div style={{ marginTop: '0.75rem' }}>{overrides.map(o => (
        <div key={o.id} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.4rem 0', borderBottom: '1px solid var(--border)', opacity: o.active ? 1 : 0.5 }}>
          <input type="checkbox" checked={o.active} onChange={() => handleToggleOverride(o.id, !o.active)} />
          <span className={'badge ' + (o.override_type === 'separate' ? 'badge-warning' : 'badge-success')} style={{ fontSize: '0.7rem' }}>{overrideTypeLabels[o.override_type] || o.override_type}</span>
          <strong style={{ fontSize: '0.85rem' }}>{o.entity_name}</strong>
          <span className="text-muted" style={{ flex: 1 }}>{o.description}</span>
          <button onClick={() => handleDeleteOverride(o.id)} style={{ background: 'none', border: 'none', color: 'var(--danger)', cursor: 'pointer' }}>x</button>
        </div>))}</div>)}
      {showOverrideForm && (
        <div style={{ marginTop: '0.75rem', padding: '0.75rem', background: 'var(--bg)', borderRadius: 6, border: '1px solid var(--border)' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginBottom: '0.5rem' }}>
            <div><label className="text-sm" style={{ display: 'block', marginBottom: 4 }}>Entity</label>
              <select value={newOverride.entity_name} onChange={e => setNewOverride(p => ({ ...p, entity_name: e.target.value }))}><option value="">Select entity...</option>{entityNames.map(n => <option key={n} value={n}>{n}</option>)}</select></div>
            <div><label className="text-sm" style={{ display: 'block', marginBottom: 4 }}>Type</label>
              <select value={newOverride.override_type} onChange={e => setNewOverride(p => ({ ...p, override_type: e.target.value }))}><option value="separate">Separate Entities</option><option value="flatten">Flatten / Merge</option><option value="custom_key">Custom Key Design</option><option value="custom_gsi">Custom GSI</option></select></div>
          </div>
          <div style={{ marginBottom: '0.5rem' }}><label className="text-sm" style={{ display: 'block', marginBottom: 4 }}>Description</label>
            <input type="text" value={newOverride.description} onChange={e => setNewOverride(p => ({ ...p, description: e.target.value }))} placeholder="e.g., Separate Profile from User" /></div>
          <button className="btn btn-primary" style={{ fontSize: '0.8rem' }} onClick={handleAddOverride} disabled={!newOverride.entity_name || !newOverride.description}>Add Override</button>
        </div>)}
      {overrides.filter(o => o.active).length > 0 && (<p className="text-muted" style={{ marginTop: '0.5rem', fontSize: '0.8rem' }}>Go to "Run Pipeline" to re-run with these overrides.</p>)}
    </div>
  );

  // Helper: compute RCU formula string for display
  const rcuFormulaStr = (sizeKB: number): string => {
    const div = sizeKB / 4;
    const ceiled = Math.ceil(div);
    const rcu = ceiled * 0.5;
    return `${sizeKB} KB / 4 = ${div.toFixed(3)} → ceil = ${ceiled} → ${ceiled} × 0.5 = ${rcu} RCU`;
  };
  const wcuFormulaStr = (sizeKB: number): string => {
    const wcu = Math.ceil(sizeKB);
    return `ceil(${sizeKB}) = ${wcu} WCU`;
  };
  const computeRcu = (sizeKB: number): number => Math.ceil(sizeKB / 4) * 0.5;
  const computeWcu = (sizeKB: number): number => Math.ceil(sizeKB);

  const renderCapacityComparisonTable = (ca: CapacityAnalysis, entityName: string) => {
    const si = ca.singleItemApproach;
    const vp = ca.verticalPartitionApproach;
    if (!si && !vp) return null;

    // If only one approach exists, show a simple summary
    if (!si || !vp) {
      const approach = si || vp!;
      const label = si ? 'Single Item (Flattened)' : 'Vertical Partition (Separate)';
      return (
        <div style={{ marginBottom: 16 }}>
          <strong className="text-sm">{label}</strong>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginTop: 8 }}>
            <div className="mini-metric"><div className="mini-label">RCU / Read<HelpTip tip="rcu" /></div><div className="mini-value">{approach.rcuPerRead}</div></div>
            <div className="mini-metric"><div className="mini-label">Reads / hr</div><div className="mini-value">{approach.readsPerHour?.toLocaleString()}</div></div>
            <div className="mini-metric"><div className="mini-label">Total RCU / hr</div><div className="mini-value" style={{ color: 'var(--primary)' }}>{approach.totalRcuPerHour?.toLocaleString()}</div></div>
            <div className="mini-metric"><div className="mini-label">Total WCU / hr</div><div className="mini-value" style={{ color: 'var(--warning)' }}>{approach.totalWcuPerHour?.toLocaleString()}</div></div>
          </div>
        </div>
      );
    }

    // Blog-style comparison table
    const siSize = si.itemSizeKB || 0;
    const vpParentSize = vp.parentItemSizeKB || 0;
    const vpChildSize = vp.childItemSizeKB || 0;
    const vpChildCount = vp.avgChildCount || 1;
    const isOneToN = vpChildCount > 1;

    const siRcuFormula = si.rcuFormula || rcuFormulaStr(siSize);
    const vpRcuFormula = vp.rcuFormula || `Parent: ${rcuFormulaStr(vpParentSize)}. Child: ${rcuFormulaStr(vpChildSize * vpChildCount)}`;

    const siIsRecommended = ca.recommendation === 'single_item';
    const vpIsRecommended = ca.recommendation === 'vertical_partition';

    const highlightStyle = (isRec: boolean) => isRec ? { background: 'rgba(40,167,69,0.08)' } : {};

    type Row = { metric: React.ReactNode; single: React.ReactNode; vertical: React.ReactNode };
    const rows: Row[] = [];

    // Row 1: Item size
    rows.push({
      metric: 'Item size',
      single: <span>{siSize} KB {isOneToN ? `(${vpParentSize} KB + ${vpChildCount} × ${vpChildSize} KB)` : `(${vpParentSize} KB + ${vpChildSize} KB)`}</span>,
      vertical: <span>Parent = {vpParentSize} KB, Child = {vpChildSize} KB{isOneToN ? ` (×${vpChildCount})` : ''}</span>,
    });

    // Row 2: API calls
    rows.push({
      metric: `API calls: ${si.readsPerHour?.toLocaleString()} reads/hr`,
      single: <span>{si.apiCallsPerRead || 1} call/read → {((si.apiCallsPerRead || 1) * si.readsPerHour).toLocaleString()}</span>,
      vertical: <span>{vp.apiCallsPerRead || 2} calls/read → {((vp.apiCallsPerRead || 2) * vp.readsPerHour).toLocaleString()}</span>,
    });

    // Row 3: RCU
    rows.push({
      metric: <span>RCU (eventually consistent)<HelpTip tip="rcu" /></span>,
      single: <div><div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 4 }}>{siRcuFormula}</div><strong style={{ color: 'var(--primary)' }}>{si.readsPerHour?.toLocaleString()} × {si.rcuPerRead} = {si.totalRcuPerHour?.toLocaleString()} RCU/hr</strong></div>,
      vertical: <div><div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 4 }}>{vpRcuFormula}</div><strong style={{ color: 'var(--primary)' }}>{vp.readsPerHour?.toLocaleString()} × {vp.rcuPerRead} = {vp.totalRcuPerHour?.toLocaleString()} RCU/hr</strong></div>,
    });

    // Row 4: WCU (parent writes)
    const siWcuWrite = si.wcuPerWrite || computeWcu(siSize);
    const siWritesHr = si.writesPerHour || 0;
    const vpParentWcu = vp.wcuPerParentWrite || computeWcu(vpParentSize);
    const vpParentWritesHr = vp.parentWritesPerHour || 0;
    if (siWritesHr > 0 || vpParentWritesHr > 0) {
      rows.push({
        metric: <span>WCU to update parent<HelpTip tip="wcu" /></span>,
        single: <div><div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 4 }}>{si.wcuFormula || wcuFormulaStr(siSize)}</div><strong style={{ color: 'var(--warning)' }}>{siWritesHr.toLocaleString()} × {siWcuWrite} = {(siWritesHr * siWcuWrite).toLocaleString()} WCU/hr</strong></div>,
        vertical: <div><div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 4 }}>{wcuFormulaStr(vpParentSize)}</div><strong style={{ color: 'var(--warning)' }}>{vpParentWritesHr.toLocaleString()} × {vpParentWcu} = {(vpParentWritesHr * vpParentWcu).toLocaleString()} WCU/hr</strong></div>,
      });
    }

    // Row 5: WCU (child writes) — for vertical partition
    const vpChildWcu = vp.wcuPerChildWrite || computeWcu(vpChildSize);
    const vpChildWritesHr = vp.childWritesPerHour || 0;
    if (vpChildWritesHr > 0) {
      rows.push({
        metric: <span>WCU to update child<HelpTip tip="wcu" /></span>,
        single: <div><div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 4 }}>Must rewrite entire {siSize} KB item</div><strong style={{ color: 'var(--warning)' }}>{vpChildWritesHr.toLocaleString()} × {siWcuWrite} = {(vpChildWritesHr * siWcuWrite).toLocaleString()} WCU/hr</strong></div>,
        vertical: <div><div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 4 }}>{wcuFormulaStr(vpChildSize)}</div><strong style={{ color: 'var(--warning)' }}>{vpChildWritesHr.toLocaleString()} × {vpChildWcu} = {(vpChildWritesHr * vpChildWcu).toLocaleString()} WCU/hr</strong></div>,
      });
    }

    // Row 6: Totals
    rows.push({
      metric: 'Total / hr',
      single: <div><strong style={{ color: 'var(--primary)' }}>{si.totalRcuPerHour?.toLocaleString()} RCU</strong> · <strong style={{ color: 'var(--warning)' }}>{si.totalWcuPerHour?.toLocaleString()} WCU</strong></div>,
      vertical: <div><strong style={{ color: 'var(--primary)' }}>{vp.totalRcuPerHour?.toLocaleString()} RCU</strong> · <strong style={{ color: 'var(--warning)' }}>{vp.totalWcuPerHour?.toLocaleString()} WCU</strong></div>,
    });

    return (
      <div style={{ marginBottom: 16 }}>
        <strong className="text-sm" style={{ display: 'block', marginBottom: 8 }}>
          Capacity Comparison: {entityName}<HelpTip tip="rcu" />
          <span className="text-muted" style={{ fontSize: '0.72rem', marginLeft: 8 }}>
            (<a href="https://aws.amazon.com/blogs/database/sql-to-nosql-modeling-data-in-amazon-dynamodb/" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--primary)' }}>methodology reference</a>)
          </span>
        </strong>
        <table className="data-table" style={{ fontSize: '0.82rem' }}>
          <thead>
            <tr>
              <th style={{ width: '25%' }}>Metric</th>
              <th style={{ width: '37.5%', ...highlightStyle(siIsRecommended) }}>{siIsRecommended ? '✅ ' : ''}Single Item (Flattened)</th>
              <th style={{ width: '37.5%', ...highlightStyle(vpIsRecommended) }}>{vpIsRecommended ? '✅ ' : ''}Vertical Partition (Separate)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                <td style={{ fontWeight: 600, fontSize: '0.8rem' }}>{row.metric}</td>
                <td style={highlightStyle(siIsRecommended)}>{row.single}</td>
                <td style={highlightStyle(vpIsRecommended)}>{row.vertical}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderKeyDesignAnalysis = (kd: KeyDesignAnalysis, entityName: string) => {
    return (
      <div style={{ marginBottom: 16 }}>
        <strong className="text-sm" style={{ display: 'block', marginBottom: 8 }}>
          Partition Key Design: {entityName}
        </strong>
        <div className="card" style={{ padding: '0.6rem 0.75rem', marginBottom: 12, background: 'rgba(40,167,69,0.06)', borderLeft: '3px solid var(--success)' }}>
          <div style={{ fontSize: '0.82rem' }}>
            <strong>Chosen:</strong> PK = <code>{kd.chosenPK}</code>{kd.chosenSK && <span>, SK = <code>{kd.chosenSK}</code></span>}
          </div>
        </div>
        {kd.alternatives.length > 0 && (
          <table className="data-table" style={{ fontSize: '0.82rem' }}>
            <thead>
              <tr>
                <th style={{ width: '20%' }}>PK Alternative</th>
                <th style={{ width: '25%' }}>Access Patterns</th>
                <th style={{ width: '20%' }}>Pros</th>
                <th style={{ width: '20%' }}>Cons</th>
                <th style={{ width: '15%' }}>Est. Cost</th>
              </tr>
            </thead>
            <tbody>
              {kd.alternatives.map((alt, i) => (
                <tr key={i} style={alt.pkPattern === kd.chosenPK ? { background: 'rgba(40,167,69,0.06)' } : {}}>
                  <td><code>{alt.pkPattern}</code>{alt.pkPattern === kd.chosenPK && <span className="badge badge-success" style={{ marginLeft: 4, fontSize: '0.65rem' }}>chosen</span>}</td>
                  <td className="text-muted" style={{ fontSize: '0.75rem' }}>{alt.accessPatterns?.join(', ') || alt.description}</td>
                  <td><ul style={{ margin: 0, paddingLeft: '1rem' }}>{alt.pros.map((p, j) => <li key={j} style={{ fontSize: '0.75rem', color: 'var(--success)' }}>{p}</li>)}</ul></td>
                  <td><ul style={{ margin: 0, paddingLeft: '1rem' }}>{alt.cons.map((c, j) => <li key={j} style={{ fontSize: '0.75rem', color: 'var(--danger)' }}>{c}</li>)}</ul></td>
                  <td className="text-muted" style={{ fontSize: '0.75rem' }}>
                    {alt.estimatedRcuPerHour != null && <div>RCU: {alt.estimatedRcuPerHour.toLocaleString()}/hr</div>}
                    {alt.estimatedWcuPerHour != null && <div>WCU: {alt.estimatedWcuPerHour.toLocaleString()}/hr</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="recommendation-box" style={{ marginTop: 12 }}>
          <strong>{'\u2705'} Design Justification</strong>
          <p style={{ marginTop: 4 }}>{kd.justification}</p>
        </div>
      </div>
    );
  };

  /**
   * Determine if an entity has capacity analysis relevance:
   * - "parent": has flattened child(ren) → shows capacity analysis for the flattened relationship
   * - "child": shares PK with parent (vertical partition) → shows capacity analysis for the separation
   * - "independent": neither parent with flattened children nor child sharing PK → no capacity evaluation
   */
  const getEntityCapacityRole = (entityName: string): 'parent' | 'child' | 'key_design' | 'independent' => {
    const e = model!.entityMappings[entityName];
    if (!e) return 'independent';
    const ca = e.capacityAnalysis;
    // Direct JSON signals
    if (ca?.recommendation === 'single_item') return 'parent';
    if (ca?.recommendation === 'vertical_partition') return 'child';
    if (ca?.recommendation === 'key_design') return 'key_design';
    // Detect child by shared PK: if this entity's PK matches another entity's PK pattern, it's a child (vertical partition)
    const myPK = e.keyMappings?.PK || '';
    if (myPK) {
      for (const [otherName, otherEntity] of Object.entries(model!.entityMappings)) {
        if (otherName === entityName) continue;
        const otherPK = otherEntity.keyMappings?.PK || '';
        // Same PK pattern means they share a partition → one is parent, one is child
        if (otherPK && otherPK === myPK) {
          // The entity with SK starting with METADATA# is typically the parent
          const mySK = e.keyMappings?.SK || '';
          const otherSK = otherEntity.keyMappings?.SK || '';
          if (mySK.startsWith('METADATA#')) {
            // This entity is the parent in this partition — but only if it has flattened children (single_item rec)
            // If no single_item rec, it's just a parent of vertical partition children → independent for capacity purposes
            continue;
          }
          // This entity has a non-METADATA SK prefix → it's a child sharing parent's PK
          return 'child';
        }
      }
    }
    // Check markdown sections as last resort
    const sections = getEntityCapacitySections(results.capacity_md || '', entityName);
    const allEntityNames = Object.keys(model!.entityMappings);
    for (const s of sections) {
      const titleLower = s.title.toLowerCase();
      const otherEntity = allEntityNames.find(n => {
        if (n === entityName) return false;
        const esc = n.replace(/[.*+?^${}()|[\]\\]/g, (ch) => '\\' + ch);
        return new RegExp('\\b' + esc + '\\b', 'i').test(s.title);
      });
      if (!otherEntity) continue;
      const myIdx = titleLower.indexOf(entityName.toLowerCase());
      const otherIdx = titleLower.indexOf(otherEntity.toLowerCase());
      const isFirst = myIdx < otherIdx;
      if (titleLower.includes('vertical') || titleLower.includes('1:n') || titleLower.includes('separate') || titleLower.includes('item collection')) {
        return isFirst ? 'independent' : 'child';
      }
      if (titleLower.includes('flatten') || titleLower.includes('1:1') || titleLower.includes('single')) {
        return isFirst ? 'parent' : 'independent';
      }
    }
    return 'independent';
  };

  const renderEntityModal = () => {
    if (!modalEntity || !model!.entityMappings[modalEntity]) return null;
    const e = model!.entityMappings[modalEntity];
    const ca = e.capacityAnalysis;
    const role = getEntityCapacityRole(modalEntity);

    // Ownership rules for markdown sections from capacity_analysis.md:
    // Rule 1: Child flattened into parent → parent entity owns the section
    // Rule 2: Child separated (same PK, vertical partition) → child entity owns the section
    // Rule 3: Independent entity → no capacity analysis sections
    const capacitySections = getEntityCapacitySections(results.capacity_md || '', modalEntity);
    const allEntityNames = Object.keys(model!.entityMappings);
    const ownedSections = role === 'independent' ? [] : capacitySections.filter(s => {
      const titleLower = s.title.toLowerCase();

      // key_design entities own any section that mentions their name
      if (role === 'key_design') {
        return true; // already filtered by getEntityCapacitySections to only include sections with this entity name
      }

      // Find which OTHER entity appears in this section title (the relationship partner)
      const otherEntity = allEntityNames.find(n => {
        if (n === modalEntity) return false;
        const esc = n.replace(/[.*+?^${}()|[\]\\]/g, (ch) => '\\' + ch);
        return new RegExp('\\b' + esc + '\\b', 'i').test(s.title);
      });

      if (!otherEntity) {
        // No other entity in title — standalone section (e.g. "Review Adjacency List")
        // Only show if this entity has capacity data
        return !!ca;
      }

      // Two entities in the title — determine who owns this section
      // Find which is "first" (parent) and which is "second" (child) by position in title
      const modalIdx = titleLower.indexOf(modalEntity.toLowerCase());
      const otherIdx = titleLower.indexOf(otherEntity.toLowerCase());
      const isModalFirst = modalIdx < otherIdx;
      const parentName = isModalFirst ? modalEntity : otherEntity;
      const childName = isModalFirst ? otherEntity : modalEntity;

      // Check the child entity's modeling decision from JSON
      const childEntity = model!.entityMappings[childName];
      const childRec = childEntity?.capacityAnalysis?.recommendation;

      // Rule 2: child is separate (vertical_partition) → child owns it
      if (childRec === 'vertical_partition') return modalEntity === childName;

      // Rule 1: child is flattened → parent owns it
      const parentEntity = model!.entityMappings[parentName];
      const parentRec = parentEntity?.capacityAnalysis?.recommendation;
      if (parentRec === 'single_item') return modalEntity === parentName;

      // Fallback: use relationship type hints from title
      if (titleLower.includes('flatten') || titleLower.includes('single')) return modalEntity === parentName;
      if (titleLower.includes('vertical') || titleLower.includes('separate')) return modalEntity === childName;
      if (titleLower.includes('1:1')) return modalEntity === parentName;
      if (titleLower.includes('1:n')) return modalEntity === childName;
      return modalEntity === parentName;
    });

    const hasCapacityData = ca || ownedSections.length > 0;
    const isKeyDesign = ca?.recommendation === 'key_design';

    return (
      <Modal title={modalEntity + ' \u2014 Capacity & Design Analysis'} onClose={() => setModalEntity(null)}>
        <div className="card" style={{ background: 'rgba(255,193,7,0.08)', borderLeft: '3px solid var(--warning)', padding: '0.5rem 0.75rem', marginBottom: '0.75rem', fontSize: '0.78rem', color: 'var(--text-muted)' }}>{DISCLAIMER}</div>
        {project?.design_priority && (
          <div style={{ marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="text-muted" style={{ fontSize: '0.78rem' }}>Design Priority:</span>
            <span className={`badge ${project.design_priority === 'cost' ? 'badge-success' : project.design_priority === 'performance' ? 'badge-warning' : 'badge-success'}`} style={{ fontSize: '0.72rem' }}>
              {project.design_priority === 'cost' ? '💰 Cost' : project.design_priority === 'performance' ? '⚡ Performance' : '⚖️ Balanced'}
            </span>
          </div>
        )}

        {/* Rule 3: Independent entity — no flattened children, not a child sharing PK, no key design analysis */}
        {role === 'independent' && (
          <div className="card guidance-card" style={{ padding: '0.75rem', marginBottom: 12 }}>
            <p className="text-muted" style={{ margin: 0 }}>
              {'\u2139\uFE0F'} No capacity comparison available for {modalEntity}. This entity does not have child entities flattened into it, nor does it share a partition key with a parent entity as a vertical partition.
            </p>
          </div>
        )}

        {/* Fallback if role is parent/child/key_design but no data generated yet */}
        {role !== 'independent' && !hasCapacityData && (
          <div className="card guidance-card" style={{ padding: '0.75rem', marginBottom: 12 }}>
            <p className="text-muted" style={{ margin: 0 }}>No capacity analysis data available yet. Re-run the pipeline to generate per-entity RCU/WCU comparisons.</p>
          </div>
        )}

        {/* Relevant Access Patterns from capacity_analysis.md */}
        {ownedSections.length > 0 && (<div style={{ marginBottom: 8 }}>
          {ownedSections.map((section, idx) => (
            <div key={idx} className="capacity-section" style={{ marginBottom: 12 }}>
              <h4 style={{ fontSize: '0.85rem', marginBottom: 6 }}>{section.title}</h4>
              {renderMarkdownContent(section.content, !!ca && !isKeyDesign)}
            </div>
          ))}
        </div>)}

        {/* Key Design Analysis (JSON-driven) — for entities where PK choice is the design decision */}
        {isKeyDesign && ca?.keyDesignAnalysis && renderKeyDesignAnalysis(ca.keyDesignAnalysis, modalEntity)}

        {/* Capacity Comparison Table (JSON-driven) — for single_item / vertical_partition */}
        {ca && !isKeyDesign && renderCapacityComparisonTable(ca, modalEntity)}

        {/* Priority Rules Applied */}
        {ca?.priorityRulesApplied && ca.priorityRulesApplied.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <strong className="text-sm">🎯 Design Priority Rules Applied</strong>
            <div style={{ marginTop: 6, padding: '0.5rem 0.75rem', background: 'rgba(52,152,219,0.06)', borderLeft: '3px solid var(--primary)', borderRadius: 4 }}>
              {ca.priorityRulesApplied.map((rule, i) => (
                <div key={i} style={{ fontSize: '0.78rem', color: 'var(--text)', lineHeight: 1.6, marginBottom: 2 }}>
                  <span style={{ color: 'var(--primary)', marginRight: 6 }}>▸</span>{rule}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Recommendation — only for non-key-design (key_design shows justification inline) */}
        {ca && !isKeyDesign && (
          <div className="recommendation-box" style={{ marginTop: 12 }}>
            <strong>{'\u2705'} Recommendation</strong><p>{ca.rationale}</p>
            {(ca.rcuSavings || ca.wcuSavings) && <div style={{ marginTop: 6, display: 'flex', gap: 8 }}>{ca.rcuSavings && <span className="badge badge-success">RCU savings: {ca.rcuSavings}</span>}{ca.wcuSavings && <span className="badge badge-success">WCU savings: {ca.wcuSavings}</span>}</div>}
          </div>
        )}

        {/* Design Notes */}
        <div style={{ marginTop: 16 }}><strong className="text-sm">Design Notes</strong><p className="text-muted" style={{ marginTop: 4, lineHeight: 1.6 }}>{e.notes}</p></div>
      </Modal>
    );
  };

  const renderAPModal = () => {
    if (!modalAP || !model!.accessPatternMapping?.[modalAP]) return null;
    const ap = model!.accessPatternMapping![modalAP];
    const diff = getMigrationDifficulty(ap);
    const queryCode = ap.dynamodb_query_csharp || ap.dynamodb_query;
    return (
      <Modal title={modalAP + ': ' + ap.name} onClose={() => setModalAP(null)}>
        <div className="card" style={{ background: 'rgba(255,193,7,0.08)', borderLeft: '3px solid var(--warning)', padding: '0.5rem 0.75rem', marginBottom: '0.75rem', fontSize: '0.78rem', color: 'var(--text-muted)' }}>{DISCLAIMER}</div>
        <div style={{ marginBottom: 16 }}>
          <span className={'badge ' + diff.cls}>{diff.label}</span>
          <span className="badge badge-success" style={{ marginLeft: 4 }}>{ap.index}</span>
          {ap.complexity_rationale && <span className="text-muted" style={{ marginLeft: 8, fontSize: '0.78rem' }}>{ap.complexity_rationale}</span>}
        </div>
        {ap.dynamodb_limitations && (
          <div className="card" style={{ background: 'rgba(13,110,253,0.06)', borderLeft: '3px solid var(--primary)', padding: '0.5rem 0.75rem', marginBottom: '0.75rem', fontSize: '0.8rem' }}>
            <strong>🔍 DynamoDB Designs Evaluated:</strong>
            <p className="text-muted" style={{ marginTop: 4, lineHeight: 1.5 }}>{ap.dynamodb_limitations}</p>
          </div>
        )}
        <strong className="text-sm">Expression Breakdown<HelpTip tip="keyExpr" /></strong>
        <table className="data-table" style={{ marginTop: 8, marginBottom: 16, fontSize: '0.85rem' }}><tbody>
          <tr><td style={{ width: 150 }}><span className="badge badge-success">Key Expression<HelpTip tip="keyExpr" /></span></td><td><code>{ap.key_expression || ('PK = ' + ap.pk + (ap.sk_condition && ap.sk_condition !== 'None' ? ' AND ' + ap.sk_condition : ''))}</code></td></tr>
          <tr><td><span className="badge badge-warning">Filter Expression<HelpTip tip="filterExpr" /></span></td><td><code>{ap.filter_expression || ap.filter || 'None'}</code></td></tr>
          <tr><td><span className="badge badge-danger">Client-Side</span></td><td>{(ap.client_side_filter && ap.client_side_filter.toLowerCase() !== 'none') ? ap.client_side_filter : 'None'}</td></tr>
        </tbody></table>

        {/* RCU/WCU Estimation */}
        {(ap.rcu_per_request != null || ap.estimated_rcu_per_hour != null) && (<>
          <strong className="text-sm">Capacity Estimation<HelpTip tip="rcu" /></strong>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, marginTop: 8, marginBottom: 16 }}>
            {ap.items_scanned != null && <div className="mini-metric"><div className="mini-label">Items Scanned</div><div className="mini-value">{ap.items_scanned}</div></div>}
            {ap.items_returned != null && <div className="mini-metric"><div className="mini-label">Items Returned</div><div className="mini-value">{ap.items_returned}</div></div>}
            {ap.rcu_per_request != null && <div className="mini-metric"><div className="mini-label">RCU / Request</div><div className="mini-value">{ap.rcu_per_request}</div></div>}
            {ap.wcu_per_request != null && <div className="mini-metric"><div className="mini-label">WCU / Request</div><div className="mini-value">{ap.wcu_per_request}</div></div>}
            {ap.requests_per_hour != null && <div className="mini-metric"><div className="mini-label">Requests / hr</div><div className="mini-value">{ap.requests_per_hour.toLocaleString()}</div></div>}
            {ap.estimated_rcu_per_hour != null && <div className="mini-metric"><div className="mini-label">Total RCU / hr</div><div className="mini-value" style={{ color: 'var(--primary)' }}>{ap.estimated_rcu_per_hour.toLocaleString()}</div></div>}
            {ap.estimated_wcu_per_hour != null && ap.estimated_wcu_per_hour > 0 && <div className="mini-metric"><div className="mini-label">Total WCU / hr</div><div className="mini-value" style={{ color: 'var(--warning)' }}>{ap.estimated_wcu_per_hour.toLocaleString()}</div></div>}
          </div>
        </>)}

        {ap.performance_notes && <div className="card guidance-card" style={{ marginBottom: 16, padding: '0.75rem' }}><strong className="text-sm">Performance Impact</strong><p className="text-muted" style={{ marginTop: 4, lineHeight: 1.5 }}>{ap.performance_notes}</p></div>}
        {ap.performance_impact && !ap.performance_notes && <div className="card guidance-card" style={{ marginBottom: 16, padding: '0.75rem' }}><strong className="text-sm">Performance Impact</strong><p className="text-muted" style={{ marginTop: 4, lineHeight: 1.5 }}>{ap.performance_impact}</p></div>}
        {ap.migration_notes && <div style={{ marginBottom: 16 }}><strong className="text-sm">Migration Notes</strong><p className="text-muted" style={{ marginTop: 4, lineHeight: 1.5 }}>{ap.migration_notes}</p></div>}
        {ap.note && !ap.migration_notes && <div style={{ marginBottom: 16 }}><strong className="text-sm">Migration Notes</strong><p className="text-muted" style={{ marginTop: 4, lineHeight: 1.5 }}>{ap.note}</p></div>}
        {ap.original_code && <div style={{ marginBottom: 16 }}><strong className="text-sm">Original C# / LINQ</strong><pre className="code-block">{ap.original_code}</pre></div>}
        {queryCode && <div><strong className="text-sm">DynamoDB C# Implementation</strong><pre className="code-block">{queryCode}</pre></div>}
      </Modal>
    );
  };

  const renderKeyJustificationModal = () => {
    if (!modalKeyJustification || !model) return null;
    const { entity, keyType } = modalKeyJustification;
    const e = model.entityMappings[entity];
    if (!e?.keyDesignJustification) return null;
    const justification = keyType === 'pk' ? e.keyDesignJustification.pk : e.keyDesignJustification.sk;
    if (!justification) return null;
    const keyLabel = keyType === 'pk' ? 'Partition Key (PK)' : 'Sort Key (SK)';
    const keyValue = keyType === 'pk' ? e.keyMappings.PK : e.keyMappings.SK;
    return (
      <Modal title={`${entity} — ${keyLabel} Design Justification`} onClose={() => setModalKeyJustification(null)}>
        <div className="card" style={{ background: 'rgba(255,193,7,0.08)', borderLeft: '3px solid var(--warning)', padding: '0.5rem 0.75rem', marginBottom: '0.75rem', fontSize: '0.78rem', color: 'var(--text-muted)' }}>{DISCLAIMER}</div>
        {project?.design_priority && (
          <div style={{ marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="text-muted" style={{ fontSize: '0.78rem' }}>Design Priority:</span>
            <span className={`badge ${project.design_priority === 'cost' ? 'badge-success' : project.design_priority === 'performance' ? 'badge-warning' : 'badge-success'}`} style={{ fontSize: '0.72rem' }}>
              {project.design_priority === 'cost' ? '💰 Cost' : project.design_priority === 'performance' ? '⚡ Performance' : '⚖️ Balanced'}
            </span>
          </div>
        )}
        <div className="card" style={{ padding: '0.6rem 0.75rem', marginBottom: 12, background: 'rgba(40,167,69,0.06)', borderLeft: '3px solid var(--success)' }}>
          <div style={{ fontSize: '0.82rem' }}>
            <strong>Chosen {keyLabel}:</strong> <code>{justification.chosen}</code>
            <span className="text-muted" style={{ marginLeft: 8, fontSize: '0.75rem' }}>({keyValue})</span>
          </div>
        </div>
        <div style={{ marginBottom: 12 }}>
          <strong className="text-sm">Access Patterns Driving This Decision</strong>
          <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {justification.accessPatternsDriving.map(ap => (
              <span key={ap} className="badge badge-success" style={{ fontSize: '0.72rem' }}>{ap}{model.accessPatternMapping?.[ap] ? `: ${model.accessPatternMapping[ap].name}` : ''}</span>
            ))}
          </div>
        </div>
        {justification.alternatives.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <strong className="text-sm">Alternatives Evaluated</strong>
            <table className="data-table" style={{ fontSize: '0.82rem', marginTop: 8 }}>
              <thead><tr><th style={{ width: '18%' }}>Alternative</th><th style={{ width: '22%' }}>Description</th><th style={{ width: '22%' }}>Pros</th><th style={{ width: '22%' }}>Cons</th><th style={{ width: '16%' }}>Cost Impact</th></tr></thead>
              <tbody>
                {justification.alternatives.map((alt, i) => (
                  <tr key={i} style={alt.keyPattern === justification.chosen ? { background: 'rgba(40,167,69,0.06)' } : {}}>
                    <td><code style={{ fontSize: '0.75rem' }}>{alt.keyPattern}</code>{alt.keyPattern === justification.chosen && <span className="badge badge-success" style={{ marginLeft: 4, fontSize: '0.6rem' }}>chosen</span>}</td>
                    <td className="text-muted" style={{ fontSize: '0.75rem' }}>{alt.description}</td>
                    <td><ul style={{ margin: 0, paddingLeft: '1rem' }}>{alt.pros.map((p, j) => <li key={j} style={{ fontSize: '0.72rem', color: 'var(--success)' }}>{p}</li>)}</ul></td>
                    <td><ul style={{ margin: 0, paddingLeft: '1rem' }}>{alt.cons.map((c, j) => <li key={j} style={{ fontSize: '0.72rem', color: 'var(--danger)' }}>{c}</li>)}</ul></td>
                    <td className="text-muted" style={{ fontSize: '0.72rem' }}>{alt.estimatedCostImpact || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {justification.priorityRulesApplied && justification.priorityRulesApplied.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <strong className="text-sm">🎯 Design Priority Rules Applied</strong>
            <div style={{ marginTop: 6, padding: '0.5rem 0.75rem', background: 'rgba(52,152,219,0.06)', borderLeft: '3px solid var(--primary)', borderRadius: 4 }}>
              {justification.priorityRulesApplied.map((rule, i) => (
                <div key={i} style={{ fontSize: '0.78rem', color: 'var(--text)', lineHeight: 1.6, marginBottom: 2 }}>
                  <span style={{ color: 'var(--primary)', marginRight: 6 }}>▸</span>{rule}
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="recommendation-box" style={{ marginTop: 12 }}>
          <strong>{'\u2705'} Rationale</strong>
          <p style={{ marginTop: 4, lineHeight: 1.6 }}>{justification.rationale}</p>
        </div>
      </Modal>
    );
  };

  const renderDataModel = () => {
    const entityEntries = Object.entries(model!.entityMappings);
    return (
      <div>
        <div className="card" style={{ background: 'rgba(255,193,7,0.08)', borderLeft: '3px solid var(--warning)', padding: '0.6rem 1rem', marginBottom: '0.75rem', fontSize: '0.82rem', color: 'var(--text-muted)' }}>{DISCLAIMER}</div>
        <div className="card"><div className="flex-between"><div><strong style={{ fontSize: '1.1rem' }}>{model!.tableName}</strong><span className="badge badge-success" style={{ marginLeft: 8 }}>{model!.billingMode}</span><HelpTip tip="singleTable" /></div><div className="text-muted">PK: {model!.primaryKey.partitionKey} / SK: {model!.primaryKey.sortKey}</div></div></div>
        <div className="card">
          <strong>Global Secondary Indexes ({model!.gsis.length})<HelpTip tip="gsi" /></strong>
          <table className="data-table" style={{ marginTop: 8 }}>
            <thead><tr><th>Index</th><th>PK</th><th>SK</th><th>Projection<HelpTip tip="projection" /></th><th>Attributes</th><th>Patterns</th></tr></thead>
            <tbody>{model!.gsis.map(g => (<tr key={g.indexName}><td><strong>{g.indexName}</strong></td><td className="text-muted">{g.partitionKey}</td><td className="text-muted">{g.sortKey}</td><td><span className={'badge ' + (g.projectionType === 'ALL' ? 'badge-warning' : 'badge-success')}>{g.projectionType}</span>{g.projectionType === 'ALL' && <HelpTip tip="writeAmplification" />}</td><td className="text-muted" style={{ fontSize: '0.75rem', maxWidth: 180 }}>{g.projectedAttributes?.length ? g.projectedAttributes.join(', ') : '\u2014'}</td><td className="text-muted" style={{ fontSize: '0.75rem' }}>{g.servedPatterns?.join(', ') || '\u2014'}</td></tr>))}</tbody>
          </table>
          {model!.gsis.some(g => g.projectionRationale) && <div style={{ marginTop: 8 }}>{model!.gsis.filter(g => g.projectionRationale).map(g => (<div key={g.indexName} className="text-muted" style={{ fontSize: '0.75rem', marginTop: 4 }}><strong>{g.indexName}</strong>: {g.projectionRationale}</div>))}</div>}
        </div>
        <strong style={{ display: 'block', margin: '1rem 0 0.5rem' }}>Entity Mappings ({entityEntries.length})</strong>
        {entityEntries.map(([name, e]) => {
          const isExp = expandedEntity === name;
          const ca = e.capacityAnalysis;
          const chosen = ca?.recommendation === 'single_item' ? ca?.singleItemApproach : ca?.verticalPartitionApproach;
          const role = getEntityCapacityRole(name);
          return (
            <div key={name} className="card">
              <div className="flex-between" style={{ cursor: 'pointer' }} onClick={() => setExpandedEntity(isExp ? null : name)}>
                <div>
                  <strong>{name}</strong><span className="badge badge-success" style={{ marginLeft: 8 }}>{e.estimatedSizeKB} KB</span>
                  {(e.description.toLowerCase().includes('flatten') || e.description.toLowerCase().includes('single')) && <span className="badge badge-warning" style={{ marginLeft: 4 }}>Flattened<HelpTip tip="flatten" /></span>}
                  <div className="text-muted" style={{ marginTop: 4 }}>{e.description}</div>
                  {chosen && <div className="text-muted" style={{ marginTop: 2, fontSize: '0.75rem' }}>RCU/hr: {chosen.totalRcuPerHour?.toLocaleString() || '\u2014'} {'\u00B7'} WCU/hr: {chosen.totalWcuPerHour?.toLocaleString() || '\u2014'}</div>}
                </div>
                <span style={{ color: 'var(--text-muted)' }}>{isExp ? '\u25BC' : '\u25B6'}</span>
              </div>
              {isExp && (
                <div style={{ marginTop: '0.75rem', borderTop: '1px solid var(--border)', paddingTop: '0.75rem' }}>
                  <strong className="text-sm">Key Mappings</strong>
                  <table className="data-table" style={{ marginTop: 4, marginBottom: 12 }}><thead><tr><th>Key</th><th>Pattern</th></tr></thead><tbody>{Object.entries(e.keyMappings).map(([k, v]) => (<tr key={k}><td><code>{k}</code></td><td><code>{v}</code>{(k === 'PK' || k === 'SK') && e.keyDesignJustification && ((k === 'PK' && e.keyDesignJustification.pk) || (k === 'SK' && e.keyDesignJustification.sk)) && <button onClick={(ev) => { ev.stopPropagation(); setModalKeyJustification({ entity: name, keyType: k === 'PK' ? 'pk' : 'sk' }); }} title={`View ${k} design justification`} style={{ background: 'none', border: 'none', cursor: 'pointer', marginLeft: 6, fontSize: '0.85rem', padding: 0, verticalAlign: 'middle' }}>{'\uD83D\uDD11'}</button>}</td></tr>))}</tbody></table>
                  <strong className="text-sm">Attributes ({Array.isArray(e.attributes) ? e.attributes.length : Object.keys(e.attributes).length})</strong>
                  <div style={{ marginTop: 4, marginBottom: 12 }}>{(Array.isArray(e.attributes) ? e.attributes : Object.keys(e.attributes)).map(a => <span key={a} className="badge badge-success" style={{ marginRight: 4, marginBottom: 4 }}>{a}</span>)}</div>
                  <strong className="text-sm">Design Notes</strong>
                  <p className="text-muted" style={{ marginTop: 4 }}>{e.notes}</p>
                  {role !== 'independent' ? (
                    <div style={{ marginTop: 12 }}><button className="btn btn-secondary" style={{ fontSize: '0.8rem' }} onClick={() => openEntityModal(name)}>{'\uD83D\uDCCA'} Capacity Analysis</button></div>
                  ) : (
                    <div className="text-muted" style={{ marginTop: 12, fontSize: '0.78rem', fontStyle: 'italic' }}>{'\u2139\uFE0F'} No capacity comparison — this entity has no flattened children and does not share a partition key with a parent entity.</div>
                  )}
                </div>
              )}
            </div>
          );
        })}
        {results.capacity_md && <details style={{ marginTop: '1rem' }}><summary style={{ cursor: 'pointer', color: 'var(--primary)', fontSize: '0.9rem' }}>{'\uD83D\uDCCA'} Full Capacity Analysis Report</summary><div className="card" style={{ marginTop: '0.5rem' }}><div style={{ whiteSpace: 'pre-wrap', fontSize: '0.8rem', maxHeight: 400, overflow: 'auto', lineHeight: 1.6 }}>{results.capacity_md}</div></div></details>}
      </div>
    );
  };

  const renderAccessPatterns = () => {
    const aps = Object.entries(model!.accessPatternMapping || {});
    if (aps.length === 0) {
      return (
        <div className="card">
          <p>No access pattern mappings found in the model JSON.</p>
          <p className="text-muted" style={{ marginTop: 8 }}>This can happen if the model JSON was truncated during generation. Try re-running the pipeline to regenerate the model.</p>
        </div>
      );
    }
    const easy = aps.filter(([,a]) => getMigrationDifficulty(a).label === 'Easy').length;
    const medium = aps.filter(([,a]) => getMigrationDifficulty(a).label === 'Medium').length;
    const hard = aps.filter(([,a]) => getMigrationDifficulty(a).label === 'Hard').length;
    const totalRcuHr = aps.reduce((sum, [, a]) => sum + (a.estimated_rcu_per_hour || 0), 0);
    const totalWcuHr = aps.reduce((sum, [, a]) => sum + (a.estimated_wcu_per_hour || 0), 0);
    return (
      <div>
        <div className="card" style={{ background: 'rgba(255,193,7,0.08)', borderLeft: '3px solid var(--warning)', padding: '0.6rem 1rem', marginBottom: '0.75rem', fontSize: '0.82rem', color: 'var(--text-muted)' }}>{DISCLAIMER}</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '0.75rem', marginBottom: '1rem' }}>
          <div className="metric-card"><div className="value" style={{ color: 'var(--success)' }}>{easy}</div><div className="label">Easy</div></div>
          <div className="metric-card"><div className="value" style={{ color: 'var(--warning)' }}>{medium}</div><div className="label">Medium</div></div>
          <div className="metric-card"><div className="value" style={{ color: 'var(--danger)' }}>{hard}</div><div className="label">Hard</div></div>
          <div className="metric-card"><div className="value" style={{ color: 'var(--primary)' }}>{totalRcuHr.toLocaleString()}</div><div className="label">Total RCU/hr<HelpTip tip="rcu" /></div></div>
          <div className="metric-card"><div className="value" style={{ color: 'var(--warning)' }}>{totalWcuHr.toLocaleString()}</div><div className="label">Total WCU/hr<HelpTip tip="wcu" /></div></div>
        </div>
        {aps.map(([id, ap]) => {
          const diff = getMigrationDifficulty(ap);
          const isExp = expandedAP === id;
          const queryCode = ap.dynamodb_query_csharp || ap.dynamodb_query;
          return (
            <div key={id} className="card" style={{ marginTop: '0.5rem' }}>
              <div className="flex-between" style={{ cursor: 'pointer' }} onClick={() => setExpandedAP(isExp ? null : id)}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}>
                    <strong>{id}: {ap.name}</strong>
                    <span className={'badge ' + diff.cls}>{diff.label}</span>
                    <span className="badge badge-success">{ap.index}</span>
                    {ap.estimated_rcu_per_hour != null && ap.estimated_rcu_per_hour > 0 && (
                      <span style={{ fontSize: '0.72rem', color: 'var(--primary)', fontWeight: 600 }}>RCU/hr: {ap.estimated_rcu_per_hour.toLocaleString()}</span>
                    )}
                    {ap.estimated_wcu_per_hour != null && ap.estimated_wcu_per_hour > 0 && (
                      <span style={{ fontSize: '0.72rem', color: 'var(--warning)', fontWeight: 600 }}>WCU/hr: {ap.estimated_wcu_per_hour.toLocaleString()}</span>
                    )}
                  </div>
                  <div className="text-muted" style={{ marginTop: 6, fontSize: '0.8rem' }}>
                    {ap.key_expression ? (<>
                      <span style={{ color: 'var(--success)', fontWeight: 600 }}>Key<HelpTip tip="keyExpr" />:</span> <code>{ap.key_expression}</code>
                      {(ap.filter_expression && ap.filter_expression !== 'None') && <span> {'\u00B7'} <span style={{ color: 'var(--warning)', fontWeight: 600 }}>Filter<HelpTip tip="filterExpr" />:</span> <code>{ap.filter_expression}</code></span>}
                      {(ap.client_side_filter && ap.client_side_filter.toLowerCase() !== 'none') && <span> {'\u00B7'} <span style={{ color: 'var(--danger)', fontWeight: 600 }}>Client:</span> {ap.client_side_filter}</span>}
                    </>) : (<>
                      PK: <code>{ap.pk}</code>
                      {ap.sk_condition && ap.sk_condition !== 'None' && <span> {'\u00B7'} SK: <code>{ap.sk_condition}</code></span>}
                      {ap.filter && ap.filter !== 'None' && <span> {'\u00B7'} Filter: <code>{ap.filter}</code></span>}
                    </>)}
                  </div>
                  {ap.requests_per_hour != null && ap.requests_per_hour > 0 && (
                    <div className="text-muted" style={{ marginTop: 4, fontSize: '0.72rem' }}>
                      {ap.requests_per_hour.toLocaleString()} req/hr
                      {ap.rcu_per_request != null && <span> · {ap.rcu_per_request} RCU/req</span>}
                      {ap.items_scanned != null && <span> · {ap.items_scanned} items scanned</span>}
                      {ap.items_returned != null && <span> → {ap.items_returned} returned</span>}
                    </div>
                  )}
                  {ap.performance_notes && <div className="text-muted" style={{ marginTop: 4, fontSize: '0.75rem' }}>{'\uD83D\uDCCA'} {ap.performance_notes}</div>}
                </div>
                <span style={{ color: 'var(--text-muted)' }}>{isExp ? '\u25BC' : '\u25B6'}</span>
              </div>
              {isExp && (
                <div style={{ marginTop: '0.75rem', borderTop: '1px solid var(--border)', paddingTop: '0.75rem' }}>
                  {/* Expression Breakdown Table */}
                  <strong className="text-sm">Expression Breakdown</strong>
                  <table className="data-table" style={{ marginTop: 4, marginBottom: 12, fontSize: '0.82rem' }}><tbody>
                    <tr><td style={{ width: 140 }}><span className="badge badge-success">Key Expression<HelpTip tip="keyExpr" /></span></td><td><code>{ap.key_expression || ('PK = ' + ap.pk + (ap.sk_condition && ap.sk_condition !== 'None' ? ' AND ' + ap.sk_condition : ''))}</code></td></tr>
                    <tr><td><span className="badge badge-warning">Filter Expression<HelpTip tip="filterExpr" /></span></td><td><code>{ap.filter_expression || ap.filter || 'None'}</code></td></tr>
                    <tr><td><span className="badge badge-danger">Client-Side</span></td><td>{(ap.client_side_filter && ap.client_side_filter.toLowerCase() !== 'none') ? ap.client_side_filter : 'None'}</td></tr>
                  </tbody></table>

                  {/* RCU/WCU Estimation */}
                  {(ap.rcu_per_request != null || ap.estimated_rcu_per_hour != null) && (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 12 }}>
                      {ap.rcu_per_request != null && <div className="mini-metric"><div className="mini-label">RCU / Request</div><div className="mini-value">{ap.rcu_per_request}</div></div>}
                      {ap.requests_per_hour != null && <div className="mini-metric"><div className="mini-label">Requests / hr</div><div className="mini-value">{ap.requests_per_hour.toLocaleString()}</div></div>}
                      {ap.estimated_rcu_per_hour != null && <div className="mini-metric"><div className="mini-label">Total RCU / hr</div><div className="mini-value" style={{ color: 'var(--primary)' }}>{ap.estimated_rcu_per_hour.toLocaleString()}</div></div>}
                      {ap.estimated_wcu_per_hour != null && <div className="mini-metric"><div className="mini-label">Total WCU / hr</div><div className="mini-value" style={{ color: 'var(--warning)' }}>{ap.estimated_wcu_per_hour.toLocaleString()}</div></div>}
                    </div>
                  )}

                  {ap.migration_notes && <div style={{ marginBottom: 12 }}><strong className="text-sm">Migration Notes</strong><p className="text-muted" style={{ marginTop: 4, lineHeight: 1.5 }}>{ap.migration_notes}</p></div>}
                  {ap.note && !ap.migration_notes && <div style={{ marginBottom: 12 }}><strong className="text-sm">Migration Notes</strong><p className="text-muted" style={{ marginTop: 4, lineHeight: 1.5 }}>{ap.note}</p></div>}
                  {ap.performance_impact && <div className="card guidance-card" style={{ marginBottom: 12, padding: '0.75rem' }}><strong className="text-sm">Performance Impact</strong><p className="text-muted" style={{ marginTop: 4, lineHeight: 1.5 }}>{ap.performance_impact}</p></div>}
                  {ap.original_code && <div style={{ marginBottom: 12 }}><strong className="text-sm">Original C# / LINQ</strong><pre className="code-block">{ap.original_code}</pre></div>}
                  {queryCode && <div style={{ marginBottom: 12 }}><strong className="text-sm">DynamoDB C# Implementation</strong><pre className="code-block">{queryCode}</pre></div>}
                  <button className="btn btn-secondary" style={{ fontSize: '0.8rem' }} onClick={() => openAPModal(id)}>{'\uD83D\uDD0D'} Full Details</button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  const renderCoverageReport = () => {
    const raw = results.extraction_coverage;
    if (!raw) return <div className="card"><p className="text-muted">No extraction coverage report available. Run the Extract step to generate one.</p></div>;
    let report: any;
    try { report = JSON.parse(raw); } catch { return <div className="card"><pre style={{ whiteSpace: 'pre-wrap', fontSize: '0.8rem' }}>{raw}</pre></div>; }

    const cov = report.coverage || {};
    const scan = report.scan_summary || {};
    const gt = report.ground_truth || {};
    const warnings = report.warnings || [];

    return (
      <div>
        <div className="card" style={{ background: 'rgba(255,193,7,0.08)', borderLeft: '3px solid var(--warning)', padding: '0.6rem 1rem', marginBottom: '0.75rem', fontSize: '0.82rem', color: 'var(--text-muted)' }}>
          This report compares what exists in the .NET codebase (DbContext entities, data access methods) against what the AI extractor found. Low coverage may indicate missed access patterns.
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.75rem', marginBottom: '1rem' }}>
          <div className="metric-card"><div className="value" style={{ color: cov.entity_coverage_pct >= 80 ? 'var(--success)' : 'var(--warning)' }}>{cov.entity_coverage_pct || 0}%</div><div className="label">Entity Coverage</div></div>
          <div className="metric-card"><div className="value" style={{ color: cov.method_coverage_pct >= 70 ? 'var(--success)' : 'var(--warning)' }}>{cov.method_coverage_pct || 0}%</div><div className="label">Method Coverage</div></div>
          <div className="metric-card"><div className="value">{scan.total_cs_files || 0}</div><div className="label">C# Files Scanned</div></div>
          <div className="metric-card"><div className="value">{scan.total_data_access_methods || 0}</div><div className="label">Data Access Methods</div></div>
        </div>

        {warnings.length > 0 && (
          <div className="card" style={{ borderLeft: '3px solid var(--warning)', marginBottom: '1rem' }}>
            <strong>Warnings</strong>
            {warnings.map((w: string, i: number) => <p key={i} className="text-muted" style={{ marginTop: 4, fontSize: '0.82rem' }}>{w}</p>)}
          </div>
        )}

        <div className="card" style={{ marginBottom: '1rem' }}>
          <strong>Entity Comparison</strong>
          <table className="data-table" style={{ marginTop: '0.5rem', fontSize: '0.82rem' }}>
            <thead><tr><th>Entity</th><th>In DbContext</th><th>Extracted</th><th>Status</th></tr></thead>
            <tbody>
              {(gt.all_known_entities || []).map((e: string) => {
                const extracted = (cov.entities_matched || []).includes(e);
                return <tr key={e}><td>{e}</td><td>✅</td><td>{extracted ? '✅' : '❌'}</td><td><span className={'badge ' + (extracted ? 'badge-success' : 'badge-danger')}>{extracted ? 'Matched' : 'Missing'}</span></td></tr>;
              })}
              {(cov.extra_entities || []).map((e: string) => (
                <tr key={e}><td>{e}</td><td>—</td><td>✅</td><td><span className="badge badge-warning">Extra (LLM-inferred)</span></td></tr>
              ))}
            </tbody>
          </table>
        </div>

        {scan.stored_procedures_found?.length > 0 && (
          <div className="card" style={{ marginBottom: '1rem' }}>
            <strong>Stored Procedures Detected</strong>
            <div style={{ marginTop: '0.5rem' }}>{scan.stored_procedures_found.map((sp: string) => <span key={sp} className="badge badge-warning" style={{ marginRight: 4, marginBottom: 4 }}>{sp}</span>)}</div>
            <p className="text-muted" style={{ marginTop: 8, fontSize: '0.8rem' }}>Verify these were analyzed — stored procedures may contain access patterns not captured by LINQ analysis.</p>
          </div>
        )}

        <div className="card">
          <strong>Data Access Classes ({scan.files_with_data_access || 0} files)</strong>
          <table className="data-table" style={{ marginTop: '0.5rem', fontSize: '0.82rem' }}>
            <thead><tr><th>File</th><th>Methods Found</th></tr></thead>
            <tbody>
              {Object.entries(gt.data_access_classes || {}).map(([file, methods]: [string, any]) => (
                <tr key={file}><td>{file}</td><td className="text-muted">{(methods as string[]).join(', ')}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const renderRawContent = (key: string) => (
    <div className="card"><div style={{ whiteSpace: 'pre-wrap', fontSize: '0.85rem', maxHeight: 600, overflow: 'auto', lineHeight: 1.6 }}>{results[key] || 'No results yet.'}</div></div>
  );

  const tabs = [
    { key: 'data_model', label: '\uD83C\uDFD7\uFE0F DynamoDB Model' },
    { key: 'access_migration', label: '\uD83D\uDD04 Access Pattern Migration' },
    { key: 'validation_md', label: '\u2705 Validation Report' },
    { key: 'extraction_coverage', label: '\uD83D\uDCCB Extraction Coverage' },
    { key: 'model_json', label: '\uD83D\uDCC4 Raw JSON' },
  ];

  return (
    <div>
      <div className="flex-between">
        <h2>{'\uD83D\uDCCB'} Migration Results</h2>
        <div className="flex" style={{ gap: '0.5rem' }}>
          <button className="btn btn-secondary" onClick={handleExportPDF}>{'\uD83D\uDCE5'} Export Report</button>
          <button className="btn btn-primary" onClick={handleExportSummary}>{'\uD83D\uDCCA'} Export Proposal</button>
        </div>
      </div>
      {currentRunId && (
        <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span>Viewing run #{currentRunId}</span>
          {project?.design_priority && (
            <span className={`badge ${project.design_priority === 'cost' ? 'badge-success' : project.design_priority === 'performance' ? 'badge-warning' : 'badge-success'}`} style={{ fontSize: '0.72rem' }}>
              {project.design_priority === 'cost' ? '💰 Cost Priority' : project.design_priority === 'performance' ? '⚡ Performance Priority' : '⚖️ Balanced'}
            </span>
          )}
        </div>
      )}
      <div className="card" style={{ background: 'rgba(255,193,7,0.08)', borderLeft: '3px solid var(--warning)', padding: '0.6rem 1rem', marginBottom: '0.75rem', fontSize: '0.82rem', color: 'var(--text-muted)' }}>{DISCLAIMER}</div>
      <div className="tabs">
        {tabs.map(t => (
          <button key={t.key} className={'tab ' + (activeTab === t.key ? 'active' : '')} onClick={() => setActiveTab(t.key)}>{t.label}</button>
        ))}
      </div>
      {renderOverridePanel()}
      {activeTab === 'data_model' && renderDataModel()}
      {activeTab === 'access_migration' && renderAccessPatterns()}
      {activeTab === 'validation_md' && renderRawContent('validation_md')}
      {activeTab === 'extraction_coverage' && renderCoverageReport()}
      {activeTab === 'model_json' && (<div className="card"><pre style={{ whiteSpace: 'pre-wrap', fontSize: '0.8rem', maxHeight: 600, overflow: 'auto' }}>{results.model_json || 'No results yet.'}</pre></div>)}
      {renderEntityModal()}
      {renderAPModal()}
      {renderKeyJustificationModal()}
    </div>
  );
}
