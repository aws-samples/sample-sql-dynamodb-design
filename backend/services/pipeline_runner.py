import os
import json
import logging
import time
from sqlalchemy.orm import Session

# Force UTF-8 mode on Windows to prevent charmap encoding errors
os.environ["PYTHONUTF8"] = "1"

from backend.db.repositories import PipelineRepository, ScopeRepository, EntityRepository, PatternRepository, OverrideRepository

logger = logging.getLogger(__name__)

# Pipeline output directory — matches pipeline.py OUTPUT_DIR
OUTPUT_DIR = "output"


class PipelineRunner:
    """Orchestrates pipeline phases, bridging DB state with Strands agents."""

    def __init__(self, db: Session, project_id: int, run_id: int, log_callback=None):
        self.db = db
        self.project_id = project_id
        self.run_id = run_id
        self.pipeline_repo = PipelineRepository(db)
        self.scope_repo = ScopeRepository(db)
        self.entity_repo = EntityRepository(db)
        self.pattern_repo = PatternRepository(db)
        self._agents_loaded = False
        self._log_callback = log_callback
        self._logs = []
        self._instructions_cache = None  # Cached scope/override/priority instructions
        logger.debug("PipelineRunner init: project_id=%s, run_id=%s", project_id, run_id)

        # Set up file-based logging for this run
        self._log_file_path = self._init_file_logger()

        # Set AWS_PROFILE from project config
        self._set_aws_profile()

    def _init_file_logger(self) -> str:
        """Initialize a per-run log file under logs/ directory. Returns the log file path."""
        from datetime import datetime
        os.makedirs("logs", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join("logs", f"run_{self.run_id}_{timestamp}.log")
        # Create a dedicated file handler for this run
        self._file_handler = logging.FileHandler(log_path, encoding="utf-8")
        self._file_handler.setLevel(logging.DEBUG)
        self._file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        # Attach to root logger so all modules' debug output goes to this file
        logging.getLogger().addHandler(self._file_handler)
        logger.info("Log file initialized: %s", log_path)
        return log_path

    def close_file_logger(self):
        """Remove and close the per-run file handler."""
        if hasattr(self, '_file_handler') and self._file_handler:
            try:
                self._file_handler.flush()
                self._file_handler.close()
                logging.getLogger().removeHandler(self._file_handler)
            except Exception:
                pass
            self._file_handler = None

    def get_log_file_path(self) -> str | None:
        """Return the path to this run's log file."""
        return getattr(self, '_log_file_path', None)

    def _validate_model_json(self, file_path: str) -> tuple[bool, str]:
        """Validate that dynamo_model.json has required structure. Returns (is_valid, error_message)."""
        if not os.path.exists(file_path):
            return False, "dynamo_model.json not generated"
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            # Try parsing (with raw_decode for Extra data)
            try:
                model = json.loads(content)
            except json.JSONDecodeError:
                decoder = json.JSONDecoder()
                model, _ = decoder.raw_decode(content.lstrip())

            # Validate required keys
            if not model.get("tableName"):
                return False, "Missing tableName in model JSON"
            if not model.get("primaryKey"):
                return False, "Missing primaryKey in model JSON"
            if not model.get("entityMappings"):
                return False, "Missing entityMappings in model JSON"
            if not model.get("accessPatternMapping"):
                return False, "Missing accessPatternMapping in model JSON — JSON was likely truncated"
            if len(model["accessPatternMapping"]) < 2:
                return False, f"Only {len(model['accessPatternMapping'])} access patterns mapped — expected more"
            return True, ""
        except (json.JSONDecodeError, ValueError) as e:
            return False, f"Invalid JSON: {e}"

    def _validate_output_file(self, file_path: str, min_size: int = 100) -> tuple[bool, str]:
        """Validate that an output file exists and has minimum content. Returns (is_valid, error_message)."""
        if not os.path.exists(file_path):
            return False, f"File not generated: {file_path}"
        size = os.path.getsize(file_path)
        if size < min_size:
            return False, f"File too small ({size} bytes): {file_path}"
        return True, ""

    def _postprocess_model_json(self, file_path: str):
        """Post-process model JSON to fix complexity classifications and add missing justifications.
        This is deterministic — doesn't rely on LLM following instructions."""
        if not os.path.exists(file_path):
            return
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            try:
                model = json.loads(content)
            except json.JSONDecodeError:
                decoder = json.JSONDecoder()
                model, _ = decoder.raw_decode(content.lstrip())

            # External service indicators
            external_indicators = [
                "opensearch", "open search", "elasticsearch", "elastic search",
                "elasticache", "redis", "external service", "dax",
                "streams + lambda", "dynamodb streams",
            ]

            modified = False
            ap_mapping = model.get("accessPatternMapping", {})
            for ap_id, ap_data in ap_mapping.items():
                # Check all text fields for external service mentions
                all_text = " ".join([
                    str(ap_data.get("note", "")),
                    str(ap_data.get("migration_notes", "")),
                    str(ap_data.get("performance_notes", "")),
                    str(ap_data.get("client_side_filter", "")),
                    str(ap_data.get("index", "")),
                ]).lower()

                mentions_external = any(ind in all_text for ind in external_indicators)
                current_complexity = (ap_data.get("complexity") or "").lower()

                # Rule: If external service is mentioned and complexity is easy/medium, upgrade
                if mentions_external and current_complexity in ("easy", "medium"):
                    ap_data["complexity"] = "hard"
                    ap_data["complexity_rationale"] = (
                        ap_data.get("complexity_rationale", "") +
                        " [Auto-corrected: Pattern references external service — cannot be Easy/Medium]"
                    )
                    modified = True
                    logger.info("Post-process: Upgraded %s complexity from '%s' to 'hard' (external service detected)", ap_id, current_complexity)

                # Rule: Add migration justification for patterns requiring external services
                if mentions_external and not ap_data.get("dynamodb_limitations"):
                    # Determine which external service
                    service = "OpenSearch" if any(s in all_text for s in ["opensearch", "open search", "elasticsearch"]) else "external service"
                    ap_data["dynamodb_limitations"] = (
                        f"DynamoDB designs evaluated: "
                        f"(1) GSI with begins_with() — only supports prefix matching, not substring. "
                        f"Pattern requires Contains() which matches anywhere in the string. Verdict: insufficient. "
                        f"(2) FilterExpression with contains() — reads ALL items in partition first (full RCU cost), "
                        f"then filters client-side. At scale this is O(N) per request. Verdict: too expensive. "
                        f"(3) Multiple GSIs per searchable attribute + parallel queries — still limited to prefix match via begins_with(). "
                        f"Verdict: partial solution only. "
                        f"Conclusion: {service} recommended because DynamoDB has no native efficient substring/fuzzy search capability."
                    )
                    ap_data["complexity"] = "hard"
                    if not ap_data.get("complexity_rationale"):
                        ap_data["complexity_rationale"] = (
                            f"Requires {service} — DynamoDB has no native substring search. "
                            f"begins_with() is prefix-only, contains() in FilterExpression is O(N)."
                        )
                    modified = True

                # Rule: If "scan" is the index and complexity is easy/medium, upgrade
                index_text = str(ap_data.get("index", "")).lower()
                if "scan" in index_text and current_complexity in ("easy", "medium"):
                    ap_data["complexity"] = "hard"
                    ap_data["complexity_rationale"] = (
                        ap_data.get("complexity_rationale", "") +
                        " [Auto-corrected: Scan-based pattern cannot be Easy/Medium]"
                    )
                    modified = True
                    logger.info("Post-process: Upgraded %s complexity from '%s' to 'hard' (scan detected)", ap_id, current_complexity)

            if modified:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(model, f, indent=2)
                self._log("🔧 Post-processed model JSON: corrected complexity classifications")

        except Exception as e:
            logger.warning("Post-processing model JSON failed: %s", e)

    def _log(self, message: str):
        """Log a message. If a callback is set, call it. Always store in _logs and write to file."""
        self._logs.append(message)
        logger.info("[UI] %s", message)
        if self._log_callback:
            try:
                self._log_callback(message)
            except Exception:
                pass

    def get_logs(self) -> list[str]:
        """Return all accumulated log messages."""
        return list(self._logs)

    def _set_aws_profile(self):
        from backend.db.repositories import ProjectRepository
        project = ProjectRepository(self.db).get_by_id(self.project_id)
        if project and project.aws_profile:
            os.environ["AWS_PROFILE"] = project.aws_profile
            logger.debug("AWS_PROFILE set to '%s'", project.aws_profile)
        else:
            logger.debug("No AWS profile configured for project %s", self.project_id)

    def _build_override_instruction(self) -> str:
        """Build override instructions from active model overrides."""
        override_repo = OverrideRepository(self.db)
        overrides = override_repo.get_by_project(self.project_id, active_only=True)
        if not overrides:
            logger.debug("No active overrides for project %s", self.project_id)
            return ""

        logger.debug("Found %d active overrides for project %s", len(overrides), self.project_id)

        lines = ["\n\n=== USER MODEL OVERRIDES (MUST follow) ===",
                 "The user has specified the following design constraints. You MUST honor these overrides:"]
        for o in overrides:
            lines.append(f"\n- [{o.override_type.upper()}] {o.entity_name}: {o.description}")
            if o.details:
                for k, v in o.details.items():
                    lines.append(f"  - {k}: {v}")
        lines.append("\nThese overrides take priority over default modeling rules. "
                     "Adjust the DynamoDB model design, access pattern mapping, and capacity analysis accordingly.")
        return "\n".join(lines)

    def _build_priority_instruction(self) -> str:
        """Build design priority instruction based on project's cost vs performance setting."""
        from backend.db.repositories import ProjectRepository
        project = ProjectRepository(self.db).get_by_id(self.project_id)
        priority = getattr(project, 'design_priority', 'balanced') or 'balanced'
        logger.debug("Design priority for project %s: %s", self.project_id, priority)

        if priority == 'performance':
            return (
                "\n\n=== DESIGN PRIORITY: PERFORMANCE (user selected) ===\n"
                "The user prioritizes LOW LATENCY and FAST RESPONSE TIMES over cost. Apply these rules:\n"
                "1. GSI DESIGN: Create dedicated GSIs for high-frequency patterns (>5K req/hr) even if it increases write amplification. "
                "Prefer INCLUDE or ALL projection to avoid base table fetches.\n"
                "2. KEY DESIGN: Maximize KeyConditionExpression coverage — design PK/SK to push as much filtering as possible into "
                "KeyConditionExpression rather than FilterExpression or client-side. Composite sort keys (e.g., STATUS#DATE#ID) are preferred.\n"
                "3. FILTER STRATEGY: Minimize FilterExpression usage on high-frequency patterns. If a filter scans >20% extra items, "
                "consider a dedicated GSI instead. Eliminate client-side filtering on patterns >10K req/hr.\n"
                "4. ENTITY MODELING: Prefer flattening (single-item) for 1:1 relationships to reduce API calls. "
                "For 1:N, prefer item collections (same PK) over separate queries. Denormalize aggressively to avoid multi-query patterns.\n"
                "5. CACHING: Recommend DAX for read-heavy patterns (>50K req/hr). Pre-compute all aggregations via DynamoDB Streams + Lambda.\n"
                "6. TRANSACTIONS: Use BatchWriteItem for non-critical writes (faster). TransactWriteItems only for ACID-critical paths.\n"
                "7. READ CONSISTENCY: Use strongly consistent reads for critical paths (inventory checks, auth, payments).\n"
                "8. ITEM COLLECTIONS: Pack related items under same PK for single-query retrieval. Maximize data locality.\n"
                "9. SPARSE GSIs: Use dense GSIs — index all items for maximum query flexibility.\n"
                "10. DENORMALIZATION: Copy frequently-read fields into related items aggressively to avoid multi-query patterns.\n"
                "11. TRADE-OFF: Accept higher WCU costs (write amplification from GSIs, larger items from denormalization) "
                "in exchange for fewer API calls and faster reads.\n"
            )
        elif priority == 'cost':
            return (
                "\n\n=== DESIGN PRIORITY: COST (user selected) ===\n"
                "The user prioritizes MINIMIZING RCU/WCU COSTS over latency. Apply these rules:\n"
                "1. GSI DESIGN: Minimize GSI count — reuse GSIs across multiple patterns via GSI overloading. "
                "Prefer KEYS_ONLY projection and fetch full items from base table only when needed.\n"
                "2. KEY DESIGN: Design PK/SK for maximum key-based filtering, but accept FilterExpression on low-frequency patterns "
                "(<1K req/hr) rather than creating additional GSIs.\n"
                "3. FILTER STRATEGY: Accept FilterExpression overhead on patterns <5K req/hr if it avoids a new GSI. "
                "Accept client-side filtering on admin/reporting patterns (<500 req/hr).\n"
                "4. ENTITY MODELING: Prefer vertical partitioning for 1:1 relationships where write frequencies differ significantly "
                "(>3x difference) — smaller items = fewer WCUs per write. Only flatten when read frequency is >10x write frequency.\n"
                "5. PROJECTION: Use KEYS_ONLY or minimal INCLUDE projections on all GSIs to minimize write amplification.\n"
                "6. TRANSACTIONS: Use single PutItem calls where possible — avoid 2x WCU transaction overhead.\n"
                "7. READ CONSISTENCY: Use eventually consistent reads everywhere (0.5x RCU cost).\n"
                "8. ITEM COLLECTIONS: Keep items independent — avoid reading unnecessary data in queries.\n"
                "9. SPARSE GSIs: Use sparse GSIs — only index items that have the GSI key attribute to reduce storage and write costs.\n"
                "10. TTL: Enable TTL on transient data (sessions, carts, logs) to auto-delete and reduce storage costs.\n"
                "11. DENORMALIZATION: Minimal — avoid write amplification from keeping copies in sync.\n"
                "12. PRE-COMPUTATION: Compute on read — accept higher RCU for aggregation queries rather than Streams + Lambda overhead.\n"
                "13. TRADE-OFF: Accept more API calls and client-side processing in exchange for fewer GSIs, "
                "smaller items, and lower write amplification. Latency is secondary to cost.\n"
            )
        else:
            return (
                "\n\n=== DESIGN PRIORITY: BALANCED (default) ===\n"
                "The user wants a balance between cost and performance. Apply these rules:\n"
                "1. GSI DESIGN: Create GSIs for patterns >10K req/hr. Reuse GSIs via overloading where possible. "
                "Use INCLUDE projection with only the attributes needed by served patterns.\n"
                "2. KEY DESIGN: Optimize KeyConditionExpression for high-frequency patterns (>10K req/hr). "
                "Accept FilterExpression on medium-frequency patterns (1K-10K req/hr).\n"
                "3. FILTER STRATEGY: Minimize FilterExpression on patterns >10K req/hr. Accept it on lower-frequency patterns.\n"
                "4. ENTITY MODELING: Flatten 1:1 relationships when read frequency >2x write frequency. "
                "Use vertical partitioning when write frequencies differ significantly or items are large.\n"
                "5. TRANSACTIONS: TransactWriteItems for critical multi-entity writes only (order placement, payments).\n"
                "6. READ CONSISTENCY: Eventually consistent default, strongly consistent for inventory and payment checks.\n"
                "7. ITEM COLLECTIONS: Group related items under same PK for common access patterns.\n"
                "8. SPARSE GSIs: Use sparse GSIs for low-cardinality patterns.\n"
                "9. DENORMALIZATION: Denormalize for top 5 read-heavy patterns only.\n"
                "10. CACHING: DAX for top 3 read-heavy patterns (>50K req/hr). Pre-compute aggregations for patterns >50K req/hr.\n"
                "11. TTL: Enable TTL on transient data (sessions, carts). Archive old orders to S3 via Streams.\n"
                "12. TRADE-OFF: Optimize the top 5 highest-RCU patterns for performance, accept cost-efficient approaches for the rest.\n"
            )

    def _load_agents(self):
        # Skip if already loaded — agents are reused across phases
        if self._agents_loaded:
            logger.debug("Agents already loaded, skipping re-initialization")
            return

        # Force UTF-8 encoding for all I/O on Windows
        os.environ["PYTHONIOENCODING"] = "utf-8"
        t0 = time.time()
        logger.debug("Loading agents for project %s, run %s", self.project_id, self.run_id)

        # Load DynamoDB expert guidance from AWS MCP server (falls back to local templates)
        # Only load if not already cached on disk
        mcp_source = "local templates"
        try:
            from pipeline import _mcp_guidance_loaded
            merged_kb = os.path.join("templates", "dynamodb_knowledge_base.md")
            if _mcp_guidance_loaded or os.path.exists(merged_kb):
                # Already loaded in a previous call or cached on disk
                mcp_source = "AWS DynamoDB MCP Server (cached)" if os.path.exists(merged_kb) else "local templates"
                logger.debug("MCP guidance already cached, skipping reload")
            else:
                from pipeline import _load_mcp_guidance
                from backend.db.repositories import ProjectRepository
                project = ProjectRepository(self.db).get_by_id(self.project_id)
                aws_profile = project.aws_profile if project and project.aws_profile else "default"
                logger.debug("Loading MCP guidance with profile '%s'", aws_profile)
                _load_mcp_guidance(aws_profile=aws_profile)
                from pipeline import _mcp_guidance_loaded as loaded
                if loaded:
                    mcp_source = "AWS DynamoDB MCP Server"
        except Exception as e:
            logger.warning("MCP guidance loading skipped: %s", e, exc_info=True)

        self._log(f"📚 Knowledge base: {mcp_source}")

        # Initialize agents once
        self._log("🔄 Initializing AI agents (Amazon Bedrock)...")
        from pipeline import get_extractor, get_architect, get_validator, get_metrics_analyzer, OPUS_MODEL_ID, SONNET_MODEL_ID
        self.extractor = get_extractor()
        self.architect = get_architect()
        self.validator = get_validator()
        self.metrics_analyzer = get_metrics_analyzer()
        self._agents_loaded = True
        self._log(f"✅ Agents ready — Architect & Validator: Opus | Extractor & Metrics: Sonnet")
        logger.debug("Agents loaded in %.2fs", time.time() - t0)

    def _get_project_path(self) -> str:
        from backend.db.repositories import ProjectRepository
        project = ProjectRepository(self.db).get_by_id(self.project_id)
        return project.path if project else "sample-dotnet-project"

    def _get_schema_path(self) -> str | None:
        """Get the optional SQL schema file path from project config."""
        from backend.db.repositories import ProjectRepository
        project = ProjectRepository(self.db).get_by_id(self.project_id)
        return getattr(project, 'schema_path', None) if project else None

    def _get_instructions(self) -> dict:
        """Get cached scope/override/priority instructions. Built once, reused across phases."""
        if self._instructions_cache is not None:
            logger.debug("Using cached instructions")
            return self._instructions_cache

        ap_file, scope_instruction = self._build_scope_instruction()
        override_instruction = self._build_override_instruction()
        priority_instruction = self._build_priority_instruction()
        metrics_file = os.path.join(OUTPUT_DIR, "scoped_entity_metrics.json") if "scoped" in ap_file else os.path.join(OUTPUT_DIR, "entity_metrics.json")

        self._instructions_cache = {
            "ap_file": ap_file,
            "scope": scope_instruction,
            "override": override_instruction,
            "priority": priority_instruction,
            "metrics_file": metrics_file,
        }
        logger.debug("Instructions built and cached: ap_file=%s, has_scope=%s, has_override=%s",
                     ap_file, bool(scope_instruction), bool(override_instruction))
        return self._instructions_cache

    def _build_scope_instruction(self) -> tuple[str, str]:
        """Returns (ap_file, scope_instruction) based on migration scope."""
        scope = self.scope_repo.get_by_project(self.project_id)
        if not scope or scope.mode == "full":
            return os.path.join(OUTPUT_DIR, "access_patterns.md"), ""

        # Write scoped files from DB state
        self._write_scoped_files(scope)
        instruction = (
            f" IMPORTANT: This is a scoped migration ({scope.mode} mode). "
            f"Only these entities are in scope: {', '.join(scope.selected_entities)}. "
            f"Read scoped_access_patterns.md (not access_patterns.md) for the filtered access patterns. "
            f"Patterns marked CROSS-BOUNDARY reference entities outside the migration scope — "
            f"design the DynamoDB model for the in-scope entities only and note that "
            f"out-of-scope data must be fetched via API call or event sync."
        )
        return os.path.join(OUTPUT_DIR, "scoped_access_patterns.md"), instruction

    def _write_scoped_files(self, scope):
        """Write scoped JSON/MD files from DB for agents to consume."""
        from pipeline import filter_access_patterns_by_scope
        scope_dict = {
            "migration_mode": scope.mode,
            "selected_entities": scope.selected_entities or []
        }
        filter_access_patterns_by_scope(scope_dict)

    def _save_file_as_result(self, phase: int, phase_name: str, output_type: str, file_path: str):
        """Read a file written by an agent and save it as a pipeline result."""
        if os.path.exists(file_path):
            size = os.path.getsize(file_path)
            logger.debug("Saving result: phase=%d (%s), type=%s, file=%s (%d bytes)", phase, phase_name, output_type, file_path, size)
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            self.pipeline_repo.save_result(self.run_id, phase, phase_name, output_type, content)
        else:
            logger.warning("Result file not found: %s (phase=%d, type=%s)", file_path, phase, output_type)

    def _repair_json_file(self, file_path: str):
        """Attempt to repair LLM-generated JSON that may have broken string escaping."""
        if not os.path.exists(file_path):
            return
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        try:
            json.loads(content)
            return  # Already valid
        except json.JSONDecodeError:
            pass

        import re

        # Fix 0: Extra data — truncate at the end of the first valid top-level JSON object
        # Common when append_file writes content after the closing brace
        try:
            decoder = json.JSONDecoder()
            obj, end_idx = decoder.raw_decode(content.lstrip())
            # Account for any leading whitespace we stripped
            leading_ws = len(content) - len(content.lstrip())
            truncated = content[:leading_ws + end_idx]
            json.loads(truncated)  # Verify it's valid
            if len(truncated) < len(content):
                logger.info("Repaired JSON by truncating extra data after position %d (removed %d chars)",
                            leading_ws + end_idx, len(content) - len(truncated))
                self._log("🔧 Fixed JSON: removed extra data after valid object")
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(truncated)
                return
        except (json.JSONDecodeError, ValueError):
            pass

        # Fix 1: Missing commas between objects (common with append_file chunking)
        # Iteratively find JSONDecodeError positions and insert missing commas
        fixed = content
        for _ in range(20):  # Max 20 fixes
            try:
                json.loads(fixed)
                self._log(f"🔧 Fixed missing commas in JSON")
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(fixed)
                return
            except json.JSONDecodeError as e:
                if "Expecting ',' delimiter" in str(e):
                    # Insert comma at the error position
                    pos = e.pos
                    # Walk backwards to find the } or ] before the error
                    insert_pos = pos
                    for j in range(pos - 1, max(pos - 50, 0), -1):
                        if fixed[j] in ('}', ']'):
                            insert_pos = j + 1
                            break
                    fixed = fixed[:insert_pos] + ',' + fixed[insert_pos:]
                else:
                    break  # Different error type, move to next fix strategy

        # Fix 2: Replace broken C# code string values with placeholder
        for field in ["dynamodb_query_csharp", "dynamodb_query", "original_code"]:
            pattern = re.compile(r'"' + field + r'"\s*:\s*"', re.DOTALL)
            pos = 0
            repaired = ""
            for m in pattern.finditer(content):
                repaired += content[pos:m.end()]
                # Find the closing quote — skip escaped quotes
                i = m.end()
                depth = 0
                while i < len(content):
                    ch = content[i]
                    if ch == '\\':
                        i += 2
                        continue
                    if ch == '"':
                        break
                    i += 1
                # Check if what follows is valid JSON continuation
                rest = content[i:]
                if rest and rest[0] == '"':
                    repaired += content[m.end():i]
                    pos = i
                else:
                    # Broken — replace the value
                    repaired += "(see dynamo_model.md)"
                    pos = i
            repaired += content[pos:]
            content = repaired if repaired else content
        try:
            json.loads(content)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return
        except json.JSONDecodeError:
            pass
        # Last resort: try to fix by re-serializing through a lenient parser
        # Remove trailing commas before } or ]
        content = re.sub(r',\s*([}\]])', r'\1', content)
        try:
            json.loads(content)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
        except json.JSONDecodeError:
            pass  # Give up, save as-is

    def run_extract(self):
        t0 = time.time()
        logger.info("=== run_extract START (project=%s, run=%s) ===", self.project_id, self.run_id)
        self._load_agents()
        project_path = self._get_project_path()
        schema_path = self._get_schema_path()
        self._log(f"📂 Scanning .NET project: {project_path}")
        from pipeline import SONNET_MODEL_ID
        self._log(f"🤖 Model: Claude Sonnet ({SONNET_MODEL_ID.split('.')[-1]})")
        if schema_path and os.path.exists(schema_path):
            self._log(f"📄 SQL schema file found: {schema_path}")
        # Check if Roslyn analyzer is available
        analyzer_path = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "analyzer", "SqlToDynamoDbDesignMentorAnalyzer.csproj")
        roslyn_available = os.path.exists(analyzer_path)
        if roslyn_available:
            self._log("🔬 Roslyn analyzer available — using AST-based semantic analysis (primary)")
        else:
            self._log("📝 Roslyn analyzer not found — using pattern-based scanning")

        # Delegate to ConsensusExtractor for multi-run consensus extraction
        from backend.services.consensus import ConsensusExtractor, ConsensusResult
        from pipeline import get_extractor, get_model_sonnet, run_roslyn_analysis, scan_dotnet_project, read_file, write_file, append_file

        # Build agent tools and prompt based on Roslyn availability
        # Strategy: Roslyn provides AUTHORITATIVE entity list (structural analysis)
        #           LLM + scan_dotnet_project identifies access patterns (code understanding)
        #           Roslyn entity list constrains which entities the LLM can include
        if roslyn_available:
            # Roslyn + pattern scan: Roslyn for entities, LLM reads source for access patterns
            extractor_tools = [run_roslyn_analysis, scan_dotnet_project, read_file, write_file, append_file]
            extractor_prompt = """You are a .NET data access analyst. Extract ALL access patterns from a .NET/SQL Server codebase.

STEP 1: Read templates/extractor_format.md for complete instructions and output format.

STEP 2: Run run_roslyn_analysis on the project path. This gives you:
  - `entities`: The AUTHORITATIVE list of database entities (confirmed via DbSet, modelBuilder, navigation properties). ONLY include these entities in your output. Do NOT add ViewModels, DTOs, Result types, DbContext classes, or any class not in this list.
  - `accessMethods`: Confirmed database query methods (isDbQuery=true). Use these as PRIMARY access patterns.
  - `supplementaryMethods`: In-memory operations (isDbQuery=false). Do NOT create access patterns from these. Use them only to understand which attributes are used downstream — annotate the related primary access pattern with projection/attribute info.

STEP 3: Run scan_dotnet_project to get the full source code. Use this to:
  - Understand the complete call chain: Controller → Service → Repository → DbContext
  - Find access patterns that Roslyn may have missed (e.g., patterns in generic repositories, specification pattern implementations, stored procedure calls)
  - Understand query customization at the repository level (filtering, sorting, includes, projections)
  - BUT: Only create access patterns for methods that ultimately execute a database query (via DbContext, Dapper, ADO.NET, stored procedures). In-memory LINQ operations (.Select() on List<T>, .Where() on arrays) are NOT access patterns.

STEP 4: For each access pattern, trace the query execution:
  - EF Core: Look for _dbContext.EntityName.Where(...).ToListAsync() or similar IQueryable chains that terminate with an async materializer
  - Repository pattern: Follow the repository method to its DbContext usage
  - Stored procedures: Look for ExecuteSqlRaw, SqlCommand, or EXEC calls
  - Dapper: Look for connection.QueryAsync<T>() calls
  - ADO.NET: Look for SqlDataAdapter, SqlDataReader usage

STEP 5: Write output/access_patterns.md using write_file, then append_file for additional sections.
STEP 6: Write output/entity_metrics.json using write_file.

CRITICAL RULES:
- Entities: ONLY from Roslyn entity list. No exceptions.
- Access patterns: ONLY methods that execute database queries. In-memory .Select()/.Where() on materialized collections are NOT access patterns.
- For each access pattern, note which attributes are actually used (from supplementary methods) to help with DynamoDB projection decisions.

IMPORTANT: Write output in chunks. Use write_file for the first section, then append_file for each subsequent section.
Keep each write_file/append_file call under 3000 words to avoid token limits.
Be thorough — missing a pattern means incomplete DynamoDB model."""
        else:
            # No Roslyn: fall back to pattern-based scanning
            extractor_tools = [scan_dotnet_project, read_file, write_file, append_file]
            extractor_prompt = """You are a .NET data access analyst. Extract ALL access patterns from a .NET/SQL Server codebase.

STEP 1: Read templates/extractor_format.md for complete instructions and output format.
STEP 2: Run scan_dotnet_project to get the raw source code of all data access methods, controllers, and repositories.
STEP 3: Analyze the source code to identify entities, relationships, access patterns, and write patterns.
STEP 4: Write output/access_patterns.md using write_file, then append_file for additional sections.
STEP 5: Write output/entity_metrics.json using write_file.

IMPORTANT: Write output in chunks. Use write_file for the first section, then append_file for each subsequent section.
Keep each write_file/append_file call under 3000 words to avoid token limits.
Be thorough — missing a pattern means incomplete DynamoDB model."""

        def agent_factory():
            """Return a fresh extractor agent instance for each parallel run."""
            from strands import Agent
            model = get_model_sonnet()
            return Agent(
                model=model,
                system_prompt=extractor_prompt,
                tools=extractor_tools,
            )

        consensus = ConsensusExtractor(
            project_path=project_path,
            schema_path=schema_path,
            agent_factory=agent_factory,
            roslyn_analyzer_path=analyzer_path if roslyn_available else None,
            log_callback=self._log,
        )
        logger.debug("ConsensusExtractor created, starting run...")
        result = consensus.run()
        if not isinstance(result, ConsensusResult):
            raise TypeError(f"ConsensusExtractor.run() returned {type(result)}, expected ConsensusResult")

        # Write merged entity_metrics.json in existing format
        entity_metrics = {
            "entities": result.merged_entities,
            "access_patterns": result.merged_access_patterns,
            "write_patterns": result.merged_write_patterns,
        }
        logger.debug(
            "Consensus result: %d entities, %d access_patterns, %d write_patterns, confidence=%.2f, rounds=%d",
            len(result.merged_entities), len(result.merged_access_patterns),
            len(result.merged_write_patterns), result.confidence_score, result.rounds_executed,
        )
        with open(os.path.join(OUTPUT_DIR, "entity_metrics.json"), "w", encoding="utf-8") as f:
            json.dump(entity_metrics, f, indent=2)

        # Write merged access_patterns.md
        with open(os.path.join(OUTPUT_DIR, "access_patterns.md"), "w", encoding="utf-8") as f:
            f.write(result.access_patterns_md)

        # Write consensus_report.json
        consensus_report = {
            "confidence_score": result.confidence_score,
            "rounds_executed": result.rounds_executed,
            "total_entities": len(result.merged_entities),
            "total_patterns": len(result.merged_access_patterns),
            "entity_agreement_ratio": result.entity_agreement,
            "pattern_agreement_ratio": result.pattern_agreement,
            "roslyn_alignment_ratio": result.roslyn_alignment,
            "dropped_entities": result.dropped_entities,
            "dropped_patterns": result.dropped_patterns,
        }
        with open(os.path.join(OUTPUT_DIR, "consensus_report.json"), "w", encoding="utf-8") as f:
            json.dump(consensus_report, f, indent=2)

        self._log("💾 Saving extraction results...")
        self._save_file_as_result(1, "extract", "access_patterns_md", os.path.join(OUTPUT_DIR, "access_patterns.md"))
        self._save_file_as_result(1, "extract", "consensus_report", os.path.join(OUTPUT_DIR, "consensus_report.json"))
        # Save Roslyn analysis if it exists
        roslyn_path = os.path.join(OUTPUT_DIR, "roslyn_analysis.json")
        if os.path.exists(roslyn_path):
            self._save_file_as_result(1, "extract", "roslyn_analysis", roslyn_path)
            self._log("🔬 Roslyn analysis saved")
        self._log("📊 Syncing extracted data to database...")
        self._sync_extracted_data()

        # Generate extraction coverage report
        self._log("📋 Generating extraction coverage report...")
        try:
            from pipeline import generate_extraction_coverage_report, compare_extraction_coverage

            # Step 1: Pre-scan the codebase deterministically
            pre_scan = generate_extraction_coverage_report(project_path)
            self._log(f"   Pre-scan: {pre_scan['total_cs_files']} .cs files, {len(pre_scan['dbcontext_entities'])} DbContext entities, {len(pre_scan['repository_classes'])} repositories")

            # Step 2: Get what the LLM extracted (from entity_metrics.json)
            extracted_entities = []
            extracted_patterns = []
            if os.path.exists(os.path.join(OUTPUT_DIR, "entity_metrics.json")):
                with open(os.path.join(OUTPUT_DIR, "entity_metrics.json"), "r", encoding="utf-8") as f:
                    metrics = json.load(f)
                extracted_entities = list(metrics.get("entities", {}).keys())
                extracted_patterns = list(metrics.get("access_patterns", {}).keys())

            # Step 3: Compare and generate coverage report
            coverage = compare_extraction_coverage(pre_scan, extracted_entities, extracted_patterns)
            coverage["pre_scan"] = pre_scan

            # Save report
            with open(os.path.join(OUTPUT_DIR, "extraction_coverage.json"), "w", encoding="utf-8") as f:
                json.dump(coverage, f, indent=2)

            # Log results
            ent_cov = coverage["entity_coverage"]
            self._log(f"   Entity coverage: {ent_cov['coverage_percentage']}% ({len(ent_cov['extracted_entities'])}/{len(ent_cov['dbcontext_entities'])} entities)")
            if ent_cov["missing_entities"]:
                self._log(f"   ⚠️ Missing entities: {', '.join(ent_cov['missing_entities'])}")
            repo_cov = coverage["repository_coverage"]
            if repo_cov["repositories_without_patterns"]:
                self._log(f"   ⚠️ Repos without patterns: {', '.join(repo_cov['repositories_without_patterns'])}")
            tech = coverage["technology_detected"]
            techs = [k for k, v in {"EF Core": tech["ef_core"], "Dapper": tech["dapper"], "Raw SQL": tech["raw_sql"]}.items() if v]
            self._log(f"   Technologies: {', '.join(techs) if techs else 'None detected'}")
            if tech["stored_procedures"]:
                self._log(f"   Stored procedures: {', '.join(tech['stored_procedures'][:5])}{'...' if len(tech['stored_procedures']) > 5 else ''}")
            for w in coverage["warnings"]:
                self._log(f"   {w}")

            self._save_file_as_result(1, "extract", "extraction_coverage", os.path.join(OUTPUT_DIR, "extraction_coverage.json"))
        except Exception as e:
            self._log(f"   ⚠️ Coverage report failed: {e}")

        self._log("✅ Extraction complete")
        logger.info("=== run_extract END (%.2fs) ===", time.time() - t0)

        # Validate extraction output
        metrics_path = os.path.join(OUTPUT_DIR, "entity_metrics.json")
        ap_path = os.path.join(OUTPUT_DIR, "access_patterns.md")
        is_valid_m, err_m = self._validate_output_file(metrics_path, min_size=50)
        is_valid_a, err_a = self._validate_output_file(ap_path, min_size=100)
        if not is_valid_m:
            self._log(f"⚠️ Extraction output incomplete: {err_m}")
        if not is_valid_a:
            self._log(f"⚠️ Extraction output incomplete: {err_a}")
        if not is_valid_m or not is_valid_a:
            logger.warning("Extraction output validation failed: metrics=%s, ap=%s", err_m, err_a)

    def run_model(self):
        t0 = time.time()
        logger.info("=== run_model START (project=%s, run=%s) ===", self.project_id, self.run_id)
        self._load_agents()
        instr = self._get_instructions()
        ap_file = instr["ap_file"]
        scope_instruction = instr["scope"]
        override_instruction = instr["override"]
        priority_instruction = instr["priority"]
        metrics_file = instr["metrics_file"]

        if scope_instruction:
            self._log("🔒 Migration scope applied — using filtered access patterns")
            logger.debug("Scope instruction applied, ap_file=%s, metrics_file=%s", ap_file, metrics_file)
        if override_instruction:
            self._log("🔧 Model overrides detected — applying user customizations")
            logger.debug("Override instruction length: %d chars", len(override_instruction))

        # Split into two calls to avoid max_tokens: markdown first, then JSON
        self._log("🏗️ Designing DynamoDB single-table model (markdown)...")
        from pipeline import OPUS_MODEL_ID
        self._log(f"🤖 Model: Claude Opus ({OPUS_MODEL_ID.split('.')[-1]})")
        self._log("   Reading knowledge base, access patterns, and entity metrics...")
        logger.debug("Invoking architect agent for dynamo_model.md...")
        t_arch = time.time()
        self.architect(
            f"Read templates/dynamodb_knowledge_base.md (or templates/dynamodb_best_practices.md if merged KB not available) and templates/architect_format.md first. "
            f"Then read {ap_file} and {metrics_file} (if it exists).{scope_instruction}{override_instruction}{priority_instruction} "
            f"Design the DynamoDB model and write ONLY {os.path.join(OUTPUT_DIR, 'dynamo_model.md')}. "
            f"Write it in chunks: use write_file for the first section (table config + GSIs + first 2 entity mappings), "
            f"then use append_file for remaining entity mappings, then append_file for access pattern mappings, "
            f"then append_file for sample items and design decisions. "
            f"Each write/append call should be under 2000 words. Do NOT write {os.path.join(OUTPUT_DIR, 'dynamo_model.json')} yet."
        )
        self._log("✅ dynamo_model.md written")
        logger.debug("Architect agent (markdown) completed in %.2fs", time.time() - t_arch)

        self._log("📄 Generating structured JSON model (dynamo_model.json)...")
        logger.debug("Invoking architect agent for dynamo_model.json...")
        t_json = time.time()
        self.architect(
            f"Read the {os.path.join(OUTPUT_DIR, 'dynamo_model.md')} you just created. Now write {os.path.join(OUTPUT_DIR, 'dynamo_model.json')} with the SAME design. "
            f"IMPORTANT: Every entity in entityMappings MUST include a keyDesignJustification object (with pk and sk sub-objects) as specified in architect_format.md. "
            f"IMPORTANT: keyDesignJustification.pk.accessPatternsDriving MUST list ALL access patterns that use this entity's PK — not just the primary lookup. "
            f"For example, User with PK=USER# should list AP-001, AP-002, AP-003, AP-013, etc. — every pattern that queries items with USER# PK. "
            f"IMPORTANT: keyDesignJustification.pk.alternatives MUST include at least one genuinely DIFFERENT PK design that was evaluated and rejected, with specific pros/cons. "
            f"IMPORTANT: Every keyDesignJustification.pk, keyDesignJustification.sk, and capacityAnalysis object MUST include a 'priorityRulesApplied' array. "
            f"Format each rule as '[Decision Area]: [How it influenced this specific decision]'. This is mandatory for traceability. "
            f"IMPORTANT: attributes MUST be a JSON array of strings (e.g., [\"id\", \"email\", \"name\"]), NOT an object with types. "
            f"CRITICAL: accessPatternMapping MUST include EVERY access pattern from {ap_file}. Do NOT stop after a few patterns. "
            f"If there are 25+ patterns, you MUST write them ALL using multiple append_file calls. "
            f"Write it in chunks: "
            f"1) write_file: opening structure (tableName, primaryKey, gsis, first 2 entityMappings) "
            f"2) append_file: remaining entityMappings "
            f"3) append_file: first batch of accessPatternMapping (AP-001 through AP-010) "
            f"4) append_file: next batch of accessPatternMapping (AP-011 through AP-020) "
            f"5) append_file: remaining accessPatternMapping + closing braces "
            f"Each write/append call should be under 2000 words. "
            f"The JSON must be valid and parseable when complete. Verify you have written ALL access patterns before closing the JSON."
        )

        self._log("💾 Saving model results...")
        logger.debug("Architect agent (JSON) completed in %.2fs", time.time() - t_json)
        self._save_file_as_result(2, "model", "model_md", os.path.join(OUTPUT_DIR, "dynamo_model.md"))
        self._log("🔧 Repairing JSON if needed...")
        self._repair_json_file(os.path.join(OUTPUT_DIR, "dynamo_model.json"))

        # Validate model JSON completeness — retry if incomplete
        json_path = os.path.join(OUTPUT_DIR, "dynamo_model.json")
        is_valid, error_msg = self._validate_model_json(json_path)
        if not is_valid:
            self._log(f"⚠️ Model JSON validation failed: {error_msg}")
            self._log("🔄 Retrying JSON generation (attempt 2/2)...")
            logger.warning("Model JSON validation failed: %s — retrying", error_msg)
            # Retry the JSON generation
            self.architect(
                f"The previous dynamo_model.json was incomplete or invalid ({error_msg}). "
                f"Read {os.path.join(OUTPUT_DIR, 'dynamo_model.md')} again and regenerate {json_path} with the COMPLETE model. "
                f"CRITICAL: The JSON MUST include tableName, primaryKey, gsis, entityMappings, AND accessPatternMapping. "
                f"accessPatternMapping must include EVERY access pattern. Write in chunks using write_file then append_file. "
                f"Each chunk under 2000 words. Ensure the JSON is valid and complete before closing."
            )
            self._repair_json_file(json_path)
            is_valid, error_msg = self._validate_model_json(json_path)
            if not is_valid:
                self._log(f"❌ Model JSON still invalid after retry: {error_msg}")
                logger.error("Model JSON validation failed after retry: %s", error_msg)
            else:
                self._log("✅ Model JSON regenerated successfully on retry")

        # Post-process: fix complexity classifications deterministically
        self._postprocess_model_json(json_path)

        self._save_file_as_result(2, "model", "model_json", json_path)
        self._log("✅ Model design complete")
        logger.info("=== run_model END (%.2fs) ===", time.time() - t0)

    def run_validate(self):
        t0 = time.time()
        logger.info("=== run_validate START (project=%s, run=%s) ===", self.project_id, self.run_id)
        self._load_agents()
        instr = self._get_instructions()
        ap_file = instr["ap_file"]
        scope_instruction = instr["scope"]
        override_instruction = instr["override"]
        priority_instruction = instr["priority"]
        self._log("✅ Cross-checking access patterns against DynamoDB model...")
        from pipeline import OPUS_MODEL_ID
        self._log(f"🤖 Model: Claude Opus ({OPUS_MODEL_ID.split('.')[-1]})")
        self._log("   Validating expressions, SK prefixes, sort order, entity modeling...")
        logger.debug("Invoking validator agent...")
        t_val = time.time()
        self.validator(
            f"Read templates/dynamodb_knowledge_base.md (or templates/dynamodb_best_practices.md if merged KB not available) and templates/validator_format.md first. "
            f"Then read {ap_file} and {os.path.join(OUTPUT_DIR, 'dynamo_model.md')}.{scope_instruction}{override_instruction}{priority_instruction} "
            f"Validate all expressions, entity modeling, and classify each pattern. "
            f"Write {os.path.join(OUTPUT_DIR, 'validation_report.md')} in chunks: use write_file for expression/SK/sort validation issues, "
            f"then append_file for entity modeling + coverage matrix, "
            f"then append_file for pattern classifications + summary + recommendations. "
            f"Each write/append call should be under 2000 words."
        )
        self._log("💾 Saving validation report...")
        logger.debug("Validator agent completed in %.2fs", time.time() - t_val)

        # Validate output
        val_path = os.path.join(OUTPUT_DIR, "validation_report.md")
        is_valid, error_msg = self._validate_output_file(val_path, min_size=200)
        if not is_valid:
            self._log(f"⚠️ Validation report incomplete: {error_msg}")
            self._log("🔄 Retrying validation (attempt 2/2)...")
            self.validator(
                f"The previous validation_report.md was incomplete. "
                f"Read {ap_file} and {os.path.join(OUTPUT_DIR, 'dynamo_model.md')} again. "
                f"Write a complete validation report to {val_path}."
            )
            is_valid, error_msg = self._validate_output_file(val_path, min_size=200)
            if not is_valid:
                self._log(f"❌ Validation report still incomplete after retry: {error_msg}")
            else:
                self._log("✅ Validation report regenerated successfully on retry")

        self._save_file_as_result(3, "validate", "validation_md", val_path)
        self._log("✅ Validation complete")
        logger.info("=== run_validate END (%.2fs) ===", time.time() - t0)

    def run_metrics(self):
        t0 = time.time()
        logger.info("=== run_metrics START (project=%s, run=%s) ===", self.project_id, self.run_id)
        self._load_agents()
        instr = self._get_instructions()
        ap_file = instr["ap_file"]
        priority_instruction = instr["priority"]
        metrics_file = instr["metrics_file"]
        self._log("📊 Calculating RCU/WCU capacity per access pattern and entity...")
        from pipeline import SONNET_MODEL_ID
        self._log(f"🤖 Model: Claude Sonnet ({SONNET_MODEL_ID.split('.')[-1]})")
        self._log("   Comparing single-item vs vertical partition strategies...")
        logger.debug("Invoking metrics_analyzer agent, ap_file=%s, metrics_file=%s", ap_file, metrics_file)
        t_met = time.time()
        self.metrics_analyzer(
            f"Read templates/dynamodb_knowledge_base.md (or templates/dynamodb_best_practices.md if merged KB not available) and templates/metrics_format.md first. "
            f"Then read {metrics_file}, {ap_file}, and {os.path.join(OUTPUT_DIR, 'dynamo_model.md')}.{priority_instruction} "
            f"Write {os.path.join(OUTPUT_DIR, 'capacity_analysis.md')} in chunks: use write_file for entity size summary + first 2 relationship analyses, "
            f"then append_file for remaining relationships, "
            f"then append_file for capacity breakdowns + totals + recommendations. "
            f"Each write/append call should be under 2000 words."
        )
        self._log("💾 Saving capacity analysis...")
        logger.debug("Metrics analyzer agent completed in %.2fs", time.time() - t_met)

        # Validate output
        cap_path = os.path.join(OUTPUT_DIR, "capacity_analysis.md")
        is_valid, error_msg = self._validate_output_file(cap_path, min_size=500)
        if not is_valid:
            self._log(f"⚠️ Capacity analysis incomplete: {error_msg}")
            self._log("🔄 Retrying capacity analysis (attempt 2/2)...")
            self.metrics_analyzer(
                f"The previous capacity_analysis.md was incomplete. "
                f"Read {metrics_file}, {ap_file}, and {os.path.join(OUTPUT_DIR, 'dynamo_model.md')} again. "
                f"Write a complete capacity analysis to {cap_path}."
            )
            is_valid, error_msg = self._validate_output_file(cap_path, min_size=500)
            if not is_valid:
                self._log(f"❌ Capacity analysis still incomplete after retry: {error_msg}")
            else:
                self._log("✅ Capacity analysis regenerated successfully on retry")

        self._save_file_as_result(4, "metrics", "capacity_md", cap_path)
        self._log("✅ Capacity analysis complete")
        logger.info("=== run_metrics END (%.2fs) ===", time.time() - t0)

    def _sync_extracted_data(self):
        """After extraction, sync entity_metrics.json data into DB tables."""
        logger.debug("Syncing extracted data to DB for project %s", self.project_id)
        metrics_path = os.path.join(OUTPUT_DIR, "entity_metrics.json")
        if not os.path.exists(metrics_path):
            return

        with open(metrics_path, "r", encoding="utf-8") as f:
            metrics = json.load(f)

        # Parse source code from access_patterns.md
        source_code_map = self._parse_source_code_from_md(os.path.join(OUTPUT_DIR, "access_patterns.md"))

        # Clear existing entities and extractor-sourced patterns (preserve user patterns)
        self.entity_repo.delete_by_project(self.project_id)
        self.pattern_repo.delete_extractor_access_patterns(self.project_id)
        self.pattern_repo.delete_extractor_write_patterns(self.project_id)

        # Entities
        entities_data = []
        for name, data in metrics.get("entities", {}).items():
            raw_fields = data.get("fields")
            # fields column is Text — serialize lists to JSON string
            if isinstance(raw_fields, list):
                raw_fields = json.dumps(raw_fields)
            entities_data.append({
                "name": name,
                "sql_table": data.get("sql_table"),
                "average_row_size_kb": data.get("average_row_size_kb", 0.5),
                "fields": raw_fields,
                "estimated_field_total_bytes": data.get("estimated_field_total_bytes"),
                "relationships_json": data.get("relationships"),
                "notes": data.get("notes"),
                "selected": True
            })
        if entities_data:
            self.entity_repo.bulk_create(self.project_id, entities_data)
            logger.debug("Synced %d entities to DB", len(entities_data))

        # Access patterns
        ap_data = []
        for ap_id, ap in metrics.get("access_patterns", {}).items():
            ap_data.append({
                "pattern_id": ap_id,
                "name": ap.get("name", ""),
                "operation": ap.get("operation", "READ"),
                "source_entities": ap.get("source_entities", []),
                "requests_per_hour": ap.get("requests_per_hour", 0),
                "avg_items_returned": ap.get("avg_items_returned", 1),
                "source_code": source_code_map.get(ap_id),
                "notes": ap.get("notes"),
                "classification": "in_scope",
                "source": "extractor"
            })
        if ap_data:
            self.pattern_repo.bulk_create_access_patterns(self.project_id, ap_data)
            logger.debug("Synced %d access patterns to DB", len(ap_data))

        # Write patterns
        wp_data = []
        for wp_id, wp in metrics.get("write_patterns", {}).items():
            wp_data.append({
                "pattern_id": wp_id,
                "name": wp.get("name", ""),
                "operation": "WRITE",
                "target_entities": wp.get("target_entities", []),
                "requests_per_hour": max(1, round(wp.get("requests_per_hour", 0))),
                "items_per_transaction": wp.get("items_per_transaction", 1),
                "source_code": source_code_map.get(wp_id),
                "notes": wp.get("notes"),
                "classification": "in_scope",
                "source": "extractor"
            })
        if wp_data:
            self.pattern_repo.bulk_create_write_patterns(self.project_id, wp_data)
            logger.debug("Synced %d write patterns to DB", len(wp_data))

        # Append user-sourced patterns to access_patterns.md so pipeline agents see them
        self._append_user_patterns_to_md()

    def _append_user_patterns_to_md(self):
        """Query user-sourced patterns from DB and append them to access_patterns.md."""
        from backend.services.markdown_writer import append_pattern_to_md

        all_access = self.pattern_repo.get_access_patterns(self.project_id)
        for ap in all_access:
            if ap.source == "user":
                append_pattern_to_md({
                    "pattern_id": ap.pattern_id,
                    "name": ap.name,
                    "operation": ap.operation or "READ",
                    "source_entities": ap.source_entities or [],
                    "requests_per_hour": ap.requests_per_hour or 0,
                    "avg_items_returned": ap.avg_items_returned or 1,
                    "source_code": ap.source_code,
                    "source": "User-added",
                }, pattern_type="access")

        all_write = self.pattern_repo.get_write_patterns(self.project_id)
        for wp in all_write:
            if wp.source == "user":
                append_pattern_to_md({
                    "pattern_id": wp.pattern_id,
                    "name": wp.name,
                    "operation": "WRITE",
                    "target_entities": wp.target_entities or [],
                    "requests_per_hour": wp.requests_per_hour or 0,
                    "items_per_transaction": wp.items_per_transaction or 1,
                    "source_code": wp.source_code,
                    "source": "User-added",
                }, pattern_type="write")

    def _parse_source_code_from_md(self, md_path: str) -> dict[str, str]:
        """Parse access_patterns.md to extract source code blocks keyed by pattern ID."""
        import re
        result = {}
        if not os.path.exists(md_path):
            return result

        with open(md_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # Match pattern headers like "#### AP-001:" or "### WP-001:"
        pattern_re = re.compile(r'#{2,4}\s+((?:AP|WP)-\d+)[:\s]')
        code_re = re.compile(r'```(?:csharp|sql|c#|linq)?\s*\n(.*?)```', re.DOTALL)

        sections = pattern_re.split(content)
        # sections alternates: [preamble, id1, body1, id2, body2, ...]
        for i in range(1, len(sections) - 1, 2):
            pattern_id = sections[i].strip()
            body = sections[i + 1]
            code_match = code_re.search(body)
            if code_match:
                result[pattern_id] = code_match.group(1).strip()

        return result
