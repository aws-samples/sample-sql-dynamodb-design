# SQL to DynamoDB Design Mentor

An AI-powered tool that analyzes .NET/C# data access patterns and designs an optimized DynamoDB single-table model. Uses [Strands Agents](https://github.com/strands-agents/strands-agents) with Amazon Bedrock to run a multi-phase pipeline: Extract → Model Design → Validation → Capacity Analysis.

React frontend + FastAPI backend + SQLite for project/run persistence.

---

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** and **npm**
- **.NET SDK 8.0+** (for the Roslyn semantic analyzer — optional but recommended)
- **AWS CLI** configured with a profile that has Bedrock model access
- **uv** (optional) — for the AWS DynamoDB MCP server integration. Install via `pip install uv`

### Required Bedrock Models

The pipeline uses two models. Enable them in your AWS Console under Bedrock → Model access:

| Model | Bedrock Model ID | Used By | Required? |
|-------|-----------------|---------|-----------|
| Claude Sonnet 4 | `us.anthropic.claude-sonnet-4-20250514-v1:0` | Extractor, Metrics Analyzer | Yes |
| Claude Opus 4.6 | `us.anthropic.claude-opus-4-6-v1` | Architect, Validator | Optional (falls back to Sonnet) |

The app validates model access on the Project Setup page before you can proceed.

---

## Setup & Run

### 1. Clone and set up Python

```bash
git clone <repo-url>
cd <repo>

python -m venv .venv
# Windows CMD: .venv\Scripts\activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate

pip install -r backend/requirements.txt
```

### 2. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 3. Build the Roslyn analyzer (optional but recommended)

The Roslyn analyzer uses the .NET Compiler Platform for accurate AST-based extraction of entities, relationships, and LINQ expressions. Without it, the pipeline falls back to pattern-based text scanning.

```bash
dotnet build tools/analyzer/SqlToDynamoDbDesignMentorAnalyzer.csproj -c Release
```

This only needs to be done once. The pipeline auto-detects whether the analyzer is built and uses it if available.

### 4. Configure AWS credentials

```bash
aws sso login --profile <your-profile>
```

### 5. Start the backend

From the repository root directory:

```bash
# Windows CMD
set PYTHONUTF8=1 && python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8081

# Windows PowerShell
$env:PYTHONUTF8="1"; python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8081

# macOS/Linux
PYTHONUTF8=1 python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8081
```

### 6. Start the frontend

In a separate terminal:

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## Project Structure

```
<repo-root>/
├── backend/                # FastAPI + SQLite backend
│   ├── api/                # Routes, schemas
│   ├── db/                 # SQLAlchemy models, repositories
│   └── services/           # Pipeline runner, MCP client
├── frontend/               # React + Vite + TypeScript
│   └── src/pages/          # UI pages (6-step wizard)
├── tools/
│   └── analyzer/           # Roslyn semantic analyzer (.NET CLI tool)
├── templates/              # Curated knowledge base & per-agent format templates
├── pipeline.py             # Agent definitions, tools, CLI entry point
├── sample-dotnet-project/  # Sample .NET project for testing
└── docs/                   # RAI narrative, presentation guide, scalability analysis
```

---

## How It Works

### Pipeline Phases

| Phase | Agent | Model | What It Does |
|-------|-------|-------|-------------|
| Extract | Extractor | Sonnet | Scans .NET code using Roslyn (AST) + pattern matching. Produces `access_patterns.md` and `entity_metrics.json` |
| Model | Architect | Opus | Designs DynamoDB single-table model with GSIs, C# queries, capacity analysis. Produces `dynamo_model.md` and `dynamo_model.json` |
| Validate | Validator | Opus | Cross-checks every access pattern against the model for expression correctness and coverage |
| Metrics | Metrics Analyzer | Sonnet | Calculates RCU/WCU per pattern, compares modeling strategies, produces `capacity_analysis.md` |

### Knowledge Sources

- **AWS DynamoDB MCP Server** — Centrally maintained DynamoDB best practices (fetched at pipeline start via `uv`)
- **Local templates** — Tool-specific rules for output format, entity modeling, capacity scoping
- **Merged knowledge base** — Both sources combined into a single file with clear priority (local rules override MCP if they conflict)

### Extraction Pipeline

The Extractor uses two complementary approaches:
1. **Roslyn analyzer** (if built) — AST-based semantic analysis: entities, fields, relationships, LINQ expressions, method signatures
2. **Pattern-based scanner** — Text matching for code context, comments, and patterns Roslyn might miss

Both outputs are combined and sent to the LLM for classification and naming. A coverage report verifies completeness by comparing extracted entities against DbContext declarations.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `'charmap' codec can't decode byte` | Set `PYTHONUTF8=1` before starting the backend |
| `Unable to locate credentials` | Run `aws sso login --profile <profile>` |
| Bedrock model access denied | Enable the model in AWS Console → Bedrock → Model access |
| Backend port 8080 blocked | The app uses port **8081** by default |
| Frontend can't reach backend | Vite proxy targets `http://127.0.0.1:8081` (not `localhost`) |
| DB schema changed | Delete `app.db` and restart the backend |
| Roslyn analyzer not found | Run `dotnet build tools/analyzer/SqlToDynamoDbDesignMentorAnalyzer.csproj -c Release` |
| MCP server unavailable | Install `uv` via `pip install uv`. Pipeline falls back to local templates if MCP fails |

---

## Tech Stack

- **Frontend:** React 18, TypeScript, Vite, Axios
- **Backend:** FastAPI, SQLAlchemy, SQLite, SSE (Server-Sent Events)
- **AI:** Amazon Bedrock (Claude Opus 4.6 + Claude Sonnet 4), Strands Agents SDK
- **Knowledge:** AWS DynamoDB MCP Server, curated knowledge base templates
- **Code Analysis:** Roslyn (.NET Compiler Platform) for semantic extraction
- **MCP:** AWS DynamoDB MCP Server for centrally maintained best practices

---

## Responsible AI

This tool was built with Responsible AI principles embedded across its architecture. Below are the six RAI dimensions addressed and how each is implemented.

### 1. Transparency — Making AI Decisions Visible

- **AI-generated disclaimers** on every output section and exported report — making it clear that results require expert review before implementation.
- **Full arithmetic transparency** for capacity calculations — every step of the RCU/WCU math is shown in the output (e.g., "3 KB / 4 = 0.75 → 0.5 RCU") so users can verify correctness.
- **Expression breakdown** for every access pattern — labels showing what runs as a KeyCondition (efficient), FilterExpression, or Client-Side processing are included in the model output.
- **Design priority traceability** — every modeling decision references the user's chosen priority (cost / balanced / performance) selected on the Project Setup page, and the pipeline injects corresponding rules into agent prompts.
- **Real-time log streaming** — the UI streams agent execution logs via SSE so users can observe exactly what the AI is doing during each pipeline phase.

### 2. Accuracy — Grounding AI Output in Verified Knowledge

- **Curated knowledge base** containing verified DynamoDB best practices, expression rules, and capacity formulas — injected directly into every agent prompt. AWS DynamoDB MCP Server provides centrally maintained guidance, merged with local template rules at pipeline start.
- **Per-agent format templates** enforce structured output — each agent must produce specific fields with specific formulas, reducing hallucination surface area.
- **Dedicated Validator Agent** independently cross-checks every access pattern against the generated model — acting as an AI-powered peer reviewer that catches errors from the Architect Agent (Phase 3 of the pipeline).
- **Multi-run consensus extraction** with confidence scoring — 3 parallel LLM runs per round (up to 3 rounds). Entities and patterns must appear in ≥2 runs to be included. Confidence score displayed on the Extract page.
- **Roslyn AST baseline alignment** — when the .NET Compiler Platform analyzer is available, LLM-extracted entities are constrained to only those confirmed by static analysis. LLM-only entities (hallucinated ViewModels, DTOs, etc.) are automatically rejected.
- **Automated output validation** — model JSON is checked for required structure (tableName, primaryKey, entityMappings, accessPatternMapping) before results are presented.
- **Deterministic post-processing** overrides LLM outputs when they violate invariants (e.g., patterns requiring external services cannot be classified as "easy" complexity; scan-based patterns are auto-upgraded to "hard").

### 3. Human Oversight — Keeping Engineers in Control

- **Human-in-the-loop workflow** — the 6-step wizard ensures users review and approve at every stage. On the Entity Selection page (Step 3), users choose which entities to migrate. On the Access Patterns page (Step 4), users adjust request rates, add/remove patterns, and reclassify them before the pipeline runs.
- **Model Override controls** — users can explicitly override AI design decisions (e.g., force separate tables, flatten entities, custom GSI, custom key) via the overrides panel. These are injected into agent prompts with "MUST follow" priority.
- **Migration scope controls** — users can choose full, microservice, or hybrid migration mode. Patterns are automatically classified as in-scope, cross-boundary, or excluded, with cross-boundary dependencies explicitly flagged.
- **Pipeline execution history** — the Run Pipeline page shows all previous runs with status, timestamps, and "View Results" buttons so users can compare outputs across runs.
- **Restart with modifications** — users can modify inputs (entities, patterns, scope, overrides) and re-run the pipeline with adjusted parameters at any point if outputs are not meeting expectations.
- **No autonomous action** — the tool never provisions infrastructure or modifies databases. It produces design documents and recommendations only. The human always makes the final call.

### 4. Explainability — Showing Why, Not Just What

- **Key design justification** for every entity — the model output documents why each partition key and sort key was chosen, which access patterns drove the decision, and what alternatives were considered.
- **Complexity ratings with rationale** — each access pattern in the generated model gets an Easy/Medium/Hard rating with a specific explanation (e.g., "Pattern requires full-text substring matching — best served by a full-text search engine. begins_with() supports prefix matching; contains() in FilterExpression scans the full partition.").
- **Confidence scores (0–100%)** displayed on the Extract page after consensus extraction — computed as a weighted formula: 40% entity agreement + 30% pattern agreement + 30% Roslyn alignment. Low confidence triggers additional extraction rounds automatically.
- **Design priority influence** — the Results page shows which modeling rules were applied based on the user's cost/balanced/performance choice, making recommendations traceable to user intent.

### 5. Privacy & Security — Protecting Source Code

- **Local-first processing** — source code is scanned entirely on the user's machine using Roslyn AST analysis and pattern matching. Only extracted patterns and metadata (not raw source files) are sent to Amazon Bedrock.
- **User-controlled AWS credentials** — the tool uses the engineer's own AWS profile (SSO/IAM) selected on the Project Setup page. No credentials are stored by the application.
- **All data stays local** — the SQLite database, output files, and pipeline results are stored on the user's machine. No data is sent to external services beyond Bedrock API calls.
- **Source code is never modified** — the pipeline only reads from the provided project path for analysis. All agent-generated output is written to a separate `output/` directory.
- **Scoped file access** — the file browser endpoint restricts navigation to allowed directory roots and rejects path traversal sequences (`..`, `~`, null bytes).
- **Log filename sanitization** — pipeline log filenames are validated via regex before serving to prevent directory traversal attacks.

### 6. Safety & Robustness — Handling Failures Gracefully

- **Multi-stage JSON repair** — handles malformed LLM output gracefully (extra data truncation, missing comma insertion, broken string replacement, trailing comma removal) instead of failing silently or showing broken results.
- **Graceful degradation** — Roslyn unavailable → falls back to pattern-based scanning. MCP server unavailable → falls back to local templates. Opus unavailable → falls back to Sonnet. The pipeline continues regardless of component availability.
- **Clear error messaging** — when something fails, the SSE stream and UI show what went wrong and what to do about it. The Troubleshooting section documents common issues and fixes.
- **Pipeline run persistence** — if a run fails partway through, partial results are preserved in the database. Users can view what completed and re-run.
- **Encoding safety** — UTF-8 is enforced across all file I/O at application startup to prevent data corruption on Windows systems.
- **Fresh AWS sessions** per pipeline run to avoid stale credential errors from expired SSO tokens.

### Key Safeguards

- **The tool never executes migrations** — it produces design documents and recommendations only. The human always makes the final call.
- **Deterministic guardrails override LLM outputs** — post-processing rules correct complexity classifications and enforce DynamoDB expression rules regardless of what the model generates.
- **Confidence gating** — extraction results include a confidence score. Low-confidence extractions trigger additional consensus rounds automatically.
- **Roslyn constrains the LLM** — when the .NET Compiler Platform baseline is available, the LLM cannot introduce entities not confirmed by static analysis.
- **Model overrides take precedence** — user-specified design constraints are injected with explicit "MUST follow" priority, ensuring domain expertise overrides AI suggestions.
