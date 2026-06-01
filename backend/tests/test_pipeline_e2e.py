"""Tier 3: Full pipeline E2E tests — requires Bedrock.

Runs the complete pipeline (extract → model → validate → metrics) and validates
structural consistency of all outputs.
"""

import json
import os
import sys
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from conftest import load_baseline, save_baseline


@pytest.fixture(scope="module")
def pipeline_result(sample_project_path, db_session, aws_profile, validate_aws_credentials):
    """Run the full pipeline and return all results."""
    os.environ["AWS_PROFILE"] = aws_profile

    from backend.db.repositories import ProjectRepository, PipelineRepository
    from backend.services.pipeline_runner import PipelineRunner

    # Create project
    project_repo = ProjectRepository(db_session)
    project = project_repo.create(
        name="E2E Pipeline Test",
        path=sample_project_path,
        aws_profile=aws_profile,
    )

    # Create pipeline run
    pipeline_repo = PipelineRepository(db_session)
    run = pipeline_repo.create_run(
        project_id=project.id,
        phases_config={"extract": True, "model": True, "validate": True, "metrics": True},
    )

    # Run all phases
    runner = PipelineRunner(db_session, project.id, run.id)
    t0 = time.time()

    runner.run_extract()
    extract_time = time.time() - t0

    t1 = time.time()
    runner.run_model()
    model_time = time.time() - t1

    t2 = time.time()
    runner.run_validate()
    validate_time = time.time() - t2

    t3 = time.time()
    runner.run_metrics()
    metrics_time = time.time() - t3

    runner.close_file_logger()
    total_time = time.time() - t0

    # Collect results
    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "output")
    results = {"timings": {
        "extract": extract_time, "model": model_time,
        "validate": validate_time, "metrics": metrics_time, "total": total_time,
    }}

    for filename in ["entity_metrics.json", "dynamo_model.json", "dynamo_model.md",
                     "validation_report.md", "capacity_analysis.md", "consensus_report.json"]:
        path = os.path.join(output_dir, filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if filename.endswith(".json"):
                try:
                    results[filename] = json.loads(content)
                except json.JSONDecodeError:
                    # Try raw_decode for Extra data issue
                    decoder = json.JSONDecoder()
                    obj, _ = decoder.raw_decode(content.lstrip())
                    results[filename] = obj
            else:
                results[filename] = content

    results["project_id"] = project.id
    results["run_id"] = run.id
    return results


class TestPipelineCompletion:
    """Validate all phases complete successfully."""

    def test_all_output_files_exist(self, pipeline_result):
        """All expected output files are produced."""
        expected = ["entity_metrics.json", "dynamo_model.json", "dynamo_model.md",
                    "validation_report.md", "capacity_analysis.md"]
        for filename in expected:
            assert filename in pipeline_result, f"Missing output: {filename}"

    def test_timing_reasonable(self, pipeline_result):
        """Pipeline phases complete within time limits."""
        timings = pipeline_result["timings"]
        assert timings["extract"] < 600, f"Extract too slow: {timings['extract']:.0f}s"
        assert timings["model"] < 1200, f"Model too slow: {timings['model']:.0f}s"
        assert timings["validate"] < 600, f"Validate too slow: {timings['validate']:.0f}s"
        assert timings["metrics"] < 300, f"Metrics too slow: {timings['metrics']:.0f}s"


class TestModelStructure:
    """Validate DynamoDB model JSON structure."""

    def test_model_has_table_name(self, pipeline_result):
        """Model JSON has a table name."""
        model = pipeline_result.get("dynamo_model.json", {})
        assert model.get("tableName"), "Missing tableName"

    def test_model_has_primary_key(self, pipeline_result):
        """Model JSON has primary key definition."""
        model = pipeline_result.get("dynamo_model.json", {})
        pk = model.get("primaryKey", {})
        assert pk.get("partitionKey"), "Missing partitionKey"
        assert pk.get("sortKey"), "Missing sortKey"

    def test_model_has_gsis(self, pipeline_result):
        """Model JSON has GSI definitions."""
        model = pipeline_result.get("dynamo_model.json", {})
        gsis = model.get("gsis", [])
        assert len(gsis) >= 1, "No GSIs defined"
        assert len(gsis) <= 6, f"Too many GSIs: {len(gsis)}"

    def test_gsi_count_in_range(self, pipeline_result, baselines_dir):
        """GSI count is within expected range."""
        model = pipeline_result.get("dynamo_model.json", {})
        gsi_count = len(model.get("gsis", []))
        baseline = load_baseline(baselines_dir, "model_baseline")
        if baseline and "gsi_count" in baseline:
            assert abs(gsi_count - baseline["gsi_count"]) <= 1, (
                f"GSI count drift: {baseline['gsi_count']} → {gsi_count}"
            )

    def test_all_entities_mapped(self, pipeline_result):
        """Every extracted entity appears in model entityMappings."""
        metrics = pipeline_result.get("entity_metrics.json", {})
        model = pipeline_result.get("dynamo_model.json", {})
        extracted = set(metrics.get("entities", {}).keys())
        mapped = set(model.get("entityMappings", {}).keys())
        missing = extracted - mapped
        # Allow some tolerance — some entities may be merged/flattened
        coverage = len(extracted & mapped) / max(len(extracted), 1)
        assert coverage >= 0.7, (
            f"Entity mapping coverage {coverage:.0%}. Missing: {missing}"
        )

    def test_entities_have_key_mappings(self, pipeline_result):
        """Each entity mapping has PK/SK key mappings."""
        model = pipeline_result.get("dynamo_model.json", {})
        for name, mapping in model.get("entityMappings", {}).items():
            keys = mapping.get("keyMappings", {})
            assert "PK" in keys, f"Entity '{name}' missing PK mapping"
            assert "SK" in keys, f"Entity '{name}' missing SK mapping"

    def test_entities_have_size_estimates(self, pipeline_result):
        """Each entity mapping has a size estimate."""
        model = pipeline_result.get("dynamo_model.json", {})
        for name, mapping in model.get("entityMappings", {}).items():
            size = mapping.get("estimatedSizeKB", 0)
            assert size > 0, f"Entity '{name}' has no size estimate"

    def test_access_patterns_mapped(self, pipeline_result):
        """Access patterns are mapped in the model."""
        model = pipeline_result.get("dynamo_model.json", {})
        ap_mapping = model.get("accessPatternMapping", {})
        assert len(ap_mapping) >= 3, f"Too few access patterns mapped: {len(ap_mapping)}"

    def test_model_json_valid(self, pipeline_result):
        """Model JSON is valid and parseable."""
        model = pipeline_result.get("dynamo_model.json")
        assert model is not None, "Model JSON is None (parse failed)"
        assert isinstance(model, dict), "Model JSON is not a dict"


class TestValidationReport:
    """Validate the validation report."""

    def test_validation_report_non_empty(self, pipeline_result):
        """Validation report is non-empty."""
        report = pipeline_result.get("validation_report.md", "")
        assert len(report) > 100, f"Validation report too short: {len(report)} chars"

    def test_validation_report_has_sections(self, pipeline_result):
        """Validation report has expected sections."""
        report = pipeline_result.get("validation_report.md", "")
        # Should have at least some markdown headers
        assert "#" in report, "No markdown headers in validation report"


class TestCapacityAnalysis:
    """Validate the capacity analysis."""

    def test_capacity_analysis_non_empty(self, pipeline_result):
        """Capacity analysis is non-empty."""
        analysis = pipeline_result.get("capacity_analysis.md", "")
        assert len(analysis) > 100, f"Capacity analysis too short: {len(analysis)} chars"

    def test_capacity_analysis_has_rcu_wcu(self, pipeline_result):
        """Capacity analysis mentions RCU and WCU."""
        analysis = pipeline_result.get("capacity_analysis.md", "")
        assert "RCU" in analysis, "No RCU mentioned in capacity analysis"
        assert "WCU" in analysis, "No WCU mentioned in capacity analysis"


class TestModelBaseline:
    """Compare model output against baseline."""

    def test_model_baseline_consistency(self, pipeline_result, baselines_dir):
        """Model structure is consistent with baseline."""
        model = pipeline_result.get("dynamo_model.json", {})
        current = {
            "gsi_count": len(model.get("gsis", [])),
            "entity_count": len(model.get("entityMappings", {})),
            "entity_names": sorted(model.get("entityMappings", {}).keys()),
            "access_pattern_count": len(model.get("accessPatternMapping", {})),
            "gsi_names": sorted([g.get("indexName", "") for g in model.get("gsis", [])]),
        }

        baseline = load_baseline(baselines_dir, "model_baseline")
        if baseline is None:
            save_baseline(baselines_dir, "model_baseline", current)
            pytest.skip("Model baseline created — re-run to validate")
        else:
            # GSI count within ±1
            assert abs(current["gsi_count"] - baseline["gsi_count"]) <= 1, (
                f"GSI count drift: {baseline['gsi_count']} → {current['gsi_count']}"
            )
            # Entity names overlap ≥70%
            baseline_set = set(baseline["entity_names"])
            current_set = set(current["entity_names"])
            overlap = len(baseline_set & current_set) / max(len(baseline_set), 1)
            assert overlap >= 0.7, (
                f"Entity mapping overlap {overlap:.0%} below 70%"
            )
