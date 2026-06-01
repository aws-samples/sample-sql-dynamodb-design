import { useState, useEffect } from 'react';
import { pipelineApi } from '../api/client';

interface Props { projectId: number; onNext: () => void; }

interface RoslynEntity { name: string; table?: string; fields: { name: string; type: string; maxLength?: number; isKey: boolean }[]; relationships: { target: string; type: string; navigationProperty?: string }[]; }
interface RoslynMethod { file: string; class: string; method: string; returnType: string; parameters: { name: string; type: string }[]; linqExpression?: string; entities: string[]; operation: string; lineNumber: number; }
interface RoslynAnalysis { projectPath: string; totalCsFiles: number; filesAnalyzed: number; efCoreDetected: boolean; dapperDetected: boolean; rawSqlDetected: boolean; entities: RoslynEntity[]; accessMethods: RoslynMethod[]; storedProcedures: { name: string; calledFrom: string }[]; }

export default function RunExtract({ projectId, onNext }: Props) {
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [done, setDone] = useState(false);
  const [counts, setCounts] = useState<{ entities: number; access_patterns: number; write_patterns: number } | null>(null);
  const [checking, setChecking] = useState(true);
  const [lastRun, setLastRun] = useState<string | null>(null);
  const [roslynData, setRoslynData] = useState<RoslynAnalysis | null>(null);
  const [showRoslyn, setShowRoslyn] = useState(false);
  const [roslynLoading, setRoslynLoading] = useState(false);
  const [confidence, setConfidence] = useState<{ score: number; rounds: number } | null>(null);

  useEffect(() => {
    // Single API call to check extraction status (replaces 4 separate calls)
    pipelineApi.getSummary(projectId).then(({ data }) => {
      if (data.has_data) {
        setCounts({ entities: data.entities, access_patterns: data.access_patterns, write_patterns: data.write_patterns });
        if (data.last_extract_completed_at) {
          setLastRun(new Date(data.last_extract_completed_at).toLocaleString());
        }
        if (data.confidence_score !== null && data.confidence_score !== undefined) {
          setConfidence({ score: data.confidence_score, rounds: data.rounds_executed || 1 });
        }
        setDone(true);
      }
      setChecking(false);
    }).catch(() => setChecking(false));
  }, [projectId]);

  const addLog = (msg: string) => setLogs((prev) => [...prev, msg]);

  function getConfidenceColor(score: number): string {
    if (score > 0.8) return 'var(--success)';
    if (score >= 0.5) return '#f0ad4e';
    return 'var(--danger)';
  }

  const handleExtract = () => {
    setRunning(true);
    setDone(false);
    setLogs([]);
    setCounts(null);
    setLastRun(null);
    setConfidence(null);

    const url = pipelineApi.extractUrl(projectId);

    fetch(url, { method: 'POST' }).then(async (response) => {
      if (!response.body) {
        addLog('❌ No response stream');
        setRunning(false);
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done: streamDone, value } = await reader.read();
        if (streamDone) break;
        const text = decoder.decode(value, { stream: true });
        for (const line of text.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.message) addLog(data.message);
            if (data.error) { addLog(`❌ ${data.error}`); setRunning(false); return; }
            if (data.status === 'completed') {
              setCounts({ entities: data.entities, access_patterns: data.access_patterns, write_patterns: data.write_patterns });
              if (data.confidence_score !== undefined) {
                setConfidence({ score: data.confidence_score, rounds: data.rounds_executed });
              }
              addLog(`✅ Extraction complete: ${data.entities} entities, ${data.access_patterns} access patterns, ${data.write_patterns} write patterns`);
              setLastRun(new Date().toLocaleString());
              setDone(true);
              setRunning(false);
            }
          } catch { /* skip */ }
        }
      }
      setRunning(false);
    }).catch((e) => { addLog(`❌ Failed: ${e.message}`); setRunning(false); });
  };

  const loadRoslynAnalysis = async () => {
    if (roslynData) { setShowRoslyn(!showRoslyn); return; }
    setRoslynLoading(true);
    try {
      const { data } = await pipelineApi.getLatestResult(projectId, 'roslyn_analysis');
      if (data?.content) {
        setRoslynData(JSON.parse(data.content));
        setShowRoslyn(true);
      }
    } catch { /* no roslyn data available */ }
    setRoslynLoading(false);
  };

  if (checking) return <div className="card">Checking previous extraction...</div>;

  return (
    <div>
      <h2>🔍 Extract Entities</h2>
      <div className="card">
        <p className="text-sm">Scan the .NET project to discover entities, access patterns, and write patterns using the AI Extractor agent.</p>
      </div>

      {done && counts && !running && (
        <div className="card" style={{ borderLeft: '3px solid var(--success)' }}>
          <strong>Previous extraction found</strong>
          {lastRun && <span className="text-muted" style={{ marginLeft: 8 }}>Last run: {lastRun}</span>}
          <p style={{ marginTop: 8 }}>
            {counts.entities} entities, {counts.access_patterns} access patterns, {counts.write_patterns} write patterns
          </p>
          {confidence && (
            <p style={{ marginTop: 4 }}>
              <span style={{ color: getConfidenceColor(confidence.score), fontWeight: 600 }}>
                {Math.round(confidence.score * 100)}% confidence
              </span>
              <span className="text-muted" style={{ marginLeft: 8 }}>
                {confidence.rounds === 1
                  ? 'Consensus reached in 1 round'
                  : `${confidence.rounds} rounds executed, best-effort result`}
              </span>
            </p>
          )}
          <div className="mt-2 flex" style={{ gap: '0.5rem' }}>
            <button className="btn btn-primary" onClick={onNext}>Next: Select Entities →</button>
            <button className="btn btn-secondary" onClick={handleExtract}>🔄 Re-run Extraction</button>
            <button className="btn btn-secondary" onClick={loadRoslynAnalysis} disabled={roslynLoading}>
              {roslynLoading ? '...' : '🔬'} {showRoslyn ? 'Hide' : 'View'} Roslyn Analysis
            </button>
          </div>
        </div>
      )}

      {/* Roslyn Analysis Viewer */}
      {showRoslyn && roslynData && (
        <div className="card" style={{ marginTop: '0.75rem', borderLeft: '3px solid var(--primary)' }}>
          <div className="flex-between">
            <strong>🔬 Roslyn Semantic Analysis</strong>
            <span className="text-muted" style={{ fontSize: '0.78rem' }}>
              {roslynData.filesAnalyzed}/{roslynData.totalCsFiles} files · 
              {roslynData.entities.length} entities · 
              {roslynData.accessMethods.length} methods
              {roslynData.efCoreDetected && ' · EF Core'}
              {roslynData.dapperDetected && ' · Dapper'}
              {roslynData.rawSqlDetected && ' · Raw SQL'}
            </span>
          </div>
          <p className="text-muted" style={{ fontSize: '0.78rem', marginTop: 4 }}>
            This is the raw data extracted by the .NET Compiler Platform (Roslyn) before being sent to the AI agent.
          </p>

          <details style={{ marginTop: '0.75rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--primary)', fontSize: '0.85rem', fontWeight: 600 }}>
              Entities ({roslynData.entities.length})
            </summary>
            <table className="data-table" style={{ marginTop: '0.5rem', fontSize: '0.8rem' }}>
              <thead><tr><th>Entity</th><th>Table</th><th>Fields</th><th>Relationships</th></tr></thead>
              <tbody>
                {roslynData.entities.map(e => (
                  <tr key={e.name}>
                    <td><strong>{e.name}</strong></td>
                    <td className="text-muted">{e.table || '—'}</td>
                    <td className="text-muted">{e.fields.length > 0 ? e.fields.map(f => f.name).join(', ') : '—'}</td>
                    <td>{e.relationships.length > 0 ? e.relationships.map(r => `${r.type} → ${r.target}`).join(', ') : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>

          <details style={{ marginTop: '0.5rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--primary)', fontSize: '0.85rem', fontWeight: 600 }}>
              Access Methods ({roslynData.accessMethods.length})
            </summary>
            <div style={{ marginTop: '0.5rem' }}>
              {roslynData.accessMethods.map((m, i) => (
                <div key={i} style={{ padding: '0.5rem', borderBottom: '1px solid var(--border)', fontSize: '0.8rem' }}>
                  <div>
                    <strong>{m.class}.{m.method}</strong>
                    <span className={'badge ' + (m.operation === 'write' ? 'badge-warning' : 'badge-success')} style={{ marginLeft: 6, fontSize: '0.7rem' }}>{m.operation}</span>
                    {m.entities.length > 0 && <span className="text-muted" style={{ marginLeft: 8 }}>Entities: {m.entities.join(', ')}</span>}
                  </div>
                  <div className="text-muted" style={{ fontSize: '0.75rem' }}>{m.file}:{m.lineNumber} → {m.returnType}</div>
                  {m.linqExpression && (
                    <details style={{ marginTop: 4 }}>
                      <summary style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: '0.75rem' }}>LINQ Expression</summary>
                      <pre style={{ fontSize: '0.72rem', background: 'var(--bg)', padding: '0.5rem', borderRadius: 4, marginTop: 4, whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto' }}>{m.linqExpression}</pre>
                    </details>
                  )}
                </div>
              ))}
            </div>
          </details>

          {roslynData.storedProcedures.length > 0 && (
            <details style={{ marginTop: '0.5rem' }}>
              <summary style={{ cursor: 'pointer', color: 'var(--primary)', fontSize: '0.85rem', fontWeight: 600 }}>
                Stored Procedures ({roslynData.storedProcedures.length})
              </summary>
              <ul style={{ fontSize: '0.8rem', paddingLeft: '1.25rem', marginTop: '0.5rem' }}>
                {roslynData.storedProcedures.map((sp, i) => (
                  <li key={i}><strong>{sp.name}</strong> — called from {sp.calledFrom}</li>
                ))}
              </ul>
            </details>
          )}

          <details style={{ marginTop: '0.5rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: '0.78rem' }}>View Raw JSON</summary>
            <pre style={{ fontSize: '0.72rem', background: 'var(--bg)', padding: '0.5rem', borderRadius: 4, marginTop: 4, maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(roslynData, null, 2)}
            </pre>
          </details>
        </div>
      )}

      {!done && !running && (
        <div className="card">
          <p className="text-muted">No previous extraction found for this project.</p>
          <div className="mt-2">
            <button className="btn btn-primary" onClick={handleExtract}>🔍 Run Extraction</button>
          </div>
        </div>
      )}

      {(running || logs.length > 0) && (
        <div className="card">
          {running && <div className="progress-bar mb-1"><div className="fill" style={{ width: '50%', transition: 'width 2s' }} /></div>}
          <div className="log-area">{logs.join('\n')}</div>
        </div>
      )}
    </div>
  );
}
