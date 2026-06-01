"""Tier 2: LLM extraction consistency tests — requires Bedrock.

Tests the extraction phase output for entity/pattern accuracy and consistency.
"""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from conftest import load_baseline, save_baseline

# Entities that MUST always be extracted (core DB entities)
REQUIRED_ENTITIES = {"User", "Product", "Order", "OrderItem"}

# Entities that should NEVER appear
FORBIDDEN_ENTITY_PATTERNS = [
    "ViewModel", "Response", "Request", "Dto", "DTO",
    "Result", "Details", "Error", "Context", "DbContext",
    "Handler", "Controller", "Service", "Base",
]


@pytest.fixture(scope="module")
def extraction_result(sample_project_path, db_session, aws_profile, validate_aws_credentials):
    """Run the extraction phase and return the results."""
    os.environ["AWS_PROFILE"] = aws_profile

    from backend.db.repositories import ProjectRepository, PipelineRepository
    from backend.services.pipeline_runner import PipelineRunner

    # Create project
    project_repo = ProjectRepository(db_session)
    project = project_repo.create(
        name="Extraction Test",
        path=sample_project_path,
        aws_profile=aws_profile,
    )

    # Create pipeline run
    pipeline_repo = PipelineRepository(db_session)
    run = pipeline_repo.create_run(project_id=project.id, phases_config={"extract": True})

    # Run extraction
    runner = PipelineRunner(db_session, project.id, run.id)
    runner.run_extract()
    runner.close_file_logger()

    # Load results
    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "output")
    results = {}

    for filename in ["entity_metrics.json", "access_patterns.md", "consensus_report.json"]:
        path = os.path.join(output_dir, filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if filename.endswith(".json"):
                results[filename] = json.loads(content)
            else:
                results[filename] = content

    results["project_id"] = project.id
    results["run_id"] = run.id
    return results


class TestExtractionEntities:
    """Validate extracted entities."""

    def test_required_entities_present(self, extraction_result):
        """Core entities are always extracted."""
        entities = set(extraction_result.get("entity_metrics.json", {}).get("entities", {}).keys())
        missing = REQUIRED_ENTITIES - entities
        assert not missing, f"Missing required entities: {missing}"

    def test_no_forbidden_entities(self, extraction_result):
        """No ViewModels, DTOs, or non-DB classes extracted."""
        entities = extraction_result.get("entity_metrics.json", {}).get("entities", {})
        for name in entities:
            for pattern in FORBIDDEN_ENTITY_PATTERNS:
                assert not name.endswith(pattern) and not name.startswith(pattern), (
                    f"Forbidden entity '{name}' matches pattern '{pattern}'"
                )

    def test_entity_count_in_range(self, extraction_result):
        """Entity count is within expected range."""
        count = len(extraction_result.get("entity_metrics.json", {}).get("entities", {}))
        assert 5 <= count <= 12, f"Entity count {count} outside range [5, 12]"

    def test_entities_have_fields(self, extraction_result):
        """Each entity has field information."""
        entities = extraction_result.get("entity_metrics.json", {}).get("entities", {})
        for name, data in entities.items():
            fields = data.get("fields")
            assert fields is not None and fields != "", (
                f"Entity '{name}' has no fields"
            )

    def test_entities_have_size_estimate(self, extraction_result):
        """Each entity has a size estimate."""
        entities = extraction_result.get("entity_metrics.json", {}).get("entities", {})
        for name, data in entities.items():
            size = data.get("average_row_size_kb", 0)
            assert size > 0, f"Entity '{name}' has no size estimate"


class TestExtractionAccessPatterns:
    """Validate extracted access patterns."""

    def test_access_patterns_exist(self, extraction_result):
        """At least some access patterns are extracted."""
        patterns = extraction_result.get("entity_metrics.json", {}).get("access_patterns", {})
        assert len(patterns) >= 3, f"Too few access patterns: {len(patterns)}"

    def test_access_pattern_count_in_range(self, extraction_result):
        """Access pattern count is within expected range."""
        patterns = extraction_result.get("entity_metrics.json", {}).get("access_patterns", {})
        count = len(patterns)
        assert 5 <= count <= 30, f"Access pattern count {count} outside range [5, 30]"

    def test_patterns_have_names(self, extraction_result):
        """Each access pattern has a name."""
        patterns = extraction_result.get("entity_metrics.json", {}).get("access_patterns", {})
        for pid, data in patterns.items():
            assert data.get("name"), f"Pattern {pid} has no name"

    def test_patterns_have_source_entities(self, extraction_result):
        """Each access pattern references at least one entity."""
        patterns = extraction_result.get("entity_metrics.json", {}).get("access_patterns", {})
        for pid, data in patterns.items():
            entities = data.get("source_entities", [])
            assert len(entities) > 0, f"Pattern {pid} has no source entities"

    def test_pattern_ids_sequential(self, extraction_result):
        """Pattern IDs follow AP-NNN format."""
        patterns = extraction_result.get("entity_metrics.json", {}).get("access_patterns", {})
        for pid in patterns:
            assert pid.startswith("AP-"), f"Invalid pattern ID: {pid}"

    def test_no_in_memory_projections_as_patterns(self, extraction_result):
        """In-memory .Select() projections should not be access patterns."""
        md_content = extraction_result.get("access_patterns.md", "")
        # Check for common in-memory projection indicators
        suspicious = [
            "orders.Select(o => new OrderViewModel",
            "basketItems.Select(basketItem =>",
            "items.Select(_mapper.Map",
        ]
        for pattern in suspicious:
            if pattern in md_content:
                # It's OK if it's mentioned as supplementary context, not as a primary AP
                # Check if it's under an AP-NNN header
                lines = md_content.split("\n")
                for i, line in enumerate(lines):
                    if pattern in line:
                        # Look backwards for the nearest AP header
                        for j in range(i, max(0, i - 10), -1):
                            if lines[j].strip().startswith("#### AP-"):
                                pytest.fail(
                                    f"In-memory projection found as access pattern:\n"
                                    f"  Pattern: {lines[j].strip()}\n"
                                    f"  Code: {pattern}"
                                )
                                break


class TestExtractionConsensus:
    """Validate consensus process."""

    def test_confidence_score_above_threshold(self, extraction_result):
        """Consensus confidence score meets threshold."""
        report = extraction_result.get("consensus_report.json", {})
        score = report.get("confidence_score", 0)
        assert score >= 0.7, f"Confidence score {score} below threshold 0.7"

    def test_consensus_report_complete(self, extraction_result):
        """Consensus report has all required fields."""
        report = extraction_result.get("consensus_report.json", {})
        required_fields = ["confidence_score", "rounds_executed", "total_entities", "total_patterns"]
        for field in required_fields:
            assert field in report, f"Missing field in consensus report: {field}"


class TestExtractionOutputFiles:
    """Validate output file creation."""

    def test_entity_metrics_json_exists(self, output_dir):
        """entity_metrics.json is created in output directory."""
        path = os.path.join(output_dir, "entity_metrics.json")
        assert os.path.exists(path), "entity_metrics.json not found"

    def test_access_patterns_md_exists(self, output_dir):
        """access_patterns.md is created in output directory."""
        path = os.path.join(output_dir, "access_patterns.md")
        assert os.path.exists(path), "access_patterns.md not found"

    def test_log_file_created(self):
        """A log file is created for the run."""
        logs_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
        if os.path.isdir(logs_dir):
            log_files = [f for f in os.listdir(logs_dir) if f.endswith(".log")]
            assert len(log_files) > 0, "No log files created"


class TestExtractionBaseline:
    """Compare extraction output against baseline ranges."""

    def test_extraction_baseline_consistency(self, extraction_result, baselines_dir):
        """Extraction output is within baseline ranges."""
        metrics = extraction_result.get("entity_metrics.json", {})
        current = {
            "entity_count": len(metrics.get("entities", {})),
            "entity_names": sorted(metrics.get("entities", {}).keys()),
            "access_pattern_count": len(metrics.get("access_patterns", {})),
            "write_pattern_count": len(metrics.get("write_patterns", {})),
        }

        baseline = load_baseline(baselines_dir, "extraction_baseline")
        if baseline is None:
            save_baseline(baselines_dir, "extraction_baseline", current)
            pytest.skip("Extraction baseline created — re-run to validate")
        else:
            # Entity count within ±2
            assert abs(current["entity_count"] - baseline["entity_count"]) <= 2, (
                f"Entity count drift: {baseline['entity_count']} → {current['entity_count']}"
            )
            # Core entities overlap ≥80%
            baseline_set = set(baseline["entity_names"])
            current_set = set(current["entity_names"])
            overlap = len(baseline_set & current_set) / max(len(baseline_set), 1)
            assert overlap >= 0.8, (
                f"Entity overlap {overlap:.0%} below 80%.\n"
                f"  Missing: {baseline_set - current_set}\n"
                f"  New: {current_set - baseline_set}"
            )
            # Access pattern count within ±3
            assert abs(current["access_pattern_count"] - baseline["access_pattern_count"]) <= 3, (
                f"Access pattern count drift: {baseline['access_pattern_count']} → {current['access_pattern_count']}"
            )
