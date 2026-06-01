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
├── templates/              # RAG knowledge base & per-agent format templates
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
- **Knowledge:** AWS DynamoDB MCP Server, RAG templates
- **Code Analysis:** Roslyn (.NET Compiler Platform) for semantic extraction
- **MCP:** AWS DynamoDB MCP Server for centrally maintained best practices
