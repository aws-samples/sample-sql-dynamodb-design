# SQL to DynamoDB Design Mentor — Architecture

## High-Level Architecture

```mermaid
graph TB
    subgraph Frontend["Frontend"]
        UI["Wizard UI<br/>React + Vite<br/>localhost:5173"]
        API_CLIENT["Axios API Client"]
        SSE["SSE Event Listener"]
        UI --> API_CLIENT
        UI --> SSE
    end

    subgraph Backend["Backend"]
        ROUTES["FastAPI Routes<br/>127.0.0.1:8081"]
        RUNNER["Pipeline Runner<br/>Orchestrator"]
        DB_LAYER["SQLAlchemy<br/>Repositories"]
        ROUTES --> RUNNER
        ROUTES --> DB_LAYER
    end

    subgraph Storage["Storage"]
        SQLITE[("SQLite<br/>app.db")]
        FILES["Output Files<br/>md and json"]
    end

    subgraph AI["AI Pipeline"]
        BEDROCK["Amazon Bedrock<br/>Claude Sonnet 4<br/>Claude Opus 4.6"]
        MCP["AWS DynamoDB<br/>MCP Server"]
        TEMPLATES["RAG Templates<br/>Best Practices<br/>Format Templates"]
        EXT["Phase 1<br/>Extractor Agent<br/>Sonnet 4"]
        ARCH["Phase 2<br/>Architect Agent<br/>Opus 4.6"]
        VAL["Phase 3<br/>Validator Agent<br/>Opus 4.6"]
        MET["Phase 4<br/>Metrics Agent<br/>Sonnet 4"]
        EXT --> ARCH
        ARCH --> VAL
        VAL --> MET
        BEDROCK -.-> EXT
        BEDROCK -.-> ARCH
        BEDROCK -.-> VAL
        BEDROCK -.-> MET
        TEMPLATES -.-> EXT
        TEMPLATES -.-> ARCH
        TEMPLATES -.-> VAL
        TEMPLATES -.-> MET
        MCP -.-> TEMPLATES
    end

    subgraph Source["dotNET Source Project"]
        CS["C# Files<br/>Controllers<br/>Repositories<br/>Services<br/>Models"]
        ROSLYN["Roslyn Analyzer<br/>dotnet CLI tool"]
        CS --> ROSLYN
    end

    API_CLIENT -- HTTP --> ROUTES
    SSE -- SSE stream --> ROUTES
    DB_LAYER --> SQLITE
    RUNNER --> AI
    RUNNER --> FILES
    ROSLYN -- AST and LINQ --> EXT
    EXT -- Pattern scan fallback --> CS
    RUNNER -- Stores results --> DB_LAYER
```

## UI Wizard Flow

```mermaid
graph LR
    S1["Step 1<br/>Project Setup"]
    S2["Step 2<br/>Extract"]
    S3["Step 3<br/>Entity Selection"]
    S4["Step 4<br/>Access Patterns"]
    S5["Step 5<br/>Run Pipeline"]
    S6["Step 6<br/>Results"]

    S1 --> S2
    S2 --> S3
    S3 --> S4
    S4 --> S5
    S5 --> S6
    S5 -. View Results .-> S6
```

| Step | Page | What the user does |
|------|------|--------------------|
| 1 | Project Setup | 📂 Set name, .NET project path, AWS profile |
| 2 | Extract | 🔍 Scan the .NET codebase |
| 3 | Entity Selection | 🏗️ Toggle entities in scope for the migration |
| 4 | Access Patterns | 📊 Review and edit the extracted access patterns |
| 5 | Run Pipeline | 🚀 Execute the four-agent pipeline |
| 6 | Results | 📋 Interactive model view, validation, capacity |

## AI Pipeline Detail

```mermaid
graph TD
    subgraph Input
        DOTNET[".NET Project<br/>C# Source Files"]
        SCOPE["Migration Scope<br/>Selected Entities"]
        PATTERNS_DB["Access Patterns<br/>from DB"]
        OVERRIDES["Model Overrides<br/>User Customizations"]
    end

    subgraph Phase1["Phase 1: Extractor (Sonnet 4)"]
        E_IN["Scan Controllers,<br/>Repositories, Services<br/>(Roslyn + pattern scan)"]
        E_OUT["access_patterns.md<br/>entity_metrics.json"]
        E_IN --> E_OUT
    end

    subgraph Phase2["Phase 2: Architect (Opus 4.6)"]
        A_IN["Design Single-Table<br/>Model + GSIs"]
        A_OUT["dynamo_model.json<br/>dynamo_model.md"]
        A_IN --> A_OUT
    end

    subgraph Phase3["Phase 3: Validator (Opus 4.6)"]
        V_IN["Cross-check Patterns<br/>vs Model"]
        V_OUT["validation_report.md<br/>Expression Breakdown"]
        V_IN --> V_OUT
    end

    subgraph Phase4["Phase 4: Metrics (Sonnet 4)"]
        M_IN["Calculate RCU/WCU<br/>per Pattern and Entity"]
        M_OUT["capacity_analysis.md<br/>Updated dynamo_model.json"]
        M_IN --> M_OUT
    end

    subgraph Templates["RAG Knowledge Base"]
        BP["dynamodb_best_practices.md"]
        FMT["Per-Agent Format Templates"]
        MCP_KB["AWS DynamoDB MCP Server<br/>(merged guidance)"]
    end

    DOTNET --> E_IN
    SCOPE --> A_IN
    PATTERNS_DB --> A_IN
    OVERRIDES --> A_IN
    E_OUT --> A_IN
    A_OUT --> V_IN
    E_OUT --> V_IN
    A_OUT --> M_IN
    E_OUT --> M_IN
    V_OUT --> M_IN
    Templates -.->|Injected into prompts| Phase1
    Templates -.->|Injected into prompts| Phase2
    Templates -.->|Injected into prompts| Phase3
    Templates -.->|Injected into prompts| Phase4
```

## Backend Module Structure

```mermaid
graph TD
    subgraph API["api/"]
        MAIN["main.py<br/>FastAPI App"]
        R_PROJ["routes/projects.py"]
        R_ENT["routes/entities.py"]
        R_PAT["routes/patterns.py"]
        R_SCOPE["routes/scopes.py"]
        R_PIPE["routes/pipeline.py"]
        R_OVER["routes/overrides.py"]
        SCHEMAS["schemas.py"]
        MAIN --> R_PROJ
        MAIN --> R_ENT
        MAIN --> R_PAT
        MAIN --> R_SCOPE
        MAIN --> R_PIPE
        MAIN --> R_OVER
    end

    subgraph Services["services/"]
        RUNNER["pipeline_runner.py<br/>Agent Orchestration<br/>SSE Streaming"]
        CONSENSUS["consensus.py<br/>Multi-round consensus"]
        VALIDATION["validation_service.py<br/>Pattern validation"]
        MARKDOWN["markdown_writer.py<br/>Output formatting"]
        MCP_CLIENT["mcp_client.py<br/>DynamoDB MCP bridge"]
        RUNNER --> CONSENSUS
        RUNNER --> VALIDATION
        RUNNER --> MARKDOWN
        RUNNER --> MCP_CLIENT
    end

    subgraph DB["db/"]
        DATABASE["database.py<br/>SQLAlchemy Engine"]
        MODELS["models.py<br/>ORM Models"]
        REPO_PROJ["project_repo.py"]
        REPO_ENT["entity_repo.py"]
        REPO_PAT["pattern_repo.py"]
        REPO_PIPE["pipeline_repo.py"]
        REPO_SCOPE["scope_repo.py"]
        REPO_OVER["override_repo.py"]
    end

    R_PIPE --> RUNNER
    RUNNER --> REPO_PIPE
    R_PROJ --> REPO_PROJ
    R_ENT --> REPO_ENT
    R_PAT --> REPO_PAT
    R_SCOPE --> REPO_SCOPE
    R_OVER --> REPO_OVER
    REPO_PROJ --> DATABASE
    REPO_ENT --> DATABASE
    REPO_PAT --> DATABASE
    REPO_PIPE --> DATABASE
    REPO_SCOPE --> DATABASE
    REPO_OVER --> DATABASE
    DATABASE --> MODELS
```

## Data Flow: Pipeline Execution

```mermaid
sequenceDiagram
    participant User
    participant UI as React UI
    participant API as FastAPI
    participant Runner as Pipeline Runner
    participant Bedrock as Amazon Bedrock
    participant DB as SQLite
    participant FS as File System

    User->>UI: Click "Run Pipeline"
    UI->>API: POST /pipeline/run {phases}
    API->>DB: Create PipelineRun record
    API-->>UI: run_id

    UI->>API: GET /pipeline/run/{id}/stream (SSE)

    loop Each Phase (Model, Validate, Metrics)
        API->>Runner: Execute phase
        Runner->>FS: Read templates + input files
        Runner->>Bedrock: Send prompt with RAG context
        Bedrock-->>Runner: Agent response
        Runner->>FS: Write output files
        Runner->>DB: Store PipelineResult
        Runner-->>API: SSE event (progress, status)
        API-->>UI: SSE event
        UI->>User: Update progress bar + logs
    end

    Runner-->>API: SSE "completed"
    API-->>UI: SSE "completed"
    UI->>User: Show "View Results" button

    User->>UI: Click "View Results"
    UI->>API: GET /pipeline/run/{id}/results
    API->>DB: Fetch PipelineResults
    API-->>UI: JSON results
    UI->>User: Render interactive Results page
```

## Entry Points

The repository has two operational entry points:

- **React UI + FastAPI backend (primary)** — Frontend at `frontend/` served by Vite on `5173`, FastAPI backend at `backend/api/main.py` on `127.0.0.1:8081`. This is the supported six-step wizard described above.
- **Streamlit app (`app.py`, legacy)** — A single-process Streamlit alternative that reuses the same `pipeline.py` agents directly. Useful for quick local trials without running the full backend, but it does not use SQLite persistence, the SSE pipeline runner, or the per-project overrides supported by the React UI.
