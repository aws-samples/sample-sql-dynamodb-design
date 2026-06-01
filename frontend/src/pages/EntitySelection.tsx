import { useState, useEffect } from 'react';
import { entitiesApi, scopeApi, Entity } from '../api/client';

interface Props { projectId: number; onNext: () => void; }

export default function EntitySelection({ projectId, onNext }: Props) {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [rowSizes, setRowSizes] = useState<Record<number, number>>({});

  useEffect(() => {
    entitiesApi.list(projectId).then((r) => {
      setEntities(r.data);
      setSelected(new Set(r.data.filter((e) => e.selected).map((e) => e.name)));
      const sizes: Record<number, number> = {};
      r.data.forEach((e) => { sizes[e.id] = e.average_row_size_kb; });
      setRowSizes(sizes);
    });
  }, [projectId]);

  const toggle = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  };

  const updateRowSize = (id: number, value: number) => {
    setRowSizes((prev) => ({ ...prev, [id]: value }));
  };

  const selectAll = () => setSelected(new Set(entities.map((e) => e.name)));
  const selectNone = () => setSelected(new Set());

  const handleSave = async () => {
    for (const entity of entities) {
      const newSize = rowSizes[entity.id];
      if (newSize !== entity.average_row_size_kb) {
        await entitiesApi.update(projectId, entity.id, { average_row_size_kb: newSize });
      }
    }
    const names = Array.from(selected);
    const mode = names.length === entities.length ? 'full' : names.length > 0 ? 'microservice' : 'full';
    await scopeApi.set(projectId, { mode, selected_entities: names });
    onNext();
  };

  return (
    <div>
      <h2>🏗️ Entity Selection</h2>

      <div className="card guidance-card">
        <p style={{ fontSize: '0.85rem', lineHeight: 1.7 }}>
          <strong>Why set average row size?</strong> DynamoDB charges for Read Capacity Units (RCU) and Write Capacity Units (WCU)
          based on item size. One RCU handles a 4 KB strongly-consistent read, and one WCU handles a 1 KB write.
          Accurate row sizes directly affect capacity estimation, cost projections, and whether entities should be
          flattened into a single item or stored as separate items. Overestimating wastes budget; underestimating causes throttling.
        </p>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
          📖 <a href="https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ProvisionedThroughput.html"
            target="_blank" rel="noopener noreferrer" style={{ color: 'var(--primary)' }}>
            AWS DynamoDB Provisioned Throughput Guide
          </a>
          {' · '}
          <a href="https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-cost-optimization.html"
            target="_blank" rel="noopener noreferrer" style={{ color: 'var(--primary)' }}>
            Cost Optimization Best Practices
          </a>
          {' · '}
          <a href="https://aws.amazon.com/blogs/database/sql-to-nosql-modeling-data-in-amazon-dynamodb/"
            target="_blank" rel="noopener noreferrer" style={{ color: 'var(--primary)' }}>
            Metrics-Driven Approach: Single vs Vertical Partition
          </a>
        </p>
      </div>

      <div className="card">
        <div className="flex-between mb-1">
          <span className="text-sm">{selected.size} of {entities.length} entities selected</span>
          <div>
            <button className="btn btn-secondary" onClick={selectAll} style={{ marginRight: 4 }}>Select All</button>
            <button className="btn btn-secondary" onClick={selectNone}>Clear</button>
          </div>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: 40 }}></th>
              <th>Entity</th>
              <th>SQL Table</th>
              <th>Avg Row Size (KB)</th>
              <th>Relationships</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {entities.map((e) => (
              <tr key={e.name} onClick={() => toggle(e.name)} style={{ cursor: 'pointer' }}>
                <td><input type="checkbox" checked={selected.has(e.name)} onChange={() => toggle(e.name)} /></td>
                <td><strong>{e.name}</strong></td>
                <td className="text-muted">{e.sql_table || '—'}</td>
                <td>
                  <input type="number" step="0.1" min="0"
                    value={rowSizes[e.id] ?? e.average_row_size_kb}
                    onChange={(ev) => updateRowSize(e.id, parseFloat(ev.target.value) || 0)}
                    onClick={(ev) => ev.stopPropagation()}
                    style={{ width: 80, textAlign: 'right' }} />
                </td>
                <td className="text-muted" style={{ fontSize: '0.8rem' }}>
                  {e.relationships_json
                    ? Object.entries(e.relationships_json).map(([k, v]) => `${k}: ${v}`).join(', ')
                    : '—'}
                </td>
                <td className="text-muted" style={{ fontSize: '0.8rem' }}>
                  {e.notes ? (
                    <span className="info-tooltip">
                      {e.notes.length > 30 ? e.notes.slice(0, 30) + '...' : e.notes}
                      <span className="info-icon" style={{ marginLeft: 4, cursor: 'help' }}>ℹ️</span>
                      <span className="tooltip-text">{e.notes}</span>
                    </span>
                  ) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-2">
        <button className="btn btn-primary" onClick={handleSave} disabled={selected.size === 0}>
          Next: Access Patterns →
        </button>
      </div>
    </div>
  );
}
