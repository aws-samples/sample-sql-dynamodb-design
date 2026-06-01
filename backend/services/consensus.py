"""
Consensus extraction module.

Provides multi-run LLM extraction with cross-run comparison,
Roslyn baseline alignment, confidence scoring, and result merging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ExtractionOutput:
    """Output from a single LLM extraction run."""

    entities: dict[str, dict] = field(default_factory=dict)
    """entity_name -> {fields, sql_table, relationships, ...}"""

    access_patterns: dict[str, dict] = field(default_factory=dict)
    """pattern_id -> {name, operation, source_entities, ...}"""

    write_patterns: dict[str, dict] = field(default_factory=dict)
    """pattern_id -> {name, target_entities, ...}"""

    raw_entity_metrics: dict = field(default_factory=dict)
    """Full entity_metrics.json content."""

    raw_access_patterns_md: str = ""
    """Full access_patterns.md content."""


@dataclass
class RoslynOutput:
    """Output from the Roslyn analyzer."""

    entity_names: set[str] = field(default_factory=set)
    entity_fields: dict[str, list[str]] = field(default_factory=dict)
    """entity_name -> [field_names]"""

    relationships: dict[str, list[dict]] = field(default_factory=dict)
    access_methods: list[dict] = field(default_factory=list)


@dataclass
class ComparisonResult:
    """Result of comparing extraction outputs."""

    entity_agreement: float = 0.0
    """Ratio of entities agreed by ≥2/3 LLM runs."""

    pattern_agreement: float = 0.0
    """Ratio of patterns agreed by ≥2/3 LLM runs."""

    roslyn_alignment: float = 0.0
    """Ratio of LLM entities also in Roslyn."""

    overall_score: float = 0.0
    """Weighted confidence score."""

    agreed_entities: set[str] = field(default_factory=set)
    agreed_patterns: set[str] = field(default_factory=set)
    disagreed_entities: set[str] = field(default_factory=set)
    disagreed_patterns: set[str] = field(default_factory=set)


@dataclass
class ConsensusResult:
    """Final result of the consensus extraction process."""

    merged_entities: dict[str, dict] = field(default_factory=dict)
    merged_access_patterns: dict[str, dict] = field(default_factory=dict)
    merged_write_patterns: dict[str, dict] = field(default_factory=dict)
    confidence_score: float = 0.0
    rounds_executed: int = 0
    entity_agreement: float = 0.0
    pattern_agreement: float = 0.0
    roslyn_alignment: float = 0.0
    dropped_entities: list[str] = field(default_factory=list)
    dropped_patterns: list[str] = field(default_factory=list)
    access_patterns_md: str = ""
    """Merged markdown content."""


@dataclass
class MergedResult:
    """Output of the ResultMerger."""

    entity_metrics: dict = field(default_factory=dict)
    """Full entity_metrics.json structure."""

    access_patterns_md: str = ""
    """Merged access_patterns.md content."""

    dropped_entities: list[str] = field(default_factory=list)
    dropped_patterns: list[str] = field(default_factory=list)


class ResultMerger:
    """Merges multiple extraction outputs into a single result."""

    @staticmethod
    def merge(
        llm_outputs: list[ExtractionOutput],
        roslyn_output: RoslynOutput | None,
        all_round_outputs: list[list[ExtractionOutput]],
    ) -> MergedResult:
        """Produce merged entity_metrics and access_patterns.

        Flattens all_round_outputs for cross-round evidence accumulation,
        then merges entities and patterns. The returned entity_metrics dict
        matches the existing entity_metrics.json schema so downstream steps
        require no changes.
        """
        # 1. Flatten all round outputs into a single list for cross-round evidence
        all_outputs: list[ExtractionOutput] = [
            output
            for round_outputs in all_round_outputs
            for output in round_outputs
        ]

        # 2. Merge entities and patterns using the full cross-round evidence
        merged_entities, dropped_entities = ResultMerger._merge_entities(
            all_outputs, roslyn_output
        )
        merged_access, merged_write, dropped_patterns, access_patterns_md = (
            ResultMerger._merge_patterns(all_outputs)
        )

        # 3. Build entity_metrics dict in existing schema format
        entity_metrics = {
            "entities": merged_entities,
            "access_patterns": merged_access,
            "write_patterns": merged_write,
        }

        # 4. Return MergedResult
        return MergedResult(
            entity_metrics=entity_metrics,
            access_patterns_md=access_patterns_md,
            dropped_entities=dropped_entities,
            dropped_patterns=dropped_patterns,
        )

    @staticmethod
    def _merge_patterns(
        llm_outputs: list[ExtractionOutput],
    ) -> tuple[dict[str, dict], dict[str, dict], list[str], str]:
        """Merge access patterns and write patterns from multiple LLM outputs.

        Inclusion rule: pattern included if it appears in ≥2 LLM runs.

        Returns:
            (merged_access_patterns, merged_write_patterns, dropped_patterns, access_patterns_md)
        """
        from collections import Counter

        # 1. Count access pattern ID occurrences across LLM outputs
        access_counts: Counter[str] = Counter()
        for output in llm_outputs:
            for pid in output.access_patterns:
                access_counts[pid] += 1

        # 2. Determine included / dropped access patterns (≥2 threshold)
        all_access_ids = set(access_counts.keys())
        included_access = {pid for pid, cnt in access_counts.items() if cnt >= 2}
        dropped_access = sorted(all_access_ids - included_access)

        # 3. Build merged access patterns using data from first output that has it
        merged_access: dict[str, dict] = {}
        for pid in included_access:
            for output in llm_outputs:
                if pid in output.access_patterns:
                    merged_access[pid] = dict(output.access_patterns[pid])
                    break

        # 4. Count write pattern key occurrences and merge (same ≥2 rule)
        write_counts: Counter[str] = Counter()
        for output in llm_outputs:
            for wid in output.write_patterns:
                write_counts[wid] += 1

        included_write = {wid for wid, cnt in write_counts.items() if cnt >= 2}

        merged_write: dict[str, dict] = {}
        for wid in included_write:
            for output in llm_outputs:
                if wid in output.write_patterns:
                    merged_write[wid] = dict(output.write_patterns[wid])
                    break

        # 5. access_patterns_md: use raw_access_patterns_md from first output with non-empty content
        access_patterns_md = ""
        for output in llm_outputs:
            if output.raw_access_patterns_md:
                access_patterns_md = output.raw_access_patterns_md
                break

        return merged_access, merged_write, dropped_access, access_patterns_md

    @staticmethod
    def _merge_entities(
        llm_outputs: list[ExtractionOutput],
        roslyn_output: RoslynOutput | None,
    ) -> tuple[dict[str, dict], list[str]]:
        """Merge entities from multiple LLM outputs and Roslyn baseline.

        Inclusion rule:
        - If Roslyn baseline is available: entity included ONLY if it appears in Roslyn output.
          LLM-only entities are dropped (prevents hallucinated entities).
        - If Roslyn baseline is NOT available: entity included if it appears in ≥2 LLM runs.
        Field resolution: prefer Roslyn field list when available, otherwise majority LLM field list.

        Returns:
            (merged_entities, dropped_entities)
            merged_entities: dict of entity_name -> entity data dict
            dropped_entities: sorted list of entity names that were excluded
        """
        from collections import Counter

        # 1. Count entity occurrences across LLM outputs
        entity_counts: Counter[str] = Counter()
        for output in llm_outputs:
            for name in output.entities:
                entity_counts[name] += 1

        # 2. Collect all unique entity names
        all_entity_names = set(entity_counts.keys())

        # 3. Determine included entities based on Roslyn availability
        roslyn_entity_names = (
            roslyn_output.entity_names if roslyn_output is not None else set()
        )

        if roslyn_entity_names:
            # Roslyn baseline available — ONLY include entities confirmed by Roslyn.
            # This prevents LLM hallucinations (e.g., ViewModels, DTOs, DbContext classes).
            included = roslyn_entity_names
            logger.debug(
                "Entity filter: Roslyn-only mode — %d Roslyn entities, dropping %d LLM-only entities",
                len(roslyn_entity_names),
                len(all_entity_names - roslyn_entity_names),
            )
        else:
            # No Roslyn baseline — fall back to ≥2 LLM agreement
            included = {
                name for name in all_entity_names if entity_counts[name] >= 2
            }

        # 4. Determine dropped entities: appeared in LLM outputs but not included
        dropped = sorted(all_entity_names - included)

        # 5. Build merged entity data for each included entity
        merged_entities: dict[str, dict] = {}
        for name in included:
            # Start with base data from the first LLM output that contains this entity
            base_data: dict = {}
            for output in llm_outputs:
                if name in output.entities:
                    base_data = dict(output.entities[name])
                    break

            # Field resolution: prefer Roslyn fields when available
            if (
                roslyn_output is not None
                and name in roslyn_output.entity_fields
            ):
                base_data["fields"] = list(roslyn_output.entity_fields[name])
            else:
                # Use majority field list from LLM outputs
                field_lists: list[tuple[str, ...]] = []
                for output in llm_outputs:
                    if name in output.entities:
                        entity_data = output.entities[name]
                        fields = entity_data.get("fields")
                        if fields is not None:
                            field_lists.append(tuple(fields))

                if field_lists:
                    # Find the most common field list
                    field_counter: Counter[tuple[str, ...]] = Counter(field_lists)
                    majority_fields = field_counter.most_common(1)[0][0]
                    base_data["fields"] = list(majority_fields)

            merged_entities[name] = base_data

        return merged_entities, dropped


class ConsensusComparer:
    """Compares extraction outputs and computes confidence score."""

    @staticmethod
    def _entity_agreement(
        llm_outputs: list[ExtractionOutput],
    ) -> tuple[float, set[str], set[str]]:
        """Calculate entity agreement across LLM outputs.

        An entity is "agreed" if its name appears in at least 2 of the
        provided outputs.  For the 2-run case (one failure) both runs
        must contain the entity for it to count as agreed.

        Returns:
            (ratio, agreed_entities, disagreed_entities)
            ratio is 1.0 when there are no entities at all.
        """
        from collections import Counter

        counts: Counter[str] = Counter()
        for output in llm_outputs:
            for name in output.entities:
                counts[name] += 1

        all_entities = set(counts.keys())
        if not all_entities:
            return 1.0, set(), set()

        agreed = {name for name, cnt in counts.items() if cnt >= 2}
        disagreed = all_entities - agreed

        ratio = len(agreed) / len(all_entities)
        return ratio, agreed, disagreed

    @staticmethod
    def _pattern_agreement(
        llm_outputs: list[ExtractionOutput],
    ) -> tuple[float, set[str], set[str]]:
        """Calculate pattern agreement across LLM outputs.

        A pattern is "agreed" if its ID appears in at least 2 of the
        provided outputs.  For the 2-run case (one failure) both runs
        must contain the pattern for it to count as agreed.

        Returns:
            (ratio, agreed_patterns, disagreed_patterns)
            ratio is 1.0 when there are no patterns at all.
        """
        from collections import Counter

        counts: Counter[str] = Counter()
        for output in llm_outputs:
            for pid in output.access_patterns:
                counts[pid] += 1

        all_patterns = set(counts.keys())
        if not all_patterns:
            return 1.0, set(), set()

        agreed = {pid for pid, cnt in counts.items() if cnt >= 2}
        disagreed = all_patterns - agreed

        ratio = len(agreed) / len(all_patterns)
        return ratio, agreed, disagreed

    @staticmethod
    def compare(
        llm_outputs: list[ExtractionOutput],
        roslyn_output: RoslynOutput | None,
    ) -> ComparisonResult:
        """Compare LLM outputs against each other and Roslyn baseline."""
        logger.debug("Comparing %d LLM outputs (roslyn=%s)", len(llm_outputs), roslyn_output is not None)
        entity_agreement, agreed_entities, disagreed_entities = (
            ConsensusComparer._entity_agreement(llm_outputs)
        )
        pattern_agreement, agreed_patterns, disagreed_patterns = (
            ConsensusComparer._pattern_agreement(llm_outputs)
        )

        # Roslyn alignment: ratio of agreed entities also in Roslyn
        if roslyn_output is None:
            roslyn_alignment = entity_agreement
        elif not agreed_entities:
            roslyn_alignment = 1.0
        else:
            roslyn_alignment = (
                len(agreed_entities & roslyn_output.entity_names)
                / len(agreed_entities)
            )

        overall_score = ConsensusComparer.compute_confidence(
            entity_agreement, pattern_agreement, roslyn_alignment
        )

        logger.debug(
            "Comparison result: entity_agreement=%.2f (%d agreed, %d disagreed), "
            "pattern_agreement=%.2f (%d agreed, %d disagreed), roslyn_alignment=%.2f, overall=%.2f",
            entity_agreement, len(agreed_entities), len(disagreed_entities),
            pattern_agreement, len(agreed_patterns), len(disagreed_patterns),
            roslyn_alignment, overall_score,
        )
        if disagreed_entities:
            logger.debug("Disagreed entities: %s", sorted(disagreed_entities))
        if disagreed_patterns:
            logger.debug("Disagreed patterns: %s", sorted(disagreed_patterns))

        return ComparisonResult(
            entity_agreement=entity_agreement,
            pattern_agreement=pattern_agreement,
            roslyn_alignment=roslyn_alignment,
            overall_score=overall_score,
            agreed_entities=agreed_entities,
            agreed_patterns=agreed_patterns,
            disagreed_entities=disagreed_entities,
            disagreed_patterns=disagreed_patterns,
        )

    @staticmethod
    def compute_confidence(
        entity_agreement: float,
        pattern_agreement: float,
        roslyn_alignment: float,
    ) -> float:
        """Compute weighted confidence score, clamped to [0, 1].

        Formula: 0.4 * entity_agreement + 0.3 * pattern_agreement + 0.3 * roslyn_alignment
        """
        score = (
            0.4 * entity_agreement
            + 0.3 * pattern_agreement
            + 0.3 * roslyn_alignment
        )
        return max(0.0, min(1.0, score))


class ConsensusExtractor:
    """Orchestrates multi-run consensus extraction with retry logic."""

    def __init__(
        self,
        project_path: str,
        schema_path: str | None,
        agent_factory,  # Callable that returns a fresh agent instance
        roslyn_analyzer_path: str | None,
        log_callback,  # Callable[[str], None]
        threshold: float = 0.7,
        max_rounds: int = 3,
        runs_per_round: int = 3,
    ):
        self.project_path = project_path
        self.schema_path = schema_path
        self.agent_factory = agent_factory
        self.roslyn_analyzer_path = roslyn_analyzer_path
        self.log_callback = log_callback
        self.threshold = threshold
        self.max_rounds = max_rounds
        self.runs_per_round = runs_per_round

    def _log(self, message: str, level: str = "info"):
        """Log a message. level can be 'info' or 'debug'.
        Debug messages only forwarded if strands logger is at DEBUG level."""
        import logging as _logging
        strands_level = _logging.getLogger("strands").level
        if level == "debug" and strands_level > _logging.DEBUG:
            return  # Skip debug messages when not in debug mode
        if self.log_callback:
            self.log_callback(message)

    def _attach_strands_log_handler(self):
        """When strands logger is at DEBUG, attach a handler that forwards to UI."""
        import logging as _logging

        strands_logger = _logging.getLogger("strands")
        if strands_logger.level > _logging.DEBUG:
            return None  # Not in debug mode

        class UILogHandler(_logging.Handler):
            def __init__(self, callback):
                super().__init__()
                self.callback = callback
                self._tool_count = 0

            def emit(self, record):
                try:
                    msg = record.getMessage()
                    name = record.name  # e.g., strands.models.bedrock, strands.event_loop.event_loop

                    # Model invocation
                    if "invoking model" in msg and "bedrock" in name:
                        self.callback(f"   🤖 Calling Bedrock model...")

                    # Model response received
                    elif "finished streaming response" in msg and "bedrock" in name:
                        self.callback(f"   🤖 Model response received")

                    # Tool use — extract tool name from the message
                    elif "tool_use" in msg.lower() or "tooluse" in msg.lower():
                        # Try to extract tool name
                        import re
                        tool_match = re.search(r"name['\"]?\s*[:=]\s*['\"]?(\w+)", msg)
                        if tool_match:
                            tool_name = tool_match.group(1)
                            self._tool_count += 1
                            self.callback(f"   🔧 Tool call #{self._tool_count}: {tool_name}")

                    # Throttling / retry
                    elif "throttling" in msg or "retry_delay" in msg:
                        import re
                        delay_match = re.search(r"retry_delay_seconds=<(\d+)>", msg)
                        delay = delay_match.group(1) if delay_match else "?"
                        self.callback(f"   ⏳ Rate limited — retrying in {delay}s")

                    # Context window management
                    elif "context reduction" in msg or "sliding_window" in msg:
                        self.callback(f"   📝 Managing context window...")

                except Exception:
                    pass

        handler = UILogHandler(self.log_callback)
        handler.setLevel(_logging.DEBUG)
        strands_logger.addHandler(handler)
        return handler

    def _detach_strands_log_handler(self, handler):
        """Remove the UI log handler from strands logger."""
        if handler:
            import logging as _logging
            _logging.getLogger("strands").removeHandler(handler)

    def run(self) -> ConsensusResult:
        """Execute consensus extraction. Returns the final merged result."""
        import concurrent.futures
        import time

        # Attach strands log forwarding if in debug mode
        strands_handler = self._attach_strands_log_handler()

        logger.info("ConsensusExtractor.run() starting: threshold=%.2f, max_rounds=%d, runs_per_round=%d",
                     self.threshold, self.max_rounds, self.runs_per_round)
        t0 = time.time()

        roslyn_output: RoslynOutput | None = None
        all_round_outputs: list[list[ExtractionOutput]] = []
        last_comparison: ComparisonResult | None = None

        for round_num in range(1, self.max_rounds + 1):
            self._log(
                f"🔄 Consensus Round {round_num}/{self.max_rounds} "
                f"— launching {self.runs_per_round} parallel extractions..."
            )

            # Determine max_workers: +1 for Roslyn on first round
            need_roslyn = round_num == 1
            max_workers = self.runs_per_round + (1 if need_roslyn else 0)

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit Roslyn on first round only
                roslyn_future = None
                if need_roslyn:
                    roslyn_future = executor.submit(self._run_roslyn)

                # Submit LLM extraction runs
                llm_futures = [
                    executor.submit(self._run_single_extraction, i, round_num)
                    for i in range(self.runs_per_round)
                ]

                # Collect Roslyn result (first round only)
                if roslyn_future is not None:
                    roslyn_output = roslyn_future.result()
                    if roslyn_output:
                        logger.debug("Roslyn baseline: %d entities, %d access methods",
                                     len(roslyn_output.entity_names), len(roslyn_output.access_methods))
                    else:
                        logger.debug("Roslyn baseline: not available")

                # Collect LLM results, filtering out failures
                llm_results: list[ExtractionOutput] = []
                for idx, future in enumerate(llm_futures):
                    result = future.result()
                    if result is not None:
                        llm_results.append(result)
                    self._log(f"✅ Thread {idx + 1}/{self.runs_per_round} complete")

            # Check minimum run threshold
            if len(llm_results) < 2:
                logger.error("Only %d successful LLM runs in round %d — need at least 2", len(llm_results), round_num)
                raise RuntimeError("Insufficient extraction runs")

            # Compare outputs
            last_comparison = ConsensusComparer.compare(llm_results, roslyn_output)
            all_round_outputs.append(llm_results)

            self._log(
                f"📊 Round {round_num} confidence: "
                f"{last_comparison.overall_score:.0%} "
                f"(threshold: {self.threshold:.0%})"
            )

            # Check if consensus reached
            if last_comparison.overall_score >= self.threshold:
                self._log(
                    f"📊 Round {round_num} confidence: "
                    f"{last_comparison.overall_score:.0%} — consensus reached"
                )
                break

            # Log retry if not last round
            if round_num < self.max_rounds:
                self._log(
                    f"⚠️ Round {round_num} confidence: "
                    f"{last_comparison.overall_score:.0%} — retrying..."
                )

        # Merge using last round outputs + all round data for cross-round evidence
        last_round_outputs = all_round_outputs[-1]
        logger.debug("Merging results: %d rounds total, last round has %d outputs",
                     len(all_round_outputs), len(last_round_outputs))
        merged = ResultMerger.merge(last_round_outputs, roslyn_output, all_round_outputs)

        # Build ConsensusResult
        assert last_comparison is not None
        logger.info("ConsensusExtractor.run() complete in %.2fs — confidence=%.2f, entities=%d, patterns=%d",
                     time.time() - t0, last_comparison.overall_score,
                     len(merged.entity_metrics.get("entities", {})),
                     len(merged.entity_metrics.get("access_patterns", {})))

        # Cleanup strands log handler
        self._detach_strands_log_handler(strands_handler)

        return ConsensusResult(
            merged_entities=merged.entity_metrics.get("entities", {}),
            merged_access_patterns=merged.entity_metrics.get("access_patterns", {}),
            merged_write_patterns=merged.entity_metrics.get("write_patterns", {}),
            confidence_score=last_comparison.overall_score,
            rounds_executed=len(all_round_outputs),
            entity_agreement=last_comparison.entity_agreement,
            pattern_agreement=last_comparison.pattern_agreement,
            roslyn_alignment=last_comparison.roslyn_alignment,
            dropped_entities=merged.dropped_entities,
            dropped_patterns=merged.dropped_patterns,
            access_patterns_md=merged.access_patterns_md,
        )

    def _run_single_extraction(self, run_index: int, round_num: int) -> ExtractionOutput | None:
        """Run a single LLM extraction in its own working directory."""
        import json
        import os
        import re
        import shutil
        import time

        t0 = time.time()
        self._log(f"   🧵 Thread {run_index + 1} (round {round_num}) — starting LLM extraction...", level="debug")
        logger.debug("LLM extraction run %d (round %d) starting...", run_index, round_num)
        temp_dir = f"_consensus_run_{run_index}"
        os.makedirs(temp_dir, exist_ok=True)

        try:
            # Get a fresh agent instance
            agent = self.agent_factory()

            # Build extraction prompt
            schema_instruction = ""
            if self.schema_path and os.path.exists(self.schema_path):
                schema_instruction = (
                    f" IMPORTANT: A SQL schema file is available at '{self.schema_path}'. "
                    f"Read it first using read_file. "
                    f"It contains table DDL, stored procedures, views, and/or triggers. "
                    f"Use this to understand the full database schema."
                )

            prompt = (
                f"Scan the .NET project at {self.project_path} and extract all "
                f"access patterns into access_patterns.md. "
                f"Write all output files to the directory '{temp_dir}'.{schema_instruction}"
            )

            self._log(f"   🧵 Thread {run_index + 1} (round {round_num}) — invoking agent...", level="debug")
            # Invoke the agent
            agent(prompt)
            self._log(f"   🧵 Thread {run_index + 1} (round {round_num}) — agent finished ({time.time() - t0:.1f}s)", level="debug")

            # Look for entity_metrics.json in the temp dir
            metrics_path = os.path.join(temp_dir, "entity_metrics.json")
            if not os.path.exists(metrics_path):
                self._log(f"   ⚠️ Thread {run_index + 1} (round {round_num}): entity_metrics.json not found")
                return None

            # Read and parse JSON, with repair logic
            with open(metrics_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            metrics = None
            try:
                metrics = json.loads(content)
            except json.JSONDecodeError:
                # Attempt repair: remove trailing commas before } or ]
                repaired = re.sub(r',\s*([}\]])', r'\1', content)
                try:
                    metrics = json.loads(repaired)
                    self._log(f"   🔧 Thread {run_index + 1} (round {round_num}): repaired JSON")
                except json.JSONDecodeError:
                    self._log(
                        f"   ⚠️ Thread {run_index + 1} (round {round_num}): "
                        f"entity_metrics.json invalid even after repair"
                    )
                    return None

            # Parse into ExtractionOutput
            entities = metrics.get("entities", {})
            access_patterns = metrics.get("access_patterns", {})
            write_patterns = metrics.get("write_patterns", {})

            self._log(
                f"   📦 Thread {run_index + 1} (round {round_num}): "
                f"{len(entities)} entities, {len(access_patterns)} APs, {len(write_patterns)} WPs "
                f"({time.time() - t0:.1f}s)",
                level="debug"
            )

            logger.debug(
                "LLM extraction run %d (round %d) parsed: %d entities, %d access_patterns, %d write_patterns (%.2fs)",
                run_index, round_num, len(entities), len(access_patterns), len(write_patterns), time.time() - t0,
            )

            # Read access_patterns.md if it exists
            access_md_path = os.path.join(temp_dir, "access_patterns.md")
            raw_access_patterns_md = ""
            if os.path.exists(access_md_path):
                with open(access_md_path, "r", encoding="utf-8", errors="replace") as f:
                    raw_access_patterns_md = f.read()

            return ExtractionOutput(
                entities=entities,
                access_patterns=access_patterns,
                write_patterns=write_patterns,
                raw_entity_metrics=metrics,
                raw_access_patterns_md=raw_access_patterns_md,
            )

        except Exception as e:
            logger.error("LLM extraction run %d (round %d) failed: %s", run_index, round_num, e, exc_info=True)
            self._log(f"   ❌ Thread {run_index + 1} (round {round_num}) failed: {e}")
            return None

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_roslyn(self) -> RoslynOutput | None:
        """Run the Roslyn analyzer once. Returns None on failure."""
        import json
        import os
        import subprocess
        import time

        t0 = time.time()
        self._log("   🔬 Roslyn analyzer starting...", level="debug")
        logger.debug("Roslyn analyzer starting, path=%s", self.roslyn_analyzer_path)

        if self.roslyn_analyzer_path is None or not os.path.exists(
            self.roslyn_analyzer_path
        ):
            self._log("⚠️ Roslyn analyzer not available — proceeding without Roslyn baseline")
            return None

        try:
            output_path = os.path.join("output", "roslyn_analysis.json")

            subprocess.run(
                [
                    "dotnet", "run",
                    "--project", self.roslyn_analyzer_path,
                    "-c", "Release",
                    "--",
                    self.project_path,
                    "--output", output_path,
                ],
                capture_output=True,
                text=True,
                timeout=300,
                encoding="utf-8",
                errors="replace",
            )

            if not os.path.exists(output_path):
                self._log("⚠️ Roslyn analyzer produced no output — proceeding without Roslyn baseline")
                return None

            with open(output_path, "r", encoding="utf-8", errors="replace") as f:
                analysis = json.load(f)

            # Extract into RoslynOutput
            entities_list = analysis.get("entities", [])
            entity_names: set[str] = set()
            entity_fields: dict[str, list[str]] = {}
            relationships: dict[str, list[dict]] = {}

            for entity in entities_list:
                name = entity.get("name", "")
                if name:
                    entity_names.add(name)
                    entity_fields[name] = [
                        f["name"] for f in entity.get("fields", [])
                    ]
                    relationships[name] = entity.get("relationships", [])

            access_methods = analysis.get("accessMethods", [])

            logger.debug("Roslyn analyzer completed in %.2fs: %d entities, %d access methods",
                         time.time() - t0, len(entity_names), len(access_methods))

            self._log(f"   🔬 Roslyn complete: {len(entity_names)} entities, {len(access_methods)} access methods ({time.time() - t0:.1f}s)", level="debug")

            return RoslynOutput(
                entity_names=entity_names,
                entity_fields=entity_fields,
                relationships=relationships,
                access_methods=access_methods,
            )

        except Exception as e:
            logger.error("Roslyn analyzer failed: %s", e, exc_info=True)
            self._log(f"⚠️ Roslyn analyzer failed: {e} — proceeding without Roslyn baseline")
            return None
