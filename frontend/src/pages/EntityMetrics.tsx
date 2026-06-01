import { useState, useEffect } from 'react';
import { entitiesApi, Entity } from '../api/client';

interface Props { projectId: number; onNext: () => void; }

export default function EntityMetrics({ projectId, onNext }: Props) {
  const [entities, setEntities] = useState<Entity[]>([]);

  useEffect(() => {
    entitiesApi.list(projectId).then((r) => {
      setEntities(r.data.filter((e) => e.selected));
    });
  }, [projectId]);

  const updateSize = (id: number, size: number) => {
    setEntities((prev) => prev.map((e) => e.id === id ? { ...e, average_row_size_kb: size } : e));
  };

  const handleSave = async () => {
    await Promise.all(
      entities.map((e) => entitiesApi.update(projectId, e.id, { average_row_size_kb: e.average_row_size_kb }))
    );
    onNext();
  };

  return (
    <div>
      <h2>📏 Entity Metrics</h2>
      <p className="text-muted mb-1">Adjust average row sizes. These drive RCU/WCU capacity estimates.</p>
      {entities.map((e) => (
        <div key={e.id} className="card">
          <div className="flex-between">
            <div>
              <strong>{e.name}</strong>
              <span className="text-muted" style={{ marginLeft: 8 }}>{e.sql_table}</span>
              {e.fields && <div className="text-muted mt-1">{e.fields}</div>}
              {e.estimated_field_total_bytes && (
                <div className="text-muted">~{e.estimated_field_total_bytes} bytes + ~100 overhead</div>
              )}
            </div>
            <div style={{ width: 120 }}>
              <label className="text-muted">Avg KB</label>
              <input type="number" step="0.05" min="0.01" max="400"
                value={e.average_row_size_kb}
                onChange={(ev) => updateSize(e.id, parseFloat(ev.target.value) || 0)}
              />
            </div>
          </div>
        </div>
      ))}
      <button className="btn btn-primary mt-2" onClick={handleSave}>Save & Continue →</button>
    </div>
  );
}
