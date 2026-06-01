from strands import Agent, tool
from strands.models import BedrockModel
import os
import io
import sys

# Force UTF-8 for all file I/O on Windows (prevents charmap codec errors)
# Skip if running under pytest (conflicts with output capture)
if sys.platform == "win32" and "pytest" not in sys.modules:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # Already wrapped or no buffer available

# Pipeline output directory — all generated files go here
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# --- Tools ---

@tool
def read_file(file_path: str) -> str:
    """Read contents of a file"""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a file (overwrites existing content)"""
    with open(file_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(content)
    return f"Written to {file_path}"


@tool
def append_file(file_path: str, content: str) -> str:
    """Append content to an existing file. Use this to write large outputs in chunks."""
    with open(file_path, "a", encoding="utf-8", errors="replace") as f:
        f.write(content)
    return f"Appended to {file_path}"


@tool
def scan_dotnet_project(project_path: str) -> str:
    """Scan a .NET project and return data access code organized by file.
    Uses parallel file reading, extracts only relevant methods (not full classes),
    and returns results in batches. DbContext/Model files are sent in full for schema context."""
    import re as _re
    from concurrent.futures import ThreadPoolExecutor, as_completed

    name_patterns = [
        "Repository", "Repo", "DbContext", "Context", "Controller",
        "Service", "DataAccess", "Dal", "Query", "Handler", "UnitOfWork"
    ]
    content_markers = [
        "DbSet<", "FromSqlRaw", "FromSqlInterpolated", "ExecuteSqlRaw",
        ".Where(", ".Select(", ".Include(", ".ThenInclude(", ".Join(",
        ".GroupBy(", ".OrderBy(", ".OrderByDescending(", ".FirstOrDefault(",
        ".SingleOrDefault(", ".ToListAsync(", ".CountAsync(", ".SumAsync(",
        "IQueryable", "SqlCommand", "SqlConnection", "Dapper", ".Query<",
        ".Execute(", "IRepository", "UnitOfWork", "SaveChangesAsync",
        "HasOne", "HasMany", "WithMany", "WithOne", "HasForeignKey",
        "modelBuilder", "OnModelCreating"
    ]
    # Files/directories that should be sent in full (schema context)
    full_file_patterns = ["DbContext", "Context"]
    full_dir_patterns = ["Models", "Model", "Data", "Entities"]
    skip_dirs = {"bin", "obj", "node_modules", ".git", "Migrations", "TestResults", ".vs"}

    # Step 1: Collect all .cs file paths
    cs_files = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if f.endswith(".cs"):
                cs_files.append(os.path.join(root, f))

    # Step 2: Read files in parallel (8 threads)
    file_contents = {}
    def _read_file(path):
        try:
            with open(path, "r", errors="ignore") as fh:
                return path, fh.read()
        except Exception:
            return path, None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_read_file, p): p for p in cs_files}
        for future in as_completed(futures):
            path, content = future.result()
            if content:
                file_contents[path] = content

    # Step 3: Filter to relevant files and extract methods
    def _is_full_file(filepath):
        """Check if this file should be sent in full (schema/model/entity files)."""
        filename = os.path.basename(filepath)
        name_lower = filename.lower()
        if any(p.lower() in name_lower for p in full_file_patterns):
            return True
        # Check if file is in a Models/Data/Entities directory
        dir_name = os.path.basename(os.path.dirname(filepath))
        if any(p.lower() == dir_name.lower() for p in full_dir_patterns):
            return True
        return False

    def _extract_methods(content, markers):
        """Extract only methods containing data access markers, plus class/namespace header."""
        lines = content.split('\n')
        # Extract namespace, using, and class declarations for context
        header_lines = []
        for line in lines:
            stripped = line.strip()
            if (stripped.startswith('using ') or stripped.startswith('namespace ') or
                stripped.startswith('public class ') or stripped.startswith('public abstract class ') or
                stripped.startswith('public static class ') or stripped.startswith('[') or
                stripped.startswith('public record ') or stripped.startswith('public enum ')):
                header_lines.append(line)
            elif stripped.startswith('{') and header_lines and 'class ' in header_lines[-1]:
                header_lines.append(line)

        # Find method boundaries using brace counting
        methods = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            # Detect method signatures: public/private/protected/internal async? Task/void/type MethodName(
            if _re.match(r'\s*(public|private|protected|internal)\s+', stripped) and '(' in stripped and ')' in stripped:
                # Skip if it's a class/interface/enum/property declaration
                if any(kw in stripped for kw in ['class ', 'interface ', 'enum ', 'struct ', '=>', '{ get;', '{ set;']):
                    # One-liner property or expression-bodied member
                    if '=>' in stripped:
                        method_block = [line]
                        # Check if it spans multiple lines
                        j = i + 1
                        if not stripped.endswith(';'):
                            while j < len(lines) and not lines[j].strip().endswith(';'):
                                method_block.append(lines[j])
                                j += 1
                            if j < len(lines):
                                method_block.append(lines[j])
                                j += 1
                        method_text = '\n'.join(method_block)
                        if any(m in method_text for m in markers):
                            methods.append(method_text)
                        i = j
                        continue
                    i += 1
                    continue

                # Collect the full method body by tracking braces
                method_lines = [line]
                brace_count = line.count('{') - line.count('}')
                j = i + 1
                # If no opening brace on signature line, look for it
                if brace_count == 0:
                    while j < len(lines):
                        method_lines.append(lines[j])
                        brace_count += lines[j].count('{') - lines[j].count('}')
                        j += 1
                        if brace_count > 0:
                            break
                    if brace_count == 0:
                        i = j
                        continue
                # Now track until braces balance
                while j < len(lines) and brace_count > 0:
                    method_lines.append(lines[j])
                    brace_count += lines[j].count('{') - lines[j].count('}')
                    j += 1

                method_text = '\n'.join(method_lines)
                # Only include if method contains data access markers
                if any(m in method_text for m in markers):
                    methods.append(method_text)
                i = j
            else:
                i += 1

        if not methods:
            return None

        header = '\n'.join(header_lines)
        body = '\n\n'.join(methods)
        return f"{header}\n\n// --- Extracted methods with data access patterns ---\n\n{body}"

    results = []
    for path, content in file_contents.items():
        filename = os.path.basename(path)
        name_match = any(p.lower() in filename.lower() for p in name_patterns)
        content_match = any(m in content for m in content_markers)
        is_full = _is_full_file(path)

        if not (name_match or content_match or is_full):
            continue

        if is_full:
            # Send full file for schema context
            results.append({"file": path, "content": content, "type": "full"})
        else:
            # Extract only relevant methods
            extracted = _extract_methods(content, content_markers)
            if extracted:
                results.append({"file": path, "content": extracted, "type": "methods"})
            elif name_match or is_full:
                # File matched by name but no methods extracted — send full as fallback
                results.append({"file": path, "content": content, "type": "full"})

    # Step 4: Build output in batches (schema files first, then by size)
    schema_files = [r for r in results if r["type"] == "full"]
    method_files = [r for r in results if r["type"] == "methods"]

    total_files = len(results)
    total_methods = sum(r["content"].count("// --- Extracted methods") for r in method_files)
    summary = f"Found {total_files} data access files ({len(schema_files)} schema/model, {len(method_files)} with extracted methods):\n\n"

    # Schema files first (DbContext, Models) — full content
    if schema_files:
        summary += "=== SCHEMA & MODEL FILES (full content for entity relationships) ===\n\n"
        for r in schema_files:
            summary += f"--- {r['file']} ---\n{r['content']}\n\n"

    # Then method-extracted files
    if method_files:
        summary += "=== DATA ACCESS FILES (relevant methods only) ===\n\n"
        for r in method_files:
            summary += f"--- {r['file']} [methods extracted] ---\n{r['content']}\n\n"

    return summary


@tool
def run_roslyn_analysis(project_path: str) -> str:
    """Run the Roslyn semantic analyzer on a .NET project.
    Returns structured JSON with entities, relationships, access methods, and LINQ expressions
    extracted using the .NET Compiler Platform (AST + type resolution).
    This is more accurate than pattern-based scanning for entity detection and method extraction."""
    import subprocess

    analyzer_path = os.path.join(os.path.dirname(__file__), "tools", "analyzer", "SqlToDynamoDbDesignMentorAnalyzer.csproj")
    output_path = os.path.join(os.path.dirname(__file__), OUTPUT_DIR, "roslyn_analysis.json")

    if not os.path.exists(analyzer_path):
        return "Roslyn analyzer not found. Falling back to pattern-based scanning."

    try:
        result = subprocess.run(
            ["dotnet", "run", "--project", analyzer_path, "-c", "Release", "--", project_path, "--output", output_path],
            capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace"
        )

        if os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8", errors="replace") as f:
                analysis = json.load(f)

            # Build a human-readable summary for the LLM
            summary = f"=== ROSLYN SEMANTIC ANALYSIS (AST-based, high accuracy) ===\n\n"
            summary += f"Project: {project_path}\n"
            summary += f"Files analyzed: {analysis.get('filesAnalyzed', 0)} / {analysis.get('totalCsFiles', 0)}\n"
            summary += f"EF Core: {analysis.get('efCoreDetected', False)}, Dapper: {analysis.get('dapperDetected', False)}, Raw SQL: {analysis.get('rawSqlDetected', False)}\n\n"

            # Entities
            entities = analysis.get("entities", [])
            summary += f"## Entities Found ({len(entities)})\n\n"
            for ent in entities:
                table = ent.get("table", "unknown")
                fields = ent.get("fields", [])
                rels = ent.get("relationships", [])
                summary += f"### {ent['name']} (table: {table})\n"
                if fields:
                    summary += f"Fields: {', '.join(f['name'] + ':' + f['type'] for f in fields)}\n"
                if rels:
                    for r in rels:
                        summary += f"  Relationship: {r['type']} → {r['target']}"
                        if r.get("navigationProperty"):
                            summary += f" (nav: {r['navigationProperty']})"
                        summary += "\n"
                summary += "\n"

            # Access methods
            methods = analysis.get("accessMethods", [])
            summary += f"## Access Methods Found ({len(methods)})\n\n"
            for m in methods:
                summary += f"### {m['class']}.{m['method']} [{m['operation'].upper()}]\n"
                summary += f"File: {m['file']}:{m['lineNumber']}\n"
                summary += f"Returns: {m['returnType']}\n"
                if m.get("parameters"):
                    summary += f"Params: {', '.join(p['name'] + ':' + p['type'] for p in m['parameters'])}\n"
                if m.get("entities"):
                    summary += f"Entities: {', '.join(m['entities'])}\n"
                if m.get("linqExpression"):
                    summary += f"LINQ:\n```csharp\n{m['linqExpression']}\n```\n"
                summary += "\n"

            # Stored procedures
            sps = analysis.get("storedProcedures", [])
            if sps:
                summary += f"## Stored Procedures ({len(sps)})\n\n"
                for sp in sps:
                    summary += f"- {sp['name']} (called from {sp['calledFrom']} in {sp['file']})\n"

            return summary
        else:
            return f"Roslyn analysis failed. stderr: {result.stderr[:500] if result.stderr else 'no output'}"

    except subprocess.TimeoutExpired:
        return "Roslyn analysis timed out (>5 min). Falling back to pattern-based scanning."
    except Exception as e:
        return f"Roslyn analysis error: {str(e)}. Falling back to pattern-based scanning."


def generate_extraction_coverage_report(project_path: str) -> dict:
    """Pre-scan the .NET codebase to build a deterministic inventory of entities,
    repositories, and data access methods. This runs BEFORE the LLM extraction
    and provides a baseline to verify completeness afterward."""
    import re as _re
    from concurrent.futures import ThreadPoolExecutor, as_completed

    skip_dirs = {"bin", "obj", "node_modules", ".git", "Migrations", "TestResults", ".vs"}

    # Collect all .cs files
    cs_files = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if f.endswith(".cs"):
                cs_files.append(os.path.join(root, f))

    # Read all files in parallel
    file_contents = {}
    def _read(path):
        try:
            with open(path, "r", errors="ignore") as fh:
                return path, fh.read()
        except Exception:
            return path, None

    with ThreadPoolExecutor(max_workers=8) as executor:
        for future in as_completed({executor.submit(_read, p): p for p in cs_files}):
            path, content = future.result()
            if content:
                file_contents[path] = content

    report = {
        "project_path": project_path,
        "total_cs_files": len(cs_files),
        "total_cs_files_with_content": len(file_contents),
        "dbcontext_entities": [],
        "model_classes": [],
        "repository_classes": [],
        "service_classes": [],
        "controller_classes": [],
        "data_access_methods": [],
        "stored_procedure_refs": [],
        "dapper_usage": False,
        "ef_core_usage": False,
        "raw_sql_usage": False,
        "files_scanned": [],
        "files_skipped": [],
    }

    for path, content in file_contents.items():
        filename = os.path.basename(path)
        rel_path = os.path.relpath(path, project_path)

        # Detect DbContext and extract DbSet entities
        if "DbContext" in content or "OnModelCreating" in content:
            report["ef_core_usage"] = True
            for m in _re.finditer(r'DbSet<(\w+)>', content):
                entity = m.group(1)
                if entity not in report["dbcontext_entities"]:
                    report["dbcontext_entities"].append(entity)

        # Detect model/entity classes (in Models/Entities/Data directories)
        dir_name = os.path.basename(os.path.dirname(path)).lower()
        if dir_name in ("models", "model", "entities", "data", "domain"):
            for m in _re.finditer(r'public\s+class\s+(\w+)', content):
                cls = m.group(1)
                if cls not in report["model_classes"] and not cls.endswith("Context"):
                    report["model_classes"].append(cls)

        # Detect repository classes
        if _re.search(r'(Repository|Repo)\b', filename, _re.IGNORECASE):
            for m in _re.finditer(r'public\s+class\s+(\w+)', content):
                report["repository_classes"].append({"name": m.group(1), "file": rel_path})

        # Detect service classes
        if _re.search(r'Service\b', filename, _re.IGNORECASE):
            for m in _re.finditer(r'public\s+class\s+(\w+)', content):
                report["service_classes"].append({"name": m.group(1), "file": rel_path})

        # Detect controller classes
        if _re.search(r'Controller\b', filename, _re.IGNORECASE):
            for m in _re.finditer(r'public\s+class\s+(\w+)', content):
                report["controller_classes"].append({"name": m.group(1), "file": rel_path})

        # Count data access methods
        da_markers = [".Where(", ".Select(", ".Include(", ".Join(", ".GroupBy(",
                      ".FirstOrDefault(", ".SingleOrDefault(", ".ToListAsync(",
                      ".CountAsync(", ".SumAsync(", "FromSqlRaw", "ExecuteSqlRaw",
                      "SaveChangesAsync", ".Query<", ".Execute("]
        method_count = 0
        for marker in da_markers:
            method_count += content.count(marker)
        if method_count > 0:
            report["data_access_methods"].append({"file": rel_path, "marker_hits": method_count})
            report["files_scanned"].append(rel_path)
        else:
            report["files_skipped"].append(rel_path)

        # Detect stored procedure references
        for m in _re.finditer(r'(?:EXEC|EXECUTE|sp_|usp_)\s*(\w+)', content):
            sp = m.group(1) if m.group(1).startswith(('sp_', 'usp_')) else m.group(0).strip()
            if sp not in report["stored_procedure_refs"]:
                report["stored_procedure_refs"].append(sp)

        # Detect Dapper usage
        if "Dapper" in content or ".Query<" in content or "DapperExtensions" in content:
            report["dapper_usage"] = True

        # Detect raw SQL
        if "SqlCommand" in content or "SqlConnection" in content or "FromSqlRaw" in content:
            report["raw_sql_usage"] = True

    return report


def compare_extraction_coverage(pre_scan: dict, extracted_entities: list, extracted_patterns: list) -> dict:
    """Compare pre-scan inventory against LLM extraction results to find gaps."""
    dbcontext_entities = set(pre_scan.get("dbcontext_entities", []))
    model_classes = set(pre_scan.get("model_classes", []))
    extracted_set = set(extracted_entities)

    # Entities in DbContext but not extracted
    missing_entities = sorted(dbcontext_entities - extracted_set)
    # Entities extracted but not in DbContext (might be valid — DTOs, computed entities)
    extra_entities = sorted(extracted_set - dbcontext_entities - model_classes)
    # Coverage percentage
    total_expected = len(dbcontext_entities) if dbcontext_entities else len(model_classes)
    covered = len(dbcontext_entities & extracted_set) if dbcontext_entities else len(model_classes & extracted_set)
    coverage_pct = (covered / total_expected * 100) if total_expected > 0 else 0

    # Repository coverage: check if each repo class has at least one pattern
    repo_classes = [r["name"] for r in pre_scan.get("repository_classes", [])]
    repos_with_patterns = set()
    for pattern in extracted_patterns:
        for repo in repo_classes:
            entity = repo.replace("Repository", "").replace("Repo", "")
            if entity.lower() in pattern.lower():
                repos_with_patterns.add(repo)
    repos_without_patterns = sorted(set(repo_classes) - repos_with_patterns)

    # Data access file coverage
    da_files = [d["file"] for d in pre_scan.get("data_access_methods", [])]
    total_da_files = len(da_files)
    total_marker_hits = sum(d["marker_hits"] for d in pre_scan.get("data_access_methods", []))

    coverage = {
        "entity_coverage": {
            "dbcontext_entities": sorted(dbcontext_entities),
            "extracted_entities": sorted(extracted_set),
            "missing_entities": missing_entities,
            "extra_entities": extra_entities,
            "coverage_percentage": round(coverage_pct, 1),
        },
        "repository_coverage": {
            "total_repositories": len(repo_classes),
            "repositories_with_patterns": sorted(repos_with_patterns),
            "repositories_without_patterns": repos_without_patterns,
        },
        "file_coverage": {
            "total_cs_files": pre_scan["total_cs_files"],
            "files_with_data_access": total_da_files,
            "total_data_access_marker_hits": total_marker_hits,
        },
        "technology_detected": {
            "ef_core": pre_scan.get("ef_core_usage", False),
            "dapper": pre_scan.get("dapper_usage", False),
            "raw_sql": pre_scan.get("raw_sql_usage", False),
            "stored_procedures": pre_scan.get("stored_procedure_refs", []),
        },
        "warnings": [],
    }

    # Generate warnings
    if missing_entities:
        coverage["warnings"].append(f"⚠️ {len(missing_entities)} entities in DbContext not found in extraction: {', '.join(missing_entities)}")
    if repos_without_patterns:
        coverage["warnings"].append(f"⚠️ {len(repos_without_patterns)} repository classes have no extracted patterns: {', '.join(repos_without_patterns)}")
    if pre_scan.get("stored_procedure_refs"):
        coverage["warnings"].append(f"ℹ️ {len(pre_scan['stored_procedure_refs'])} stored procedure references detected — verify these are captured as access patterns")
    if pre_scan.get("dapper_usage"):
        coverage["warnings"].append("ℹ️ Dapper usage detected — ensure Dapper queries are captured (they may not use standard EF Core markers)")
    if coverage_pct < 80:
        coverage["warnings"].append(f"🔴 Entity coverage is {coverage_pct}% — below 80% threshold. Review missing entities.")
    elif coverage_pct < 100:
        coverage["warnings"].append(f"🟡 Entity coverage is {coverage_pct}% — some entities may be missing.")
    else:
        coverage["warnings"].append(f"🟢 Entity coverage is 100% — all DbContext entities found in extraction.")

    return coverage


# --- Model ---

import boto3
import json
import re

# Lazy model initialization — avoids AWS credential errors on import
_model_sonnet = None
_model_opus = None

# Model configuration — Opus for reasoning-heavy agents, Sonnet for classification/arithmetic
SONNET_MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"
OPUS_MODEL_ID = "us.anthropic.claude-opus-4-6-v1"

def _create_session():
    """Create a fresh boto3 session to pick up refreshed SSO/credentials.
    Uses AWS_PROFILE env var if set (from frontend project config), otherwise falls back to default."""
    profile = os.environ.get("AWS_PROFILE", "default")
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.Session(profile_name=profile, region_name=region)

def get_model_sonnet():
    """Get Claude Sonnet model — used for Extractor and Metrics Analyzer agents.
    Good for classification, pattern matching, and structured arithmetic."""
    global _model_sonnet
    _model_sonnet = BedrockModel(
        model_id=SONNET_MODEL_ID,
        boto_session=_create_session(),
        max_tokens=16384
    )
    return _model_sonnet

def get_model_opus():
    """Get Claude Opus 4.6 model — used for Architect and Validator agents.
    1M context window, 128K max output. Superior reasoning for complex design decisions."""
    global _model_opus
    from botocore.config import Config
    # Increase read timeout for Opus — it takes longer for complex reasoning tasks
    boto_config = Config(read_timeout=600, connect_timeout=30, retries={"max_attempts": 3})
    session = _create_session()
    _model_opus = BedrockModel(
        model_id=OPUS_MODEL_ID,
        boto_session=session,
        max_tokens=65536,  # Opus 4.6 supports up to 128K output
        boto_client_config=boto_config,
    )
    return _model_opus

def get_model():
    """Backward-compatible — returns Sonnet model."""
    return get_model_sonnet()


def load_migration_scope():
    """Load migration_scope.json and return scope config. Returns None if file doesn't exist or mode is 'full'."""
    scope_file = os.path.join(OUTPUT_DIR, "migration_scope.json")
    if not os.path.exists(scope_file):
        return None
    with open(scope_file, "r", encoding="utf-8") as f:
        scope = json.load(f)
    if scope.get("migration_mode") == "full":
        return None
    return scope


def filter_access_patterns_by_scope(scope):
    """Read access_patterns.md and entity_metrics.json, filter to only in-scope entities.
    Writes scoped_access_patterns.md and scoped_entity_metrics.json.
    Returns a summary of what was included/excluded/cross-boundary."""
    selected = set(scope["selected_entities"])
    mode = scope.get("migration_mode", "microservice")

    # --- Filter entity_metrics.json ---
    metrics_file = os.path.join(OUTPUT_DIR, "entity_metrics.json")
    if os.path.exists(metrics_file):
        with open(metrics_file, "r", encoding="utf-8") as f:
            metrics = json.load(f)

        scoped_metrics = {
            "description": f"Scoped entity metrics for migration ({mode} mode). Selected entities: {', '.join(sorted(selected))}",
            "migration_mode": mode,
            "selected_entities": sorted(selected),
            "entities": {},
            "access_patterns": {"in_scope": {}, "cross_boundary": {}},
            "write_patterns": {"in_scope": {}, "cross_boundary": {}}
        }

        # Filter entities
        for name, data in metrics.get("entities", {}).items():
            if name in selected:
                scoped_metrics["entities"][name] = data

        # Classify access patterns
        for ap_id, ap_data in metrics.get("access_patterns", {}).items():
            entities = set(ap_data.get("source_entities", []))
            in_scope = entities & selected
            out_of_scope = entities - selected
            if not in_scope:
                continue
            ap_copy = dict(ap_data)
            if out_of_scope:
                ap_copy["cross_boundary"] = True
                ap_copy["in_scope_entities"] = sorted(in_scope)
                ap_copy["out_of_scope_entities"] = sorted(out_of_scope)
                ap_copy["notes"] = ap_data.get("notes", "") + f" [CROSS-BOUNDARY: {', '.join(sorted(out_of_scope))} not in migration scope]"
                scoped_metrics["access_patterns"]["cross_boundary"][ap_id] = ap_copy
            else:
                ap_copy["cross_boundary"] = False
                scoped_metrics["access_patterns"]["in_scope"][ap_id] = ap_copy

        # Classify write patterns
        for wp_id, wp_data in metrics.get("write_patterns", {}).items():
            entities = set(wp_data.get("target_entities", []))
            in_scope = entities & selected
            out_of_scope = entities - selected
            if not in_scope:
                continue
            wp_copy = dict(wp_data)
            if out_of_scope:
                wp_copy["cross_boundary"] = True
                wp_copy["in_scope_entities"] = sorted(in_scope)
                wp_copy["out_of_scope_entities"] = sorted(out_of_scope)
                wp_copy["notes"] = wp_data.get("notes", "") + f" [CROSS-BOUNDARY: {', '.join(sorted(out_of_scope))} not in migration scope]"
                scoped_metrics["write_patterns"]["cross_boundary"][wp_id] = wp_copy
            else:
                wp_copy["cross_boundary"] = False
                scoped_metrics["write_patterns"]["in_scope"][wp_id] = wp_copy

        with open(os.path.join(OUTPUT_DIR, "scoped_entity_metrics.json"), "w", encoding="utf-8") as f:
            json.dump(scoped_metrics, f, indent=2)

    # --- Filter access_patterns.md ---
    ap_file = os.path.join(OUTPUT_DIR, "access_patterns.md")
    if os.path.exists(ap_file):
        with open(ap_file, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        output_lines = []
        current_entity = None
        in_scope_section = True
        current_pattern_id = None
        include_current_pattern = True

        in_scope_aps = set(scoped_metrics["access_patterns"]["in_scope"].keys()) if os.path.exists(metrics_file) else set()
        cross_aps = set(scoped_metrics["access_patterns"]["cross_boundary"].keys()) if os.path.exists(metrics_file) else set()
        in_scope_wps = set(scoped_metrics["write_patterns"]["in_scope"].keys()) if os.path.exists(metrics_file) else set()
        cross_wps = set(scoped_metrics["write_patterns"]["cross_boundary"].keys()) if os.path.exists(metrics_file) else set()
        all_included = in_scope_aps | cross_aps | in_scope_wps | cross_wps

        for line in lines:
            entity_match = re.match(r'^### (\w+)', line)
            if entity_match:
                current_entity = entity_match.group(1)
                entity_map = {
                    "User": "User", "Product": "Product", "Order": "Order",
                    "Review": "Review", "Inventory": "Inventory", "Category": "Category",
                    "Reports": "Order"
                }
                mapped = entity_map.get(current_entity, current_entity)
                in_scope_section = mapped in selected
                if in_scope_section:
                    output_lines.append(line)
                continue

            pattern_match = re.match(r'^#### ((?:AP|WP)-\d+):', line)
            if pattern_match:
                current_pattern_id = pattern_match.group(1)
                include_current_pattern = current_pattern_id in all_included
                if include_current_pattern:
                    if current_pattern_id in cross_aps or current_pattern_id in cross_wps:
                        output_lines.append(line + " ⚠️ CROSS-BOUNDARY")
                    else:
                        output_lines.append(line)
                continue

            if current_entity is None:
                output_lines.append(line)
                continue

            if in_scope_section and include_current_pattern:
                output_lines.append(line)

        scope_header = [
            f"<!-- Migration Scope: {mode} mode -->",
            f"<!-- Selected Entities: {', '.join(sorted(selected))} -->",
            f"<!-- In-scope patterns: {len(in_scope_aps)} read + {len(in_scope_wps)} write -->",
            f"<!-- Cross-boundary patterns: {len(cross_aps)} read + {len(cross_wps)} write -->",
            ""
        ]

        with open(os.path.join(OUTPUT_DIR, "scoped_access_patterns.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(scope_header + output_lines))

    summary = f"""Migration Scope Applied ({mode} mode):
- Selected entities: {', '.join(sorted(selected))}
- In-scope read patterns: {len(scoped_metrics['access_patterns']['in_scope'])}
- Cross-boundary read patterns: {len(scoped_metrics['access_patterns']['cross_boundary'])}
- In-scope write patterns: {len(scoped_metrics['write_patterns']['in_scope'])}
- Cross-boundary write patterns: {len(scoped_metrics['write_patterns']['cross_boundary'])}
- Files written: scoped_access_patterns.md, scoped_entity_metrics.json"""

    if scoped_metrics["access_patterns"]["cross_boundary"]:
        summary += "\n\nCross-boundary read patterns (need API/sync):"
        for ap_id, ap in scoped_metrics["access_patterns"]["cross_boundary"].items():
            summary += f"\n  {ap_id}: {ap['name']} — out-of-scope: {', '.join(ap['out_of_scope_entities'])}"

    if scoped_metrics["write_patterns"]["cross_boundary"]:
        summary += "\n\nCross-boundary write patterns (need API/sync):"
        for wp_id, wp in scoped_metrics["write_patterns"]["cross_boundary"].items():
            summary += f"\n  {wp_id}: {wp['name']} — out-of-scope: {', '.join(wp['out_of_scope_entities'])}"

    print(summary)
    return summary


# --- Agents (slim prompts — detailed rules live in templates/) ---
# Lazy initialization to avoid AWS credential errors on import

_extractor = None
_architect = None
_validator = None
_metrics_analyzer = None
_mcp_guidance_loaded = False


def _load_mcp_guidance(aws_profile: str = None, aws_region: str = "us-east-1"):
    """Fetch DynamoDB modeling guidance from the AWS MCP server and merge it with our local knowledge base.
    The merged file combines AWS-maintained DynamoDB expertise with our tool-specific rules.
    Falls back gracefully if the MCP server is unavailable."""
    global _mcp_guidance_loaded
    mcp_raw_path = os.path.join("templates", "mcp_dynamodb_guidance.md")
    merged_path = os.path.join("templates", "dynamodb_knowledge_base.md")
    local_path = os.path.join("templates", "dynamodb_best_practices.md")

    mcp_content = ""
    try:
        from backend.services.mcp_client import get_mcp_modeling_guidance
        mcp_content = get_mcp_modeling_guidance(aws_profile=aws_profile, aws_region=aws_region)
        if mcp_content and len(mcp_content) > 200:
            # Save raw MCP content for reference
            with open(mcp_raw_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(mcp_content)
            _mcp_guidance_loaded = True
            print(f"✅ Loaded DynamoDB guidance from AWS MCP server ({len(mcp_content)} chars)")
        else:
            mcp_content = ""
    except ImportError:
        pass
    except Exception as e:
        print(f"⚠️ MCP server unavailable ({e}), using local templates only")
        mcp_content = ""

    # Read local best practices
    local_content = ""
    if os.path.exists(local_path):
        with open(local_path, "r", encoding="utf-8", errors="replace") as f:
            local_content = f.read()

    # Merge: local rules are PRIMARY, MCP guidance is supplementary context
    if mcp_content:
        merged = (
            "# DynamoDB Knowledge Base (Merged)\n\n"
            "This knowledge base combines two sources:\n"
            "1. **SQL to DynamoDB Design Mentor Rules (PRIMARY)** — Tool-specific rules for output format, entity modeling, capacity scoping, and calculations. These ALWAYS take precedence.\n"
            "2. **AWS DynamoDB Expert Guidance (SUPPLEMENTARY)** — AWS-maintained design patterns and best practices from the DynamoDB MCP server. Use for additional context on DynamoDB capabilities.\n\n"
            "If any rule in Section 1 conflicts with Section 2, ALWAYS follow Section 1.\n\n"
            "---\n\n"
            "# Section 1: SQL to DynamoDB Design Mentor Rules (PRIMARY)\n\n"
            f"{local_content}\n\n"
            "---\n\n"
            "# Section 2: AWS DynamoDB Expert Guidance (SUPPLEMENTARY)\n\n"
            f"{mcp_content}\n"
        )
        with open(merged_path, "w", encoding="utf-8", errors="replace") as f:
            f.write(merged)
        print(f"📚 Merged knowledge base written ({len(merged)} chars) — local rules PRIMARY, MCP guidance supplementary")
    else:
        # No MCP content — just copy local as the knowledge base
        if local_content:
            with open(merged_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(local_content)
        _mcp_guidance_loaded = False


def _get_agents():
    global _extractor, _architect, _validator, _metrics_analyzer
    # Opus for reasoning-heavy agents (Architect, Validator)
    # Sonnet for classification/arithmetic agents (Extractor, Metrics)
    m_sonnet = get_model_sonnet()
    try:
        m_opus = get_model_opus()
        print(f"🧠 Models: Architect & Validator → Claude Opus | Extractor & Metrics → Claude Sonnet")
    except Exception as e:
        print(f"⚠️ Opus model unavailable ({e}), using Sonnet for all agents")
        m_opus = m_sonnet

    # Knowledge base reference — agents read the merged file
    kb_file = "templates/dynamodb_knowledge_base.md" if os.path.exists("templates/dynamodb_knowledge_base.md") else "templates/dynamodb_best_practices.md"
    kb_source = "merged (local + AWS MCP)" if _mcp_guidance_loaded else "local only"

    _extractor = Agent(
        model=m_sonnet,
        system_prompt="""You are a .NET data access analyst. Extract ALL access patterns from a .NET/SQL Server codebase.

STEP 1: Read templates/extractor_format.md for complete instructions and output format.
STEP 2: Run run_roslyn_analysis on the project path. This uses the .NET Compiler Platform (Roslyn) for accurate AST-based extraction of entities, relationships, and LINQ expressions. Use its output as your COMPLETE source of entities and access methods.
STEP 3: If run_roslyn_analysis fails or is unavailable, run scan_dotnet_project as a fallback to get raw source code of data access methods.
STEP 4: Write output/access_patterns.md using write_file, then append_file for additional sections.
STEP 5: Write output/entity_metrics.json using write_file.

IMPORTANT: Write output in chunks. Use write_file for the first section, then append_file for each subsequent section.
Keep each write_file/append_file call under 3000 words to avoid token limits.
Be thorough — missing a pattern means incomplete DynamoDB model.
Do NOT run both run_roslyn_analysis and scan_dotnet_project — use Roslyn if it succeeds, pattern-based scanning only as fallback.""",
        tools=[run_roslyn_analysis, scan_dotnet_project, read_file, write_file, append_file]
    )

    _architect = Agent(
        model=m_opus,
        system_prompt=f"""You are a DynamoDB single-table design expert.

STEP 1: Read {kb_file} for DynamoDB rules and best practices (knowledge base source: {kb_source})
STEP 2: Read templates/architect_format.md for output format and entity modeling rules
STEP 3: Read output/access_patterns.md and output/entity_metrics.json (if exists)
STEP 4: Write output/dynamo_model.md in chunks:
  - write_file: Table config + GSIs + first 2-3 entity mappings
  - append_file: remaining entity mappings
  - append_file: access pattern mapping (first half)
  - append_file: access pattern mapping (second half) + sample items + design decisions
STEP 5: Write output/dynamo_model.json in chunks:
  - write_file: opening {{ + tableName + primaryKey + gsis + first entityMappings
  - append_file: remaining entityMappings + accessPatternMapping + closing }}

CRITICAL: Write output in CHUNKS using write_file then append_file. Each call must be under 3000 words.
Never try to write an entire file in one call — this will hit token limits and fail.
Both files must reflect the same design. Use C# for all DynamoDB query code.
CRITICAL: The architect_format.md template is the AUTHORITATIVE source for output structure, entity modeling rules, and JSON schema. Follow it exactly.""",
        tools=[read_file, write_file, append_file]
    )

    _validator = Agent(
        model=m_opus,
        system_prompt=f"""You are a DynamoDB access pattern validator and execution classifier.

STEP 1: Read {kb_file} for DynamoDB rules (knowledge base source: {kb_source})
STEP 2: Read templates/validator_format.md for validation rules and output format
STEP 3: Read output/access_patterns.md and output/dynamo_model.md
STEP 4: Write output/validation_report.md in chunks:
  - write_file: Expression validation issues + SK prefix issues + sort order issues
  - append_file: Entity modeling validation + coverage matrix
  - append_file: Server-side patterns + filter patterns + client-side + not possible
  - append_file: Coverage summary + recommendations

CRITICAL: Write output in CHUNKS using write_file then append_file. Each call must be under 3000 words.
CRITICAL: The validator_format.md template is the AUTHORITATIVE source for validation rules and output structure.""",
        tools=[read_file, write_file, append_file]
    )

    _metrics_analyzer = Agent(
        model=m_sonnet,
        system_prompt=f"""You are a DynamoDB capacity planning expert.

STEP 1: Read {kb_file} for DynamoDB rules and capacity formulas (knowledge base source: {kb_source})
STEP 2: Read templates/metrics_format.md for capacity analysis rules and output format
STEP 3: Read output/entity_metrics.json, output/access_patterns.md, and output/dynamo_model.md
STEP 4: Write output/capacity_analysis.md in chunks:
  - write_file: Entity size summary + first 2 relationship analyses
  - append_file: remaining relationship analyses
  - append_file: access pattern capacity breakdown + write pattern breakdown
  - append_file: total capacity estimate + recommendations

CRITICAL: Write output in CHUNKS using write_file then append_file. Each call must be under 3000 words.
CRITICAL: The metrics_format.md template is the AUTHORITATIVE source for capacity analysis rules and output structure.
Do NOT include dollar cost estimates — show only RCU/WCU numbers.""",
        tools=[read_file, write_file, append_file]
    )


# Public accessors for pipeline_runner.py imports
def get_extractor():
    _get_agents()
    return _extractor

def get_architect():
    _get_agents()
    return _architect

def get_validator():
    _get_agents()
    return _validator

def get_metrics_analyzer():
    _get_agents()
    return _metrics_analyzer


def run(project_path: str = None, skip_extract: bool = False, skip_metrics: bool = False):
    # Load DynamoDB expert guidance from AWS MCP server (falls back to local templates)
    print("=== Loading DynamoDB modeling guidance ===")
    _load_mcp_guidance()

    if not skip_extract:
        if not project_path:
            raise ValueError("Provide .NET project path or use --skip-extract")
        print("=== Phase 1: Extracting access patterns from .NET project ===")
        get_extractor()(f"Scan the .NET project at {project_path} and extract all access patterns into output/access_patterns.md")
    else:
        print("=== Skipping extraction, using existing access_patterns.md ===")

    # --- Scope filtering ---
    scope = load_migration_scope()
    if scope:
        print(f"\n=== Applying migration scope ({scope.get('migration_mode')}) ===")
        filter_access_patterns_by_scope(scope)
        ap_file = os.path.join(OUTPUT_DIR, "scoped_access_patterns.md")
        metrics_file = os.path.join(OUTPUT_DIR, "scoped_entity_metrics.json")
        scope_instruction = (
            f" IMPORTANT: This is a scoped migration ({scope.get('migration_mode')} mode). "
            f"Only these entities are in scope: {', '.join(scope['selected_entities'])}. "
            f"Read {ap_file} (not access_patterns.md) for the filtered access patterns. "
            f"Patterns marked CROSS-BOUNDARY reference entities outside the migration scope — "
            f"for these, design the DynamoDB model for the in-scope entities only and note that "
            f"out-of-scope data must be fetched via API call or event sync."
        )
    else:
        print("\n=== No migration scope filter (full migration) ===")
        ap_file = os.path.join(OUTPUT_DIR, "access_patterns.md")
        metrics_file = os.path.join(OUTPUT_DIR, "entity_metrics.json")
        scope_instruction = ""

    print("\n=== Phase 2: Designing DynamoDB model ===")
    get_architect()(
        f"Read templates/dynamodb_best_practices.md and templates/architect_format.md first. "
        f"Then read {ap_file} and design the DynamoDB model.{scope_instruction} "
        f"If {metrics_file} exists, read it and use the metrics to make data-driven modeling decisions. "
        f"Write ONLY output/dynamo_model.md in chunks: use write_file for the first section (table config + GSIs + first 2 entity mappings), "
        f"then use append_file for remaining entity mappings, then append_file for access pattern mappings, "
        f"then append_file for sample items and design decisions. Each write/append under 2000 words. "
        f"Do NOT write output/dynamo_model.json yet."
    )
    get_architect()(
        f"Read the output/dynamo_model.md you just created. Now write output/dynamo_model.json with the SAME design. "
        f"Write it in chunks: use write_file for the opening structure, then append_file for remaining sections. "
        f"Each write/append under 2000 words. The JSON must be valid and parseable when complete."
    )

    print("\n=== Phase 3: Validating and classifying patterns ===")
    get_validator()(
        f"Read templates/dynamodb_best_practices.md and templates/validator_format.md first. "
        f"Then read {ap_file} and output/dynamo_model.md. Validate coverage and classify each pattern.{scope_instruction} "
        f"Write output/validation_report.md in chunks: use write_file for first section, then append_file for remaining. "
        f"Each write/append under 2000 words."
    )

    if not skip_metrics:
        if os.path.exists(metrics_file):
            print("\n=== Phase 4: Analyzing capacity metrics ===")
            get_metrics_analyzer()(
                f"Read templates/dynamodb_best_practices.md and templates/metrics_format.md first. "
                f"Then read {metrics_file}, {ap_file}, and output/dynamo_model.md. "
                f"Write output/capacity_analysis.md in chunks: use write_file for first section, then append_file for remaining. "
                f"Each write/append under 2000 words."
            )
        else:
            print(f"\n=== Skipping Phase 4: {metrics_file} not found. ===")
    else:
        print("\n=== Skipping Phase 4: Metrics analysis (--skip-metrics) ===")


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    skip = "--skip-extract" in args
    skip_met = "--skip-metrics" in args
    path = next((a for a in args if not a.startswith("--")), None)
    run(project_path=path, skip_extract=skip, skip_metrics=skip_met)
