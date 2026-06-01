import { useState, useEffect } from 'react';
import { patternsApi, entitiesApi, AccessPattern, WritePattern, Entity, AccessPatternCreate, WritePatternCreate } from '../api/client';

interface Props { projectId: number; onNext: () => void; }

interface FormErrors { name?: string; entities?: string; requests_per_hour?: string; }

function AddReadPatternForm({ projectId, entities, onCreated, onCancel }: {
  projectId: number; entities: Entity[]; onCreated: (p: AccessPattern) => void; onCancel: () => void;
}) {
  const [name, setName] = useState('');
  const [selectedEntities, setSelectedEntities] = useState<string[]>([]);
  const [requestsPerHour, setRequestsPerHour] = useState<number | ''>('');
  const [avgItemsReturned, setAvgItemsReturned] = useState(1);
  const [sourceCode, setSourceCode] = useState('');
  const [errors, setErrors] = useState<FormErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [isRetryable, setIsRetryable] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const toggleEntity = (entityName: string) => {
    setSelectedEntities((prev) =>
      prev.includes(entityName) ? prev.filter((e) => e !== entityName) : [...prev, entityName]
    );
  };

  const validate = (): boolean => {
    const errs: FormErrors = {};
    if (!name.trim()) errs.name = 'Name is required';
    if (selectedEntities.length === 0) errs.entities = 'Select at least one entity';
    if (!requestsPerHour || requestsPerHour <= 0) errs.requests_per_hour = 'Must be a positive number';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = async () => {
    setApiError(null);
    setIsRetryable(false);
    if (!validate()) return;
    setSubmitting(true);
    try {
      const data: AccessPatternCreate = {
        name: name.trim(),
        source_entities: selectedEntities,
        requests_per_hour: requestsPerHour as number,
        avg_items_returned: avgItemsReturned,
        ...(sourceCode.trim() ? { source_code: sourceCode.trim() } : {}),
      };
      const res = await patternsApi.createAccess(projectId, data);
      onCreated(res.data);
      setSuccessMsg(`Pattern "${res.data.name}" added successfully`);
      setTimeout(() => onCancel(), 1200);
    } catch (err: any) {
      if (err.response?.status === 422) {
        setApiError(err.response.data?.detail || 'Validation failed');
        setIsRetryable(false);
      } else if (err.response?.status === 503) {
        setApiError('Validation service unavailable. Please try again.');
        setIsRetryable(true);
      } else {
        setApiError('An unexpected error occurred.');
        setIsRetryable(false);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="card" style={{ borderLeft: '3px solid var(--primary)' }}>
      <div style={{ marginBottom: '0.75rem' }}><strong>Add Read Pattern</strong></div>
      <div style={{ marginBottom: '0.75rem' }}>
        <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 4 }}>Name *</label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Get users by email" />
        {errors.name && <div style={{ color: 'var(--danger)', fontSize: '0.75rem', marginTop: 2 }}>{errors.name}</div>}
      </div>
      <div style={{ marginBottom: '0.75rem' }}>
        <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 4 }}>Source Entities *</label>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
          {entities.map((ent) => (
            <label key={ent.id} className="checkbox-label" style={{ fontSize: '0.8rem', padding: '0.25rem 0.5rem' }}>
              <input type="checkbox" checked={selectedEntities.includes(ent.name)} onChange={() => toggleEntity(ent.name)} />
              {ent.name}
            </label>
          ))}
        </div>
        {errors.entities && <div style={{ color: 'var(--danger)', fontSize: '0.75rem', marginTop: 2 }}>{errors.entities}</div>}
      </div>
      <div className="grid-2" style={{ marginBottom: '0.75rem' }}>
        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 4 }}>Requests per Hour *</label>
          <input type="number" min="1" value={requestsPerHour} onChange={(e) => setRequestsPerHour(parseInt(e.target.value) || '')} />
          {errors.requests_per_hour && <div style={{ color: 'var(--danger)', fontSize: '0.75rem', marginTop: 2 }}>{errors.requests_per_hour}</div>}
        </div>
        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 4 }}>Avg Items Returned</label>
          <input type="number" min="1" value={avgItemsReturned} onChange={(e) => setAvgItemsReturned(parseInt(e.target.value) || 1)} />
        </div>
      </div>
      <div style={{ marginBottom: '0.75rem' }}>
        <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 4 }}>Source Code (optional)</label>
        <textarea value={sourceCode} onChange={(e) => setSourceCode(e.target.value)} rows={3} placeholder="Paste LINQ/SQL query here..."
          style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '0.5rem 0.75rem', color: 'var(--text)', fontSize: '0.8rem', fontFamily: 'monospace', resize: 'vertical' }} />
      </div>
      {apiError && (
        <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid var(--danger)', borderRadius: 6, padding: '0.5rem 0.75rem', marginBottom: '0.75rem', fontSize: '0.8rem', color: '#fca5a5' }}>
          {apiError}
          {isRetryable && <button className="btn btn-secondary" style={{ marginLeft: 8, padding: '0.2rem 0.5rem', fontSize: '0.75rem' }} onClick={handleSubmit}>Retry</button>}
        </div>
      )}
      {successMsg && (
        <div style={{ background: 'rgba(34,197,94,0.1)', border: '1px solid var(--success)', borderRadius: 6, padding: '0.5rem 0.75rem', marginBottom: '0.75rem', fontSize: '0.8rem', color: '#86efac' }}>
          {successMsg}
        </div>
      )}
      <div className="flex" style={{ gap: '0.5rem' }}>
        <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>{submitting ? 'Validating...' : 'Submit'}</button>
        <button className="btn btn-secondary" onClick={onCancel} disabled={submitting}>Cancel</button>
      </div>
    </div>
  );
}

function AddWritePatternForm({ projectId, entities, onCreated, onCancel }: {
  projectId: number; entities: Entity[]; onCreated: (p: WritePattern) => void; onCancel: () => void;
}) {
  const [name, setName] = useState('');
  const [selectedEntities, setSelectedEntities] = useState<string[]>([]);
  const [requestsPerHour, setRequestsPerHour] = useState<number | ''>('');
  const [itemsPerTransaction, setItemsPerTransaction] = useState(1);
  const [sourceCode, setSourceCode] = useState('');
  const [errors, setErrors] = useState<FormErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [isRetryable, setIsRetryable] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const toggleEntity = (entityName: string) => {
    setSelectedEntities((prev) =>
      prev.includes(entityName) ? prev.filter((e) => e !== entityName) : [...prev, entityName]
    );
  };

  const validate = (): boolean => {
    const errs: FormErrors = {};
    if (!name.trim()) errs.name = 'Name is required';
    if (selectedEntities.length === 0) errs.entities = 'Select at least one entity';
    if (!requestsPerHour || requestsPerHour <= 0) errs.requests_per_hour = 'Must be a positive number';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = async () => {
    setApiError(null);
    setIsRetryable(false);
    if (!validate()) return;
    setSubmitting(true);
    try {
      const data: WritePatternCreate = {
        name: name.trim(),
        target_entities: selectedEntities,
        requests_per_hour: requestsPerHour as number,
        items_per_transaction: itemsPerTransaction,
        ...(sourceCode.trim() ? { source_code: sourceCode.trim() } : {}),
      };
      const res = await patternsApi.createWrite(projectId, data);
      onCreated(res.data);
      setSuccessMsg(`Pattern "${res.data.name}" added successfully`);
      setTimeout(() => onCancel(), 1200);
    } catch (err: any) {
      if (err.response?.status === 422) {
        setApiError(err.response.data?.detail || 'Validation failed');
        setIsRetryable(false);
      } else if (err.response?.status === 503) {
        setApiError('Validation service unavailable. Please try again.');
        setIsRetryable(true);
      } else {
        setApiError('An unexpected error occurred.');
        setIsRetryable(false);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="card" style={{ borderLeft: '3px solid var(--primary)' }}>
      <div style={{ marginBottom: '0.75rem' }}><strong>Add Write Pattern</strong></div>
      <div style={{ marginBottom: '0.75rem' }}>
        <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 4 }}>Name *</label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Update order status" />
        {errors.name && <div style={{ color: 'var(--danger)', fontSize: '0.75rem', marginTop: 2 }}>{errors.name}</div>}
      </div>
      <div style={{ marginBottom: '0.75rem' }}>
        <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 4 }}>Target Entities *</label>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
          {entities.map((ent) => (
            <label key={ent.id} className="checkbox-label" style={{ fontSize: '0.8rem', padding: '0.25rem 0.5rem' }}>
              <input type="checkbox" checked={selectedEntities.includes(ent.name)} onChange={() => toggleEntity(ent.name)} />
              {ent.name}
            </label>
          ))}
        </div>
        {errors.entities && <div style={{ color: 'var(--danger)', fontSize: '0.75rem', marginTop: 2 }}>{errors.entities}</div>}
      </div>
      <div className="grid-2" style={{ marginBottom: '0.75rem' }}>
        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 4 }}>Requests per Hour *</label>
          <input type="number" min="1" value={requestsPerHour} onChange={(e) => setRequestsPerHour(parseInt(e.target.value) || '')} />
          {errors.requests_per_hour && <div style={{ color: 'var(--danger)', fontSize: '0.75rem', marginTop: 2 }}>{errors.requests_per_hour}</div>}
        </div>
        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 4 }}>Items per Transaction</label>
          <input type="number" min="1" value={itemsPerTransaction} onChange={(e) => setItemsPerTransaction(parseInt(e.target.value) || 1)} />
        </div>
      </div>
      <div style={{ marginBottom: '0.75rem' }}>
        <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 4 }}>Source Code (optional)</label>
        <textarea value={sourceCode} onChange={(e) => setSourceCode(e.target.value)} rows={3} placeholder="Paste LINQ/SQL query here..."
          style={{ width: '100%', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '0.5rem 0.75rem', color: 'var(--text)', fontSize: '0.8rem', fontFamily: 'monospace', resize: 'vertical' }} />
      </div>
      {apiError && (
        <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid var(--danger)', borderRadius: 6, padding: '0.5rem 0.75rem', marginBottom: '0.75rem', fontSize: '0.8rem', color: '#fca5a5' }}>
          {apiError}
          {isRetryable && <button className="btn btn-secondary" style={{ marginLeft: 8, padding: '0.2rem 0.5rem', fontSize: '0.75rem' }} onClick={handleSubmit}>Retry</button>}
        </div>
      )}
      {successMsg && (
        <div style={{ background: 'rgba(34,197,94,0.1)', border: '1px solid var(--success)', borderRadius: 6, padding: '0.5rem 0.75rem', marginBottom: '0.75rem', fontSize: '0.8rem', color: '#86efac' }}>
          {successMsg}
        </div>
      )}
      <div className="flex" style={{ gap: '0.5rem' }}>
        <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>{submitting ? 'Validating...' : 'Submit'}</button>
        <button className="btn btn-secondary" onClick={onCancel} disabled={submitting}>Cancel</button>
      </div>
    </div>
  );
}

export default function AccessPatterns({ projectId, onNext }: Props) {
  const [reads, setReads] = useState<AccessPattern[]>([]);
  const [writes, setWrites] = useState<WritePattern[]>([]);
  const [expandedCode, setExpandedCode] = useState<number | null>(null);
  const [entities, setEntities] = useState<Entity[]>([]);
  const [showAddRead, setShowAddRead] = useState(false);
  const [showAddWrite, setShowAddWrite] = useState(false);

  useEffect(() => {
    patternsApi.listAccess(projectId).then((r) => setReads(r.data));
    patternsApi.listWrite(projectId).then((r) => setWrites(r.data));
    entitiesApi.list(projectId).then((r) => setEntities(r.data));
  }, [projectId]);

  const updateRead = (id: number, field: string, value: number) => {
    setReads((prev) => prev.map((p) => p.id === id ? { ...p, [field]: value } : p));
  };

  const updateWrite = (id: number, field: string, value: number) => {
    setWrites((prev) => prev.map((p) => p.id === id ? { ...p, [field]: value } : p));
  };

  const handleSave = async () => {
    await Promise.all([
      ...reads.map((p) => patternsApi.updateAccess(projectId, p.id, {
        requests_per_hour: p.requests_per_hour, avg_items_returned: p.avg_items_returned
      })),
      ...writes.map((p) => patternsApi.updateWrite(projectId, p.id, {
        requests_per_hour: p.requests_per_hour
      })),
    ]);
    onNext();
  };

  const handleDeleteRead = async (id: number) => {
    if (!confirm('Delete this user-added pattern?')) return;
    await patternsApi.deleteAccess(projectId, id);
    setReads((prev) => prev.filter((p) => p.id !== id));
  };

  const handleDeleteWrite = async (id: number) => {
    if (!confirm('Delete this user-added pattern?')) return;
    await patternsApi.deleteWrite(projectId, id);
    setWrites((prev) => prev.filter((p) => p.id !== id));
  };

  const badge = (c: string | null) => {
    if (c === 'cross_boundary') return <span className="badge badge-warning">Cross-boundary</span>;
    if (c === 'excluded') return <span className="badge badge-danger">Excluded</span>;
    return <span className="badge badge-success">In scope</span>;
  };

  const sourceBadge = (source: string | null) => {
    if (source === 'user') {
      return <span style={{ display: 'inline-block', padding: '0.15rem 0.5rem', borderRadius: 4, fontSize: '0.75rem', fontWeight: 600, background: '#e8f5e9', color: '#2e7d32', border: '1px solid #a5d6a7', marginLeft: 6 }}>User</span>;
    }
    return <span style={{ display: 'inline-block', padding: '0.15rem 0.5rem', borderRadius: 4, fontSize: '0.75rem', fontWeight: 600, background: 'var(--bg)', color: 'var(--text-muted)', border: '1px solid var(--border)', marginLeft: 6 }}>Extractor</span>;
  };

  const toggleCode = (id: number) => setExpandedCode(expandedCode === id ? null : id);
  const filteredReads = reads.filter((p) => p.classification !== 'excluded');
  const filteredWrites = writes.filter((p) => p.classification !== 'excluded');

  return (
    <div>
      <h2>📊 Access Patterns</h2>

      <div className="card guidance-card">
        <p style={{ fontSize: '0.85rem', lineHeight: 1.7 }}>
          <strong>Why specify Requests per Hour?</strong> This metric determines how many Read Capacity Units (RCU) 
          and Write Capacity Units (WCU) your DynamoDB table needs. Higher request rates require more provisioned 
          capacity or on-demand scaling headroom.
        </p>
        <p style={{ fontSize: '0.85rem', lineHeight: 1.7, marginTop: '0.5rem' }}>
          <strong>Why specify Average Items Returned?</strong> For read patterns, this affects RCU calculation. 
          A query returning 10 items of 2KB each consumes more RCUs than one returning a single item. 
          This helps estimate whether to use Query vs GetItem and impacts GSI design decisions.
        </p>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
          📖 <a href="https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ProvisionedThroughput.html"
            target="_blank" rel="noopener noreferrer" style={{ color: 'var(--primary)' }}>
            DynamoDB Capacity Planning Guide
          </a>
        </p>
      </div>

      <h3 className="mt-2 mb-1">Read Patterns ({filteredReads.length})</h3>
      {!showAddRead && (
        <button className="btn btn-primary" style={{ marginBottom: '0.75rem', fontSize: '0.8rem' }} onClick={() => setShowAddRead(true)}>
          ➕ Add Pattern
        </button>
      )}
      {showAddRead && (
        <AddReadPatternForm
          projectId={projectId}
          entities={entities}
          onCreated={(p) => setReads((prev) => [...prev, p])}
          onCancel={() => setShowAddRead(false)}
        />
      )}
      {filteredReads.map((p) => (
        <div key={p.id} className="card">
          <div className="flex-between" style={{ alignItems: 'flex-start' }}>
            <div style={{ flex: 1 }}>
              <strong>{p.pattern_id}: {p.name}</strong> {badge(p.classification)} {sourceBadge(p.source)}
              {p.source === 'user' && (
                <button onClick={() => handleDeleteRead(p.id)} title="Delete user pattern"
                  style={{ marginLeft: 8, background: 'none', border: 'none', color: 'var(--danger)', cursor: 'pointer', fontSize: '0.85rem', padding: 0 }}>🗑</button>
              )}
              <div className="text-muted" style={{ marginTop: 4 }}>
                Entities: {p.source_entities?.join(', ') || '—'}
                {p.notes && <span> · {p.notes}</span>}
              </div>
              <button className="btn btn-secondary" style={{ marginTop: 8, padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
                onClick={() => toggleCode(p.id)}>
                {expandedCode === p.id ? '▼ Hide Query' : '▶ Show Query'}
              </button>
            </div>
            <div className="flex" style={{ gap: '1rem', alignItems: 'flex-end' }}>
              <div style={{ textAlign: 'right' }}>
                <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 4 }}>Requests per Hour</label>
                <input type="number" step="100" min="0" value={p.requests_per_hour}
                  onChange={(e) => updateRead(p.id, 'requests_per_hour', parseInt(e.target.value) || 0)}
                  style={{ width: 120, textAlign: 'right' }} />
              </div>
              <div style={{ textAlign: 'right' }}>
                <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 4 }}>Avg Items Returned</label>
                <input type="number" step="1" min="1" value={p.avg_items_returned}
                  onChange={(e) => updateRead(p.id, 'avg_items_returned', parseInt(e.target.value) || 1)}
                  style={{ width: 100, textAlign: 'right' }} />
              </div>
            </div>
          </div>
          {expandedCode === p.id && (
            <pre className="code-block">{p.source_code || `-- Original LINQ/SQL not captured during extraction\n-- Pattern: ${p.name}\n-- Entities: ${p.source_entities?.join(', ') || 'N/A'}`}</pre>
          )}
        </div>
      ))}

      <h3 className="mt-2 mb-1">Write Patterns ({filteredWrites.length})</h3>
      {!showAddWrite && (
        <button className="btn btn-primary" style={{ marginBottom: '0.75rem', fontSize: '0.8rem' }} onClick={() => setShowAddWrite(true)}>
          ➕ Add Pattern
        </button>
      )}
      {showAddWrite && (
        <AddWritePatternForm
          projectId={projectId}
          entities={entities}
          onCreated={(p) => setWrites((prev) => [...prev, p])}
          onCancel={() => setShowAddWrite(false)}
        />
      )}
      {filteredWrites.map((p) => (
        <div key={p.id} className="card">
          <div className="flex-between" style={{ alignItems: 'flex-start' }}>
            <div style={{ flex: 1 }}>
              <strong>{p.pattern_id}: {p.name}</strong> {badge(p.classification)} {sourceBadge(p.source)}
              {p.source === 'user' && (
                <button onClick={() => handleDeleteWrite(p.id)} title="Delete user pattern"
                  style={{ marginLeft: 8, background: 'none', border: 'none', color: 'var(--danger)', cursor: 'pointer', fontSize: '0.85rem', padding: 0 }}>🗑</button>
              )}
              <div className="text-muted" style={{ marginTop: 4 }}>
                Entities: {p.target_entities?.join(', ') || '—'}
                {p.notes && <span> · {p.notes}</span>}
              </div>
              <button className="btn btn-secondary" style={{ marginTop: 8, padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
                onClick={() => toggleCode(p.id + 10000)}>
                {expandedCode === p.id + 10000 ? '▼ Hide Query' : '▶ Show Query'}
              </button>
            </div>
            <div style={{ textAlign: 'right' }}>
              <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 4 }}>Requests per Hour</label>
              <input type="number" step="100" min="0" value={p.requests_per_hour}
                onChange={(e) => updateWrite(p.id, 'requests_per_hour', parseInt(e.target.value) || 0)}
                style={{ width: 120, textAlign: 'right' }} />
            </div>
          </div>
          {expandedCode === p.id + 10000 && (
            <pre className="code-block">{p.source_code || `-- Original LINQ/SQL not captured during extraction\n-- Pattern: ${p.name}\n-- Entities: ${p.target_entities?.join(', ') || 'N/A'}`}</pre>
          )}
        </div>
      ))}

      <button className="btn btn-primary mt-2" onClick={handleSave}>Next: Run Pipeline →</button>
    </div>
  );
}
