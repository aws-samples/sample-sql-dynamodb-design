import { useState, useEffect, useCallback } from 'react';
import { projectsApi, Project } from '../api/client';

interface Props {
  projectId: number | null;
  setProjectId: (id: number) => void;
  onNext: () => void;
}

interface BrowseEntry { name: string; path: string; }
type PickerMode = 'folder' | 'file';
interface PickerState {
  open: boolean;
  mode: PickerMode;
  fileExts: string;       // e.g. '.sql,.txt'
  onSelect: (p: string) => void;
}

export default function ProjectSetup({ projectId, setProjectId, onNext }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState('ECommerce Migration');
  const [path, setPath] = useState('sample-dotnet-project');
  const [schemaPath, setSchemaPath] = useState('');
  const [awsProfile, setAwsProfile] = useState('default');
  const [awsProfiles, setAwsProfiles] = useState<string[]>([]);
  const [designPriority, setDesignPriority] = useState('balanced');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<{
    ready: boolean; credentials_valid: boolean;
    models: Record<string, { model_id: string; accessible: boolean; used_by: string; required: boolean; error: string | null }>;
    instructions: string[];
  } | null>(null);

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [hoveredCardId, setHoveredCardId] = useState<number | null>(null);

  // Unified picker state
  const [picker, setPicker] = useState<PickerState>({ open: false, mode: 'folder', fileExts: '', onSelect: () => {} });
  const [browseDir, setBrowseDir] = useState('.');
  const [browseDirs, setBrowseDirs] = useState<BrowseEntry[]>([]);
  const [browseFiles, setBrowseFiles] = useState<BrowseEntry[]>([]);
  const [browseParent, setBrowseParent] = useState('.');
  const [browseCurrent, setBrowseCurrent] = useState('.');
  const [browseLoading, setBrowseLoading] = useState(false);
  const [selectedItem, setSelectedItem] = useState('');

  useEffect(() => {
    projectsApi.list()
      .then((r) => setProjects(r.data))
      .catch((e) => setError(`Failed to load projects: ${e.message}`));
    projectsApi.awsProfiles()
      .then((r) => {
        setAwsProfiles(r.data);
        // Default to first profile if 'default' isn't in the list
        if (r.data.length > 0 && !r.data.includes('default')) {
          setAwsProfile(r.data[0]);
        }
      })
      .catch(() => {});
  }, []);

  const loadDir = useCallback(async (dirPath: string, fileExts: string = '') => {
    setBrowseLoading(true);
    try {
      const { data } = await projectsApi.browseDirs(dirPath, fileExts);
      setBrowseDirs(data.dirs);
      setBrowseFiles(data.files || []);
      setBrowseParent(data.parent);
      setBrowseCurrent(data.current);
      setBrowseDir(data.current);
      setSelectedItem(data.current);
    } catch { setBrowseDirs([]); setBrowseFiles([]); }
    setBrowseLoading(false);
  }, []);

  const openPicker = (mode: PickerMode, currentVal: string, fileExts: string, onSelect: (p: string) => void) => {
    setPicker({ open: true, mode, fileExts, onSelect });
    setSelectedItem(currentVal || '.');
    loadDir(mode === 'file' && currentVal ? currentVal.replace(/[/\\][^/\\]*$/, '') || '.' : currentVal || '.', fileExts);
  };

  const handlePickerSelect = () => {
    picker.onSelect(selectedItem);
    setPicker(p => ({ ...p, open: false }));
  };

  const handleCreate = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await projectsApi.create({
        name, path, aws_profile: awsProfile, design_priority: designPriority,
        schema_path: schemaPath || null,
      });
      setProjectId(data.id);
      setProjects((prev) => [data, ...prev]);
      setShowCreateForm(false);
      onNext();
    } catch (e: any) {
      const msg = e.response?.data?.detail || e.message || 'Unknown error';
      setError(`Failed to create project: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  const designDecisions = [
    ['GSI Count', 'Minimize — overload GSIs across patterns', 'GSIs for patterns >10K req/hr, overload rest', 'Dedicated GSI per high-frequency pattern'],
    ['GSI Projection', 'KEYS_ONLY — minimize write amplification', 'INCLUDE with only needed attributes', 'INCLUDE or ALL — avoid base table fetches'],
    ['Key Design (PK/SK)', 'Accept broader queries + FilterExpression on low-freq patterns', 'Optimize top patterns for KeyCondition, accept filters on rest', 'Composite sort keys to push max filtering into KeyConditionExpression'],
    ['Filter Strategy', 'Accept FilterExpression on patterns <5K/hr to avoid new GSIs', 'Minimize FilterExpression on >10K/hr patterns', 'Eliminate FilterExpression on >10K/hr — use dedicated GSI instead'],
    ['Entity Modeling', 'Vertical partition when write frequencies differ >3x — smaller items = fewer WCUs', 'Flatten when reads >2x writes, separate otherwise', 'Aggressive flattening — fewer API calls per read'],
    ['Denormalization', 'Minimal — avoid write amplification from keeping copies in sync', 'Denormalize for top 5 read patterns only', 'Aggressive — copy frequently-read fields to avoid multi-query patterns'],
    ['Transaction Strategy', 'Single PutItem calls — avoid 2x WCU transaction overhead', 'TransactWriteItems for critical multi-entity writes only', 'BatchWriteItem for non-critical writes, transactions for ACID-critical paths'],
    ['Read Consistency', 'Eventually consistent everywhere (0.5x RCU)', 'Eventually consistent default, strongly consistent for inventory/payments', 'Strongly consistent for critical paths (inventory, auth, payments)'],
    ['Item Collection Density', 'Keep items independent — avoid reading unnecessary data', 'Group related items under same PK for common access patterns', 'Pack related items under same PK for single-query retrieval'],
    ['TTL / Data Lifecycle', 'Enable TTL on transient data (sessions, carts) to reduce storage costs', 'TTL on transient data, archive old orders to S3', 'Keep data longer for faster access without re-computation'],
    ['Sparse GSI Design', 'Use sparse GSIs — only index items with the GSI key attribute to reduce costs', 'Sparse GSIs for low-cardinality patterns', 'Dense GSIs — index all items for maximum query flexibility'],
    ['Caching (DAX)', 'No DAX — accept higher latency to avoid DAX cluster cost', 'DAX for top 3 read-heavy patterns (>50K req/hr)', 'DAX for all read-heavy patterns, pre-compute aggregations via Streams'],
    ['Pre-computation', 'Compute on read — accept higher RCU for aggregation queries', 'Pre-compute for patterns >50K req/hr (e.g., rating stats)', 'Pre-compute all aggregations via DynamoDB Streams + Lambda'],
  ];

  return (
    <div>
      <h2>📂 Project Setup</h2>
      {error && <div className="card" style={{ borderLeft: '3px solid #e74c3c', color: '#e74c3c' }}>{error}</div>}

      {!showCreateForm && (
        <button className="btn btn-primary" onClick={() => setShowCreateForm(true)} style={{ marginBottom: '1rem' }}>
          + Create New Project
        </button>
      )}

      {showCreateForm && (
      <div className="card">
        <label className="text-sm">Project Name</label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} />

        <div className="mt-1">
          <label className="text-sm">Project Path</label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input type="text" value={path} onChange={(e) => setPath(e.target.value)} style={{ flex: 1 }} />
            <button className="btn btn-secondary" onClick={() => openPicker('folder', path, '', setPath)} style={{ whiteSpace: 'nowrap', fontSize: '0.8rem' }}>📁 Browse</button>
          </div>
        </div>

        <div className="mt-1">
          <label className="text-sm">DB Schema File <span className="text-muted" style={{ fontWeight: 400 }}>(optional)</span></label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input type="text" value={schemaPath} onChange={(e) => setSchemaPath(e.target.value)} style={{ flex: 1 }} placeholder="Path to SQL schema file (.sql)" />
            <button className="btn btn-secondary" onClick={() => openPicker('file', schemaPath, '.sql,.ddl,.txt', setSchemaPath)} style={{ whiteSpace: 'nowrap', fontSize: '0.8rem' }}>📄 Browse</button>
            {schemaPath && <button className="btn btn-secondary" onClick={() => setSchemaPath('')} style={{ fontSize: '0.8rem', padding: '4px 8px' }} title="Clear">✕</button>}
          </div>
          <span className="text-muted" style={{ display: 'block', marginTop: 4 }}>
            SQL file with table DDL, stored procedures, views, and triggers. Used to understand DB schema and resolve SP/view references in .NET code.
          </span>
        </div>

        <div className="mt-1">
          <label className="text-sm">AWS Profile</label>
          {awsProfiles.length > 0 ? (
            <select value={awsProfile} onChange={(e) => setAwsProfile(e.target.value)}>
              {awsProfiles.map(p => <option key={p} value={p}>{p}</option>)}
              {!awsProfiles.includes(awsProfile) && <option value={awsProfile}>{awsProfile}</option>}
            </select>
          ) : (
            <input type="text" value={awsProfile} onChange={(e) => setAwsProfile(e.target.value)} placeholder="default" />
          )}
          <span className="text-muted" style={{ display: 'block', marginTop: 4 }}>
            {awsProfiles.length > 0
              ? `${awsProfiles.length} profiles found in ~/.aws/credentials and ~/.aws/config`
              : 'The AWS CLI profile to use for Bedrock API calls (from ~/.aws/credentials)'}
          </span>
        </div>

        <div className="mt-1">
          <label className="text-sm">Design Priority: Cost vs Performance</label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
            <span style={{ fontSize: '0.8rem', color: designPriority === 'cost' ? 'var(--success)' : 'var(--text-muted)', fontWeight: designPriority === 'cost' ? 700 : 400 }}>💰 Cost</span>
            <input type="range" min={0} max={2} step={1}
              value={designPriority === 'cost' ? 0 : designPriority === 'balanced' ? 1 : 2}
              onChange={(e) => setDesignPriority(['cost', 'balanced', 'performance'][parseInt(e.target.value)])}
              style={{ flex: 1, accentColor: designPriority === 'cost' ? '#27ae60' : designPriority === 'performance' ? '#3498db' : '#f39c12' }}
            />
            <span style={{ fontSize: '0.8rem', color: designPriority === 'performance' ? 'var(--primary)' : 'var(--text-muted)', fontWeight: designPriority === 'performance' ? 700 : 400 }}>⚡ Performance</span>
          </div>
          <div style={{ textAlign: 'center', marginTop: 6 }}>
            <span className={`badge ${designPriority === 'cost' ? 'badge-success' : designPriority === 'performance' ? 'badge-warning' : 'badge-success'}`} style={{ fontSize: '0.75rem' }}>
              {designPriority === 'cost' && '💰 Optimize for Cost — minimize RCU/WCU, accept more client-side processing'}
              {designPriority === 'balanced' && '⚖️ Balanced — optimize hot paths for performance, cold paths for cost'}
              {designPriority === 'performance' && '⚡ Optimize for Performance — minimize latency, maximize server-side filtering'}
            </span>
          </div>
          <details style={{ marginTop: 10 }}>
            <summary style={{ cursor: 'pointer', fontSize: '0.78rem', color: 'var(--primary)' }}>View design decisions for "{designPriority}" mode</summary>
            <div style={{ marginTop: 8, fontSize: '0.78rem', lineHeight: 1.7 }}>
              <table className="data-table" style={{ fontSize: '0.75rem' }}>
                <thead><tr><th style={{ width: '18%' }}>Decision Area</th><th style={{ width: '27%' }}>💰 Cost</th><th style={{ width: '27%' }}>⚖️ Balanced</th><th style={{ width: '28%' }}>⚡ Performance</th></tr></thead>
                <tbody>
                  {designDecisions.map(([area, cost, balanced, perf], i) => (
                    <tr key={i}>
                      <td style={{ fontWeight: 600 }}>{area}</td>
                      <td style={{ background: designPriority === 'cost' ? 'rgba(39,174,96,0.08)' : undefined }}>{cost}</td>
                      <td style={{ background: designPriority === 'balanced' ? 'rgba(243,156,18,0.08)' : undefined }}>{balanced}</td>
                      <td style={{ background: designPriority === 'performance' ? 'rgba(52,152,219,0.08)' : undefined }}>{perf}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </div>

        <div className="mt-2 flex" style={{ gap: 8 }}>
          <button className="btn btn-secondary" onClick={() => setShowCreateForm(false)}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={handleCreate} disabled={loading || !name || !path}>
            {loading ? 'Creating...' : 'Create & Continue →'}
          </button>
        </div>
      </div>
      )}

      {/* Bedrock Validation Result */}
      {validationResult && !validationResult.ready && (
        <div className="card" style={{ borderLeft: '3px solid var(--danger)', marginTop: '0.75rem' }}>
          <strong>⚠️ Bedrock Model Access Check</strong>
          <p className="text-muted" style={{ marginTop: 4 }}>
            {validationResult.credentials_valid ? 'AWS credentials are valid.' : '❌ AWS credentials are invalid or expired.'}
          </p>
          <table className="data-table" style={{ marginTop: '0.5rem', fontSize: '0.82rem' }}>
            <thead><tr><th>Model</th><th>Status</th><th>Used By</th><th>Required</th></tr></thead>
            <tbody>
              {Object.entries(validationResult.models).map(([key, m]) => (
                <tr key={key}>
                  <td><strong>{key}</strong><br/><span className="text-muted" style={{ fontSize: '0.72rem' }}>{m.model_id}</span></td>
                  <td>{m.accessible ? <span className="badge badge-success">✅ Accessible</span> : <span className="badge badge-danger">❌ {m.error || 'Not accessible'}</span>}</td>
                  <td className="text-muted">{m.used_by}</td>
                  <td>{m.required ? 'Yes' : 'Optional'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {validationResult.instructions.length > 0 && (
            <div style={{ marginTop: '0.75rem' }}>
              <strong className="text-sm">How to fix:</strong>
              <ul style={{ paddingLeft: '1.25rem', marginTop: 4 }}>
                {validationResult.instructions.map((inst, i) => (
                  <li key={i} className="text-muted" style={{ fontSize: '0.82rem', lineHeight: 1.6 }}>{inst}</li>
                ))}
              </ul>
            </div>
          )}
          <button className="btn btn-secondary" style={{ marginTop: '0.75rem', fontSize: '0.8rem' }} onClick={async () => {
            setValidating(true); setValidationResult(null);
            try {
              const { data } = await projectsApi.validateBedrock(awsProfile);
              setValidationResult(data);
              if (data.ready) onNext();
            } catch (e: any) { setError(`Validation failed: ${(e as Error).message}`); }
            setValidating(false);
          }}>
            🔄 Retry Validation
          </button>
        </div>
      )}

      {/* Existing Projects */}
      {projects.length > 0 && (
        <div style={showCreateForm ? { opacity: 0.4, pointerEvents: 'none' as const } : undefined}
             data-testid="project-list">
          <h3 className="text-sm mb-1">Existing Projects</h3>
          {projects.map((p) => (
            <div key={p.id} className="card"
              onClick={() => setSelectedProjectId(prev => prev === p.id ? null : p.id)}
              onMouseEnter={() => setHoveredCardId(p.id)}
              onMouseLeave={() => setHoveredCardId(null)}
              style={{
                cursor: 'pointer',
                border: selectedProjectId === p.id ? '2px solid var(--primary)' : undefined,
                background: selectedProjectId === p.id
                  ? 'rgba(52,152,219,0.08)'
                  : hoveredCardId === p.id
                    ? 'var(--bg-hover, rgba(52,152,219,0.05))'
                    : 'transparent',
              }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <strong>{p.name}</strong>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  {selectedProjectId === p.id && <span className="badge badge-success">Selected</span>}
                  <button
                    className="btn btn-secondary"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm(`Delete project "${p.name}"? This removes all entities, patterns, and pipeline runs.`)) {
                        projectsApi.delete(p.id).then(() => {
                          setProjects(prev => prev.filter(proj => proj.id !== p.id));
                          if (selectedProjectId === p.id) setSelectedProjectId(null);
                          if (projectId === p.id) setProjectId(0 as any);
                        }).catch((err) => setError(`Failed to delete: ${err.message}`));
                      }
                    }}
                    style={{ fontSize: '0.7rem', padding: '2px 8px', color: 'var(--danger, #e74c3c)' }}
                    title="Delete project"
                  >✕ Remove</button>
                </div>
              </div>
              <div className="text-muted" style={{ fontSize: '0.85rem', marginTop: 4 }}>
                {p.path}
              </div>
              <div className="text-muted" style={{ fontSize: '0.85rem', marginTop: 2 }}>
                AWS Profile: {p.aws_profile || 'default'}
              </div>
              <div style={{ marginTop: 6, display: 'flex', gap: 8 }}>
                {p.schema_path && (
                  <span className="badge badge-success" style={{ fontSize: '0.65rem' }}>📄 SQL Schema</span>
                )}
                {p.design_priority && p.design_priority !== 'balanced' && (
                  <span className={`badge ${p.design_priority === 'cost' ? 'badge-success' : 'badge-warning'}`} style={{ fontSize: '0.7rem' }}>
                    {p.design_priority === 'cost' ? '💰 Cost' : '⚡ Perf'}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {!showCreateForm && selectedProjectId && (
        <div style={{ marginTop: '1rem' }}>
          <button className="btn btn-primary" onClick={async () => {
            const selectedProject = projects.find(p => p.id === selectedProjectId);
            if (!selectedProject) return;
            setValidating(true); setValidationResult(null); setError(null);
            try {
              const { data } = await projectsApi.validateBedrock(selectedProject.aws_profile || 'default');
              setValidationResult(data);
              if (data.ready) {
                setProjectId(selectedProjectId);
                onNext();
              }
            } catch (e: any) {
              setError(`Validation failed: ${e.message}`);
            }
            setValidating(false);
          }} disabled={validating}>
            {validating ? '🔄 Validating Bedrock access...' : 'Next →'}
          </button>
        </div>
      )}

      {/* Unified Path/File Picker Modal */}
      {picker.open && (
        <div className="modal-overlay" onMouseDown={() => setPicker(p => ({ ...p, open: false }))}>
          <div className="modal-content" onMouseDown={e => e.stopPropagation()} style={{ maxWidth: 600 }}>
            <div className="modal-header">
              <strong style={{ fontSize: '1rem' }}>{picker.mode === 'folder' ? '📁 Select Folder' : '📄 Select File'}</strong>
              <button onClick={() => setPicker(p => ({ ...p, open: false }))} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.2rem' }}>&#x2715;</button>
            </div>
            <div className="modal-body">
              <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                <input type="text" value={browseDir} onChange={(e) => setBrowseDir(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && loadDir(browseDir, picker.fileExts)}
                  style={{ flex: 1, fontSize: '0.82rem', fontFamily: 'monospace' }} placeholder="Enter path and press Enter" />
                <button className="btn btn-secondary" onClick={() => loadDir(browseDir, picker.fileExts)} style={{ fontSize: '0.8rem' }}>Go</button>
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 8, wordBreak: 'break-all' }}>{browseCurrent}</div>

              {browseCurrent !== browseParent && (
                <div onClick={() => loadDir(browseParent, picker.fileExts)}
                  style={{ padding: '6px 10px', cursor: 'pointer', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem' }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                  <span>⬆️</span> <span>..</span>
                </div>
              )}

              <div style={{ maxHeight: 350, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 6 }}>
                {browseLoading ? (
                  <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)' }}>Loading...</div>
                ) : browseDirs.length === 0 && browseFiles.length === 0 ? (
                  <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)' }}>Empty directory</div>
                ) : (<>
                  {browseDirs.map((d) => (
                    <div key={d.path}
                      onDoubleClick={() => loadDir(d.path, picker.fileExts)}
                      onClick={() => { setBrowseDir(d.path); setSelectedItem(d.path); }}
                      style={{ padding: '6px 10px', cursor: 'pointer', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem',
                        background: selectedItem === d.path ? 'rgba(52,152,219,0.1)' : 'transparent' }}
                      onMouseEnter={e => { if (selectedItem !== d.path) e.currentTarget.style.background = 'var(--bg-hover)'; }}
                      onMouseLeave={e => { if (selectedItem !== d.path) e.currentTarget.style.background = 'transparent'; }}>
                      <span>📁</span> <span>{d.name}</span>
                    </div>
                  ))}
                  {browseFiles.map((f) => (
                    <div key={f.path}
                      onClick={() => { setSelectedItem(f.path); }}
                      onDoubleClick={() => { picker.onSelect(f.path); setPicker(p => ({ ...p, open: false })); }}
                      style={{ padding: '6px 10px', cursor: 'pointer', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem',
                        background: selectedItem === f.path ? 'rgba(52,152,219,0.1)' : 'transparent' }}
                      onMouseEnter={e => { if (selectedItem !== f.path) e.currentTarget.style.background = 'var(--bg-hover)'; }}
                      onMouseLeave={e => { if (selectedItem !== f.path) e.currentTarget.style.background = 'transparent'; }}>
                      <span>📄</span> <span>{f.name}</span>
                    </div>
                  ))}
                </>)}
              </div>

              <div className="text-muted" style={{ fontSize: '0.72rem', marginTop: 8 }}>
                {picker.mode === 'folder'
                  ? 'Single-click to select, double-click to navigate into folder'
                  : 'Single-click to select, double-click file to confirm. Double-click folder to navigate.'}
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
                <button className="btn btn-secondary" onClick={() => setPicker(p => ({ ...p, open: false }))}>Cancel</button>
                <button className="btn btn-primary" onClick={handlePickerSelect}>
                  {picker.mode === 'folder' ? 'Select This Folder' : 'Select This File'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
