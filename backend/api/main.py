from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import os
import sys

# Force UTF-8 on Windows — must be before any file I/O
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.platform == "win32" and "pytest" not in sys.modules:
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, Exception):
        pass

# Configure logging — DEBUG level for SQL to DynamoDB Design Mentor backend, WARNING for noisy libs
# Set STRANDS_DEBUG=1 to see full agent LLM calls, tool invocations, and prompts
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Quiet down noisy third-party loggers
_strands_level = logging.DEBUG if os.environ.get("STRANDS_DEBUG") == "1" else logging.WARNING
for _noisy in ("uvicorn", "uvicorn.access", "httpcore", "httpx", "botocore", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logging.getLogger("strands").setLevel(_strands_level)
if _strands_level == logging.DEBUG:
    logging.getLogger("root").info("🔍 STRANDS_DEBUG=1 — agent LLM calls, tool invocations, and prompts will be logged")

from backend.db.database import init_db
from backend.api.routes import projects, entities, patterns, scopes, pipeline, overrides


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="SQL to DynamoDB Design Mentor API",
    description="SQL Server to DynamoDB migration tool",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api")
app.include_router(entities.router, prefix="/api")
app.include_router(patterns.router, prefix="/api")
app.include_router(scopes.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api")
app.include_router(overrides.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/log-level")
def get_log_level():
    """Get current log level for strands agent logging."""
    current = logging.getLogger("strands").level
    return {"level": "debug" if current <= logging.DEBUG else "info" if current <= logging.INFO else "warning"}


@app.post("/api/log-level")
def set_log_level(level: str = "warning"):
    """Toggle log level for strands agent logging. Levels: debug, info, warning."""
    level_map = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING}
    log_level = level_map.get(level.lower(), logging.WARNING)
    logging.getLogger("strands").setLevel(log_level)
    actual = "debug" if log_level <= logging.DEBUG else "info" if log_level <= logging.INFO else "warning"
    logging.getLogger("backend").info(f"Strands log level set to {actual}")
    return {"level": actual}
