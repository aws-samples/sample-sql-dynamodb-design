"""Tier 1: Deterministic Roslyn tests — no Bedrock required.

These tests validate the Roslyn analyzer output against a golden baseline.
The baseline is auto-generated on first run and compared on subsequent runs.
"""

import json
import os
import subprocess
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from conftest import load_baseline, save_baseline


# Expected entities for the sample-dotnet-project (from AppDbContext DbSet properties)
EXPECTED_DBCONTEXT_ENTITIES = {
    "User", "Profile", "Address", "Product", "Category",
    "Order", "OrderItem", "Review", "Inventory",
}

# These should NEVER appear as entities
EXCLUDED_ENTITY_PATTERNS = [
    "ViewModel", "Response", "Request", "Dto", "DTO",
    "Command", "Query", "Result", "Details", "Error",
    "Exception", "Handler", "Controller", "Service",
    "Context", "DbContext",
]


@pytest.fixture(scope="module")
def roslyn_output(sample_project_path, roslyn_analyzer_path, output_dir):
    """Run the Roslyn analyzer and return parsed output."""
    if not os.path.exists(roslyn_analyzer_path):
        pytest.skip("Roslyn analyzer not found")

    output_path = os.path.join(output_dir, "test_roslyn_analysis.json")

    result = subprocess.run(
        ["dotnet", "run", "--project", roslyn_analyzer_path, "-c", "Release",
         "--", sample_project_path, "--output", output_path],
        capture_output=True, text=True, timeout=300,
        encoding="utf-8", errors="replace",
    )

    if not os.path.exists(output_path):
        pytest.fail(f"Roslyn analyzer produced no output.\nstderr: {result.stderr}")

    with open(output_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data


class TestRoslynEntityDetection:
    """Validate Roslyn entity identification accuracy."""

    def test_detects_all_dbcontext_entities(self, roslyn_output):
        """All DbSet entities from AppDbContext are detected."""
        entity_names = {e["name"] for e in roslyn_output["entities"]}
        missing = EXPECTED_DBCONTEXT_ENTITIES - entity_names
        assert not missing, f"Missing DbContext entities: {missing}"

    def test_entity_sources_are_valid(self, roslyn_output):
        """Every entity has a valid source."""
        valid_sources = {"dbcontext", "navigation", "automapper"}
        for entity in roslyn_output["entities"]:
            assert entity.get("source") in valid_sources, (
                f"Entity '{entity['name']}' has invalid source: {entity.get('source')}"
            )

    def test_no_viewmodels_or_dtos(self, roslyn_output):
        """No ViewModels, DTOs, or non-DB classes in entity list."""
        for entity in roslyn_output["entities"]:
            name = entity["name"]
            for pattern in EXCLUDED_ENTITY_PATTERNS:
                assert not name.endswith(pattern) and not name.startswith(pattern), (
                    f"Entity '{name}' matches excluded pattern '{pattern}'"
                )

    def test_dbcontext_entities_have_fields(self, roslyn_output):
        """DbContext entities have field definitions."""
        for entity in roslyn_output["entities"]:
            if entity.get("source") == "dbcontext":
                assert len(entity.get("fields", [])) > 0, (
                    f"DbContext entity '{entity['name']}' has no fields"
                )

    def test_entity_count_reasonable(self, roslyn_output):
        """Entity count is within expected range for sample project."""
        count = len(roslyn_output["entities"])
        assert 7 <= count <= 15, f"Entity count {count} outside expected range [7, 15]"


class TestRoslynAccessMethodClassification:
    """Validate access method DB vs in-memory classification."""

    def test_access_methods_are_db_queries(self, roslyn_output):
        """All accessMethods have isDbQuery=true."""
        for method in roslyn_output.get("accessMethods", []):
            assert method.get("isDbQuery") is True, (
                f"Access method {method['class']}.{method['method']} has isDbQuery=false"
            )

    def test_supplementary_methods_are_in_memory(self, roslyn_output):
        """All supplementaryMethods have isDbQuery=false."""
        for method in roslyn_output.get("supplementaryMethods", []):
            assert method.get("isDbQuery") is False, (
                f"Supplementary method {method['class']}.{method['method']} has isDbQuery=true"
            )

    def test_no_test_methods_in_output(self, roslyn_output):
        """No test methods in access methods."""
        test_indicators = ["Test", "Spec", "Mock", "Fake", "Stub", "Assert"]
        for method in roslyn_output.get("accessMethods", []):
            file_path = method.get("file", "")
            assert not any(t in file_path for t in ["Tests/", "Test/", "UnitTests/", "FunctionalTests/"]), (
                f"Test file in accessMethods: {file_path}"
            )

    def test_access_method_count_reasonable(self, roslyn_output):
        """Access method count is within expected range."""
        db_count = len(roslyn_output.get("accessMethods", []))
        supp_count = len(roslyn_output.get("supplementaryMethods", []))
        assert db_count >= 3, f"Too few DB access methods: {db_count}"
        assert db_count <= 50, f"Too many DB access methods: {db_count}"


class TestRoslynBaseline:
    """Compare Roslyn output against golden baseline."""

    def test_baseline_consistency(self, roslyn_output, baselines_dir):
        """Roslyn output matches the golden baseline (or creates it on first run)."""
        baseline = load_baseline(baselines_dir, "roslyn_baseline")

        # Extract comparable data
        current = {
            "entity_names": sorted([e["name"] for e in roslyn_output["entities"]]),
            "entity_sources": {e["name"]: e.get("source") for e in roslyn_output["entities"]},
            "db_method_count": len(roslyn_output.get("accessMethods", [])),
            "supplementary_method_count": len(roslyn_output.get("supplementaryMethods", [])),
            "ef_core_detected": roslyn_output.get("efCoreDetected"),
        }

        if baseline is None:
            # First run — save as baseline
            save_baseline(baselines_dir, "roslyn_baseline", current)
            pytest.skip("Baseline created on first run — re-run to validate")
        else:
            # Compare against baseline
            assert current["entity_names"] == baseline["entity_names"], (
                f"Entity names changed.\n"
                f"  Baseline: {baseline['entity_names']}\n"
                f"  Current:  {current['entity_names']}"
            )
            assert current["entity_sources"] == baseline["entity_sources"], (
                f"Entity sources changed"
            )
            assert current["db_method_count"] == baseline["db_method_count"], (
                f"DB method count changed: {baseline['db_method_count']} → {current['db_method_count']}"
            )
            assert current["ef_core_detected"] == baseline["ef_core_detected"]
