import { useState, useEffect } from 'react';
import ProjectSetup from './pages/ProjectSetup';
import RunExtract from './pages/RunExtract';
import EntitySelection from './pages/EntitySelection';
import AccessPatterns from './pages/AccessPatterns';
import RunPipeline from './pages/RunPipeline';
import Results from './pages/Results';
import { logApi } from './api/client';

const steps = [
  { num: 1, icon: '📂', label: 'Project Setup' },
  { num: 2, icon: '🔍', label: 'Extract' },
  { num: 3, icon: '🏗️', label: 'Entity Selection' },
  { num: 4, icon: '📊', label: 'Access Patterns' },
  { num: 5, icon: '🚀', label: 'Run Pipeline' },
  { num: 6, icon: '📋', label: 'Results' },
];

export default function App() {
  const [currentStep, setCurrentStep] = useState(1);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [logLevel, setLogLevel] = useState<string>('warning');

  useEffect(() => {
    logApi.getLevel().then(res => setLogLevel(res.data.level)).catch(() => {});
  }, []);

  const cycleLogLevel = () => {
    const next = logLevel === 'warning' ? 'info' : logLevel === 'info' ? 'debug' : 'warning';
    logApi.setLevel(next).then(res => setLogLevel(res.data.level)).catch(() => {});
  };

  const goNext = () => setCurrentStep((s) => Math.min(s + 1, 6));

  const handleViewResults = (runId: number) => {
    setSelectedRunId(runId);
    setCurrentStep(6);
  };

  return (
    <div className="app">
      <nav className="sidebar">
        <h1>🔄 SQL to DynamoDB Design Mentor</h1>
        <p className="subtitle">SQL Server → DynamoDB</p>
        {steps.map((s) => (
          <button
            key={s.num}
            className={`nav-item ${currentStep === s.num ? 'active' : ''}`}
            onClick={() => setCurrentStep(s.num)}
          >
            {s.icon} {s.label}
          </button>
        ))}
        <div style={{ marginTop: 'auto', padding: '0.75rem 0', borderTop: '1px solid var(--border)' }}>
          <button
            className="nav-item"
            onClick={cycleLogLevel}
            title={`Agent log level: ${logLevel}. Click to cycle: warning → info → debug → warning`}
            style={{ fontSize: '0.78rem', opacity: 0.8 }}
          >
            {logLevel === 'debug' ? '🔍' : logLevel === 'info' ? 'ℹ️' : '⚠️'} Logs: {logLevel}
          </button>
        </div>
      </nav>
      <main className="main">
        {currentStep === 1 && <ProjectSetup projectId={projectId} setProjectId={setProjectId} onNext={goNext} />}
        {currentStep === 2 && projectId && <RunExtract projectId={projectId} onNext={goNext} />}
        {currentStep === 3 && projectId && <EntitySelection projectId={projectId} onNext={goNext} />}
        {currentStep === 4 && projectId && <AccessPatterns projectId={projectId} onNext={goNext} />}
        {currentStep === 5 && projectId && <RunPipeline projectId={projectId} onViewResults={handleViewResults} />}
        {currentStep === 6 && projectId && <Results projectId={projectId} runId={selectedRunId} />}
        {!projectId && currentStep > 1 && (
          <div className="card"><p>Please set up a project first (Step 1).</p></div>
        )}
      </main>
    </div>
  );
}
