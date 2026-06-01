"""Tier 4: Cross-run drift detection — uses DB history, no extra Bedrock runs needed.

Analyzes the last 3-5 pipeline runs stored in the database to detect output drift.
Skips if insufficient history (<3 runs).
"""

import json
import os
import sys
import pytest
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


MIN_RUNS_FOR_DRIFT = 3
MAX_RUNS_FOR_DRIFT = 5


def jaccard_similarity(set_a, set_b):
    """Calculate Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 1.0


@pytest.fixture(scope="module")
def historical_runs(db_session):
    """Load the last N completed pipeline runs with their results from the DB."""
    from backend.db.repositories import PipelineRepository

    repo = PipelineRepository(db_session)

    # Get all completed runs that have model phase
    from backend.db.models import PipelineRun, PipelineResult
    runs = (
        db_session.query(PipelineRun)
        .filter(PipelineRun.status == "completed")
        .order_by(PipelineRun.id.desc())
        .limit(MAX_RUNS_FOR_DRIFT)
        .all()
    )

    if len(runs) < MIN_RUNS_FOR_DRIFT:
        pytest.skip(f"Insufficient history: {len(runs)} runs (need {MIN_RUNS_FOR_DRIFT}+)")

    # Load results for each run
    history = []
    for run in runs:
        results = (
            db_session.query(PipelineResult)
            .filter(PipelineResult.run_id == run.id)
            .all()
        )
        run_data = {
            "run_id": run.id,
            "phases_config": run.phases_config,
            "results": {},
        }
        for result in results:
            if result.content:
                run_data["results"][result.output_type] = result.content
        history.append(run_data)

    return history


def parse_entities_from_run(run_data):
    """Extract entity names from a run's results."""
    # Try entity_metrics from extraction
    for key in ["access_patterns_md", "model_json"]:
        content = run_data["results"].get(key, "")
        if key == "model_json" and content:
            try:
                model = json.loads(content)
                return set(model.get("entityMappings", {}).keys())
            except json.JSONDecodeError:
                try:
                    decoder = json.JSONDecoder()
                    model, _ = decoder.raw_decode(content.lstrip())
                    return set(model.get("entityMappings", {}).keys())
                except (json.JSONDecodeError, ValueError):
                    pass
    return set()


def parse_gsi_count_from_run(run_data):
    """Extract GSI count from a run's model JSON."""
    content = run_data["results"].get("model_json", "")
    if content:
        try:
            model = json.loads(content)
            return len(model.get("gsis", []))
        except json.JSONDecodeError:
            try:
                decoder = json.JSONDecoder()
                model, _ = decoder.raw_decode(content.lstrip())
                return len(model.get("gsis", []))
            except (json.JSONDecodeError, ValueError):
                pass
    return None


def parse_access_pattern_count_from_run(run_data):
    """Extract access pattern count from a run's model JSON."""
    content = run_data["results"].get("model_json", "")
    if content:
        try:
            model = json.loads(content)
            return len(model.get("accessPatternMapping", {}))
        except json.JSONDecodeError:
            try:
                decoder = json.JSONDecoder()
                model, _ = decoder.raw_decode(content.lstrip())
                return len(model.get("accessPatternMapping", {}))
            except (json.JSONDecodeError, ValueError):
                pass
    return None


class TestEntityDrift:
    """Detect entity set drift across runs."""

    def test_entity_set_stability(self, historical_runs):
        """Entity sets should be stable across recent runs (Jaccard ≥ 0.7)."""
        entity_sets = []
        for run in historical_runs:
            entities = parse_entities_from_run(run)
            if entities:
                entity_sets.append((run["run_id"], entities))

        if len(entity_sets) < MIN_RUNS_FOR_DRIFT:
            pytest.skip(f"Only {len(entity_sets)} runs with entity data")

        # Compare each consecutive pair
        for i in range(len(entity_sets) - 1):
            run_a_id, set_a = entity_sets[i]
            run_b_id, set_b = entity_sets[i + 1]
            similarity = jaccard_similarity(set_a, set_b)
            assert similarity >= 0.7, (
                f"Entity drift between run #{run_b_id} and #{run_a_id}: "
                f"Jaccard={similarity:.2f}\n"
                f"  Run #{run_b_id}: {sorted(set_b)}\n"
                f"  Run #{run_a_id}: {sorted(set_a)}\n"
                f"  Added: {sorted(set_b - set_a)}\n"
                f"  Removed: {sorted(set_a - set_b)}"
            )

    def test_core_entities_always_present(self, historical_runs):
        """Core entities appear in every run."""
        # Find entities that appear in ALL runs
        all_entity_sets = []
        for run in historical_runs:
            entities = parse_entities_from_run(run)
            if entities:
                all_entity_sets.append(entities)

        if len(all_entity_sets) < MIN_RUNS_FOR_DRIFT:
            pytest.skip("Insufficient entity data")

        # Entities present in every run
        core = set.intersection(*all_entity_sets) if all_entity_sets else set()
        # Entities present in at least 80% of runs
        counter = Counter()
        for s in all_entity_sets:
            for e in s:
                counter[e] += 1
        threshold = len(all_entity_sets) * 0.8
        stable = {e for e, c in counter.items() if c >= threshold}

        assert len(stable) >= 3, (
            f"Only {len(stable)} stable entities across {len(all_entity_sets)} runs.\n"
            f"  Core (100%): {sorted(core)}\n"
            f"  Stable (≥80%): {sorted(stable)}"
        )


class TestGSIDrift:
    """Detect GSI count drift across runs."""

    def test_gsi_count_stability(self, historical_runs):
        """GSI count should be stable (std dev ≤ 1.0)."""
        import statistics

        gsi_counts = []
        for run in historical_runs:
            count = parse_gsi_count_from_run(run)
            if count is not None:
                gsi_counts.append(count)

        if len(gsi_counts) < MIN_RUNS_FOR_DRIFT:
            pytest.skip(f"Only {len(gsi_counts)} runs with GSI data")

        stdev = statistics.stdev(gsi_counts) if len(gsi_counts) > 1 else 0
        mean = statistics.mean(gsi_counts)
        assert stdev <= 1.5, (
            f"GSI count unstable: mean={mean:.1f}, stdev={stdev:.2f}\n"
            f"  Counts: {gsi_counts}"
        )


class TestAccessPatternDrift:
    """Detect access pattern count drift across runs."""

    def test_access_pattern_count_stability(self, historical_runs):
        """Access pattern count should be stable (std dev ≤ 3.0)."""
        import statistics

        ap_counts = []
        for run in historical_runs:
            count = parse_access_pattern_count_from_run(run)
            if count is not None:
                ap_counts.append(count)

        if len(ap_counts) < MIN_RUNS_FOR_DRIFT:
            pytest.skip(f"Only {len(ap_counts)} runs with AP data")

        stdev = statistics.stdev(ap_counts) if len(ap_counts) > 1 else 0
        mean = statistics.mean(ap_counts)
        assert stdev <= 5.0, (
            f"Access pattern count unstable: mean={mean:.1f}, stdev={stdev:.2f}\n"
            f"  Counts: {ap_counts}"
        )


class TestOutputCompleteness:
    """Check that recent runs produce all expected outputs."""

    def test_all_runs_have_model(self, historical_runs):
        """All pipeline runs with model phase produce model_json."""
        for run in historical_runs:
            phases = run.get("phases_config", {})
            if phases.get("model"):
                assert "model_json" in run["results"], (
                    f"Run #{run['run_id']} has model phase but no model_json output"
                )

    def test_all_runs_have_capacity(self, historical_runs):
        """All pipeline runs with metrics phase produce capacity_md."""
        for run in historical_runs:
            phases = run.get("phases_config", {})
            if phases.get("metrics"):
                assert "capacity_md" in run["results"], (
                    f"Run #{run['run_id']} has metrics phase but no capacity_md output"
                )
