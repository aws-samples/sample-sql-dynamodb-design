import { useState, useEffect } from 'react';
import { pipelineApi, PipelineRun } from '../api/client';

interface Props { projectId: number; onViewResults: (runId: number) => void; }

interface PhaseEvent {
  phase?: number;
  name?: string;
  status: string;
  progress?: number;
  message?: string;
  error?: string;
  log_file?: string;
}

export default function RunPipeline({ projectId, onViewResults }: Props) {
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState<string[]>([]);
  const [done, setDone] = useState(false);
  const [checking, setChecking] = useState(true);
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [latestRunId, setLatestRunId] = useState<number | null>(null);
  const [logFile, setLogFile] = useState<string | null>(null);
  const [logFiles, setLogFiles] = useState<Record<number, string>>({});

  const loadRuns = async () => {
    try {
      const { data } = await pipelineApi.listRuns(projectId);
      // Show all runs that include model phase (not extract-only)
      const pipelineRuns = data.filter(
        (r) => r.phases_config?.model
      );
      setRuns(pipelineRuns);

      // Load available log files and match to run IDs
      try {
        const logsRes = await pipelineApi.listLogs(projectId);
        const mapping: Record<number, string> = {};
        for (const log of logsRes.data.logs) {
          // Log filenames are like run_5_20260415_112615.log
          const match = log.filename.match(/^run_(\d+)_/);
          if (match) {
            const runId = parseInt(match[1], 10);
            // Keep the most recent log per run (list is sorted desc)
            if (!mapping[runId]) mapping[runId] = log.filename;
          }
        }
        setLogFiles(mapping);
      } catch { /* log listing not critical */ }

      return pipelineRuns;
    } catch { return []; }
  };

  useEffect(() => {
    loadRuns().then((pipelineRuns) => {
      setChecking(false);
    });
  }, [projectId]);

  const addLog = (msg: string) => setLogs((prev) => [...prev, msg]);

  const handleRun = async () => {
    setRunning(true);
    setDone(false);
    setLogs([]);
    setProgress(0);
    setLatestRunId(null);
    setLogFile(null);

    try {
      const phases = { extract: false, model: true, validate_phase: true, metrics: true };
      const { data: run } = await pipelineApi.createRun(projectId, phases);
      addLog(`Pipeline run #${run.id} started...`);

      const url = pipelineApi.streamUrl(projectId, run.id);
      const eventSource = new EventSource(url);

      eventSource.onmessage = (event) => {
        const data: PhaseEvent = JSON.parse(event.data);
        if (data.error) {
          addLog(`❌ Error: ${data.error}`);
          setRunning(false);
          eventSource.close();
          loadRuns();
          return;
        }
        if (data.progress) setProgress(data.progress);
        if (data.message) addLog(data.message);
        if (data.status === 'complete' && data.name) {
          addLog(`  ✓ Phase ${data.phase} (${data.name}) complete`);
        }
        if (data.status === 'completed') {
          addLog('✅ Pipeline complete!');
          if (data.log_file) setLogFile(data.log_file);
          setRunning(false);
          setDone(true);
          setLatestRunId(run.id);
          loadRuns();
          eventSource.close();
        }
      };

      eventSource.onerror = () => {
        addLog('Connection lost.');
        setRunning(false);
        eventSource.close();
        loadRuns();
      };
    } catch (e: any) {
      addLog(`❌ Failed to start: ${e.message}`);
      setRunning(false);
    }
  };

  const statusBadge = (status: string) => {
    const cls = status === 'completed' ? 'badge-success' : status === 'failed' ? 'badge-danger' : 'badge-warning';
    return <span className={'badge ' + cls}>{status}</span>;
  };

  if (checking) return <div className="card">Loading pipeline history...</div>;

  return (
    <div>
      <h2>🚀 Run Pipeline</h2>

      {/* Phase descriptions */}
      {!running && (
        <div className="card guidance-card" style={{ marginBottom: '1rem' }}>
          <p style={{ fontSize: '0.85rem', lineHeight: 1.7, marginBottom: 8 }}>
            The pipeline executes 3 phases using AI agents powered by Amazon Bedrock:
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.75rem' }}>
            <div><strong style={{ fontSize: '0.82rem' }}>🏗️ Model Design</strong><p className="text-muted" style={{ marginTop: 2 }}>DynamoDB single-table model with GSIs, C# queries, capacity analysis</p></div>
            <div><strong style={{ fontSize: '0.82rem' }}>✅ Validation</strong><p className="text-muted" style={{ marginTop: 2 }}>Cross-checks every access pattern for coverage and expression correctness</p></div>
            <div><strong style={{ fontSize: '0.82rem' }}>📊 Capacity</strong><p className="text-muted" style={{ marginTop: 2 }}>RCU/WCU estimation per pattern and entity comparison analysis</p></div>
          </div>
        </div>
      )}

      {/* Run button */}
      {!running && !done && (
        <div className="card" style={{ textAlign: 'center', padding: '1.25rem' }}>
          <p style={{ marginBottom: '0.75rem', fontSize: '0.9rem' }}>
            {runs.length > 0
              ? 'Run a new pipeline execution, or view results from a previous run below.'
              : 'Ready to proceed? You can always go back to previous steps to make changes before running.'}
          </p>
          <button className="btn btn-primary" onClick={handleRun}>
            {runs.length > 0 ? '🔄 Run New Pipeline' : '✅ Yes, Proceed with Execution'}
          </button>
        </div>
      )}

      {/* Progress */}
      {(running || logs.length > 0) && (
        <div className="card">
          <div className="progress-bar mb-1">
            <div className="fill" style={{ width: `${progress * 100}%` }} />
          </div>
          <div className="log-area">{logs.join('\n')}</div>
          {logFile && !running && (
            <div style={{ marginTop: '0.5rem', textAlign: 'right' }}>
              <a
                href={pipelineApi.downloadLogUrl(projectId, logFile)}
                download={logFile}
                className="btn btn-secondary"
                style={{ fontSize: '0.78rem', padding: '0.3rem 0.6rem' }}
              >
                📥 Download Debug Logs
              </a>
            </div>
          )}
        </div>
      )}

      {done && latestRunId && (
        <div className="mt-2" style={{ textAlign: 'center' }}>
          <button className="btn btn-primary" onClick={() => onViewResults(latestRunId)}>📋 View Results →</button>
        </div>
      )}

      {/* Pipeline Runs History */}
      {runs.length > 0 && !running && (
        <div className="card" style={{ marginTop: '1rem' }}>
          <strong>Pipeline Execution History ({runs.length})</strong>
          <table className="data-table" style={{ marginTop: '0.75rem', fontSize: '0.82rem' }}>
            <thead>
              <tr><th>Run</th><th>Status</th><th>Phases</th><th>Started</th><th>Completed</th><th>Error</th><th></th><th></th></tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const phases = run.phases_config || {};
                const phaseList = Object.entries(phases).filter(([, v]) => v).map(([k]) => k).join(', ');
                const canView = run.status === 'completed';
                const runLogFile = logFiles[run.id];
                return (
                  <tr key={run.id}>
                    <td><strong>#{run.id}</strong></td>
                    <td>{statusBadge(run.status)}</td>
                    <td className="text-muted">{phaseList}</td>
                    <td className="text-muted">{run.started_at ? new Date(run.started_at).toLocaleString() : '—'}</td>
                    <td className="text-muted">{run.completed_at ? new Date(run.completed_at).toLocaleString() : '—'}</td>
                    <td className="text-muted" style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{run.error_message || '—'}</td>
                    <td>
                      {canView && (
                        <button className="btn btn-primary" style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem' }} onClick={() => onViewResults(run.id)}>
                          📋 View Results
                        </button>
                      )}
                    </td>
                    <td>
                      {runLogFile && (
                        <a
                          href={pipelineApi.downloadLogUrl(projectId, runLogFile)}
                          download={runLogFile}
                          className="btn btn-secondary"
                          style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem' }}
                        >
                          📥 Logs
                        </a>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
