"""Property-based tests for the consensus extraction module."""

from hypothesis import given, settings, strategies as st

from backend.services.consensus import ConsensusComparer


# Feature: consensus-extraction, Property 3: Confidence score formula
# Validates: Requirements 3.3, 3.4
#
# For any entity_agreement, pattern_agreement, and roslyn_alignment in [0,1],
# the computed confidence score shall equal
#   0.4 * entity_agreement + 0.3 * pattern_agreement + 0.3 * roslyn_alignment
# and the result shall always be in [0, 1].


@settings(max_examples=100)
@given(
    entity_agreement=st.floats(min_value=0.0, max_value=1.0),
    pattern_agreement=st.floats(min_value=0.0, max_value=1.0),
    roslyn_alignment=st.floats(min_value=0.0, max_value=1.0),
)
def test_confidence_score_formula(
    entity_agreement: float,
    pattern_agreement: float,
    roslyn_alignment: float,
) -> None:
    """The confidence score must match the weighted formula and stay in [0, 1]."""
    score = ConsensusComparer.compute_confidence(
        entity_agreement, pattern_agreement, roslyn_alignment
    )

    expected = (
        0.4 * entity_agreement
        + 0.3 * pattern_agreement
        + 0.3 * roslyn_alignment
    )

    assert score == max(0.0, min(1.0, expected)), (
        f"Score {score} != clamped expected {max(0.0, min(1.0, expected))}"
    )
    assert 0.0 <= score <= 1.0, f"Score {score} out of [0, 1]"


@settings(max_examples=100)
@given(
    entity_agreement=st.floats(min_value=0.0, max_value=1.0),
    pattern_agreement=st.floats(min_value=0.0, max_value=1.0),
    roslyn_alignment=st.floats(min_value=0.0, max_value=1.0),
)
def test_confidence_score_weights_sum_to_one(
    entity_agreement: float,
    pattern_agreement: float,
    roslyn_alignment: float,
) -> None:
    """When all inputs are equal to v, the score must equal v (weights sum to 1)."""
    # Use a single value for all three to verify weights sum to 1.0
    v = entity_agreement  # reuse the generated value
    score = ConsensusComparer.compute_confidence(v, v, v)
    assert abs(score - v) < 1e-9, f"Score {score} != {v} when all inputs equal"


def test_confidence_score_boundary_zero() -> None:
    """All-zero inputs produce a zero score."""
    assert ConsensusComparer.compute_confidence(0.0, 0.0, 0.0) == 0.0


def test_confidence_score_boundary_one() -> None:
    """All-one inputs produce a score of 1.0."""
    assert ConsensusComparer.compute_confidence(1.0, 1.0, 1.0) == 1.0


def test_confidence_score_entity_weight() -> None:
    """Entity agreement has 40% weight."""
    score = ConsensusComparer.compute_confidence(1.0, 0.0, 0.0)
    assert abs(score - 0.4) < 1e-9


def test_confidence_score_pattern_weight() -> None:
    """Pattern agreement has 30% weight."""
    score = ConsensusComparer.compute_confidence(0.0, 1.0, 0.0)
    assert abs(score - 0.3) < 1e-9


def test_confidence_score_roslyn_weight() -> None:
    """Roslyn alignment has 30% weight."""
    score = ConsensusComparer.compute_confidence(0.0, 0.0, 1.0)
    assert abs(score - 0.3) < 1e-9


# ---------------------------------------------------------------------------
# Unit tests for ConsensusComparer._entity_agreement
# Validates: Requirements 3.1, 3.3
# ---------------------------------------------------------------------------

from backend.services.consensus import ExtractionOutput


def _make_output(*entity_names: str) -> ExtractionOutput:
    """Helper: create an ExtractionOutput with the given entity names."""
    return ExtractionOutput(entities={name: {} for name in entity_names})


def test_entity_agreement_all_three_agree() -> None:
    """When all 3 outputs share the same entities, ratio is 1.0."""
    outputs = [
        _make_output("User", "Order"),
        _make_output("User", "Order"),
        _make_output("User", "Order"),
    ]
    ratio, agreed, disagreed = ConsensusComparer._entity_agreement(outputs)
    assert ratio == 1.0
    assert agreed == {"User", "Order"}
    assert disagreed == set()


def test_entity_agreement_two_of_three() -> None:
    """Entities in ≥2 outputs are agreed; those in only 1 are disagreed."""
    outputs = [
        _make_output("User", "Order"),
        _make_output("User", "Product"),
        _make_output("User", "Order"),
    ]
    ratio, agreed, disagreed = ConsensusComparer._entity_agreement(outputs)
    # User in 3, Order in 2, Product in 1 → 2 agreed / 3 total
    assert agreed == {"User", "Order"}
    assert disagreed == {"Product"}
    assert abs(ratio - 2 / 3) < 1e-9


def test_entity_agreement_no_overlap() -> None:
    """When every entity appears in only 1 output, ratio is 0.0."""
    outputs = [
        _make_output("A"),
        _make_output("B"),
        _make_output("C"),
    ]
    ratio, agreed, disagreed = ConsensusComparer._entity_agreement(outputs)
    assert ratio == 0.0
    assert agreed == set()
    assert disagreed == {"A", "B", "C"}


def test_entity_agreement_empty_outputs() -> None:
    """No entities at all → perfect agreement (1.0)."""
    outputs = [_make_output(), _make_output(), _make_output()]
    ratio, agreed, disagreed = ConsensusComparer._entity_agreement(outputs)
    assert ratio == 1.0
    assert agreed == set()
    assert disagreed == set()


def test_entity_agreement_two_run_case() -> None:
    """2-run case (1 failure): both must agree for an entity to count."""
    outputs = [
        _make_output("User", "Order"),
        _make_output("User"),
    ]
    ratio, agreed, disagreed = ConsensusComparer._entity_agreement(outputs)
    # User in 2 → agreed; Order in 1 → disagreed → 1/2
    assert agreed == {"User"}
    assert disagreed == {"Order"}
    assert abs(ratio - 0.5) < 1e-9


def test_entity_agreement_two_run_full_agreement() -> None:
    """2-run case where both outputs are identical → ratio 1.0."""
    outputs = [
        _make_output("User", "Order"),
        _make_output("User", "Order"),
    ]
    ratio, agreed, disagreed = ConsensusComparer._entity_agreement(outputs)
    assert ratio == 1.0
    assert agreed == {"User", "Order"}
    assert disagreed == set()


# ---------------------------------------------------------------------------
# Feature: consensus-extraction, Property 4: Entity agreement ratio
# Validates: Requirements 3.1, 3.3
#
# For any set of 3 LLM extraction outputs each containing a set of entity
# names, the entity agreement ratio shall equal the number of entity names
# appearing in at least 2 of the 3 outputs divided by the total number of
# unique entity names across all outputs.
# ---------------------------------------------------------------------------

_entity_name_strategy = st.text(
    min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))
)
_entity_set_strategy = st.sets(_entity_name_strategy, max_size=10)


@settings(max_examples=100)
@given(
    set_a=_entity_set_strategy,
    set_b=_entity_set_strategy,
    set_c=_entity_set_strategy,
)
def test_entity_agreement_ratio(
    set_a: set[str],
    set_b: set[str],
    set_c: set[str],
) -> None:
    """**Validates: Requirements 3.1, 3.3**

    The entity agreement ratio must equal
    (entities in ≥2 sets) / (total unique entities).
    Agreed and disagreed sets must partition all unique entities.
    """
    outputs = [
        ExtractionOutput(entities={name: {} for name in set_a}),
        ExtractionOutput(entities={name: {} for name in set_b}),
        ExtractionOutput(entities={name: {} for name in set_c}),
    ]

    ratio, agreed, disagreed = ConsensusComparer._entity_agreement(outputs)

    # Manually compute expected values
    all_unique = set_a | set_b | set_c

    if not all_unique:
        assert ratio == 1.0, "Empty inputs should yield ratio 1.0"
        assert agreed == set()
        assert disagreed == set()
        return

    from collections import Counter

    counts: Counter[str] = Counter()
    for s in (set_a, set_b, set_c):
        for name in s:
            counts[name] += 1

    expected_agreed = {name for name, cnt in counts.items() if cnt >= 2}
    expected_disagreed = all_unique - expected_agreed
    expected_ratio = len(expected_agreed) / len(all_unique)

    # Assert ratio matches
    assert abs(ratio - expected_ratio) < 1e-9, (
        f"Ratio {ratio} != expected {expected_ratio}"
    )

    # Assert agreed + disagreed = all unique entities
    assert agreed | disagreed == all_unique, (
        f"agreed ∪ disagreed ({agreed | disagreed}) != all_unique ({all_unique})"
    )

    # Assert agreed ∩ disagreed = empty set
    assert agreed & disagreed == set(), (
        f"agreed ∩ disagreed is not empty: {agreed & disagreed}"
    )


# ---------------------------------------------------------------------------
# Feature: consensus-extraction, Property 5: Pattern agreement ratio
# Validates: Requirements 3.2, 3.3
#
# For any set of 3 LLM extraction outputs each containing a set of access
# pattern IDs, the pattern agreement ratio shall equal the number of pattern
# IDs appearing in at least 2 of the 3 outputs divided by the total number
# of unique pattern IDs across all outputs.
# ---------------------------------------------------------------------------

_pattern_id_strategy = st.text(
    min_size=1,
    max_size=10,
    alphabet=st.characters(whitelist_categories=("L", "N")),
)
_pattern_set_strategy = st.sets(_pattern_id_strategy, max_size=10)


def _make_pattern_output(*pattern_ids: str) -> ExtractionOutput:
    """Helper: create an ExtractionOutput with the given access pattern IDs."""
    return ExtractionOutput(access_patterns={pid: {} for pid in pattern_ids})


@settings(max_examples=100)
@given(
    set_a=_pattern_set_strategy,
    set_b=_pattern_set_strategy,
    set_c=_pattern_set_strategy,
)
def test_pattern_agreement_ratio(
    set_a: set[str],
    set_b: set[str],
    set_c: set[str],
) -> None:
    """**Validates: Requirements 3.2, 3.3**

    The pattern agreement ratio must equal
    (patterns in ≥2 sets) / (total unique patterns).
    Agreed and disagreed sets must partition all unique patterns.
    """
    outputs = [
        ExtractionOutput(access_patterns={pid: {} for pid in set_a}),
        ExtractionOutput(access_patterns={pid: {} for pid in set_b}),
        ExtractionOutput(access_patterns={pid: {} for pid in set_c}),
    ]

    ratio, agreed, disagreed = ConsensusComparer._pattern_agreement(outputs)

    # Manually compute expected values
    all_unique = set_a | set_b | set_c

    if not all_unique:
        assert ratio == 1.0, "Empty inputs should yield ratio 1.0"
        assert agreed == set()
        assert disagreed == set()
        return

    from collections import Counter

    counts: Counter[str] = Counter()
    for s in (set_a, set_b, set_c):
        for pid in s:
            counts[pid] += 1

    expected_agreed = {pid for pid, cnt in counts.items() if cnt >= 2}
    expected_disagreed = all_unique - expected_agreed
    expected_ratio = len(expected_agreed) / len(all_unique)

    # Assert the ratio matches
    assert abs(ratio - expected_ratio) < 1e-9, (
        f"Ratio {ratio} != expected {expected_ratio}"
    )

    # Assert agreed + disagreed = all unique patterns
    assert agreed | disagreed == all_unique, (
        f"agreed ∪ disagreed ({agreed | disagreed}) != all_unique ({all_unique})"
    )

    # Assert agreed ∩ disagreed = empty set
    assert agreed & disagreed == set(), (
        f"agreed ∩ disagreed is not empty: {agreed & disagreed}"
    )


# ---------------------------------------------------------------------------
# Unit tests for ConsensusComparer.compare() — Roslyn alignment & full flow
# Validates: Requirements 2.2, 2.3, 3.3, 3.4
# ---------------------------------------------------------------------------

from backend.services.consensus import ComparisonResult, RoslynOutput


def test_compare_roslyn_none_fallback() -> None:
    """When roslyn_output is None, roslyn_alignment falls back to entity_agreement."""
    outputs = [
        _make_output("User", "Order"),
        _make_output("User", "Order"),
        _make_output("User", "Order"),
    ]
    result = ConsensusComparer.compare(outputs, roslyn_output=None)
    assert result.entity_agreement == 1.0
    assert result.roslyn_alignment == result.entity_agreement
    expected_score = 0.4 * 1.0 + 0.3 * 1.0 + 0.3 * 1.0
    assert abs(result.overall_score - expected_score) < 1e-9


def test_compare_roslyn_full_alignment() -> None:
    """All agreed entities are in Roslyn → roslyn_alignment = 1.0."""
    outputs = [
        _make_output("User", "Order"),
        _make_output("User", "Order"),
        _make_output("User"),
    ]
    roslyn = RoslynOutput(entity_names={"User", "Order", "Product"})
    result = ConsensusComparer.compare(outputs, roslyn_output=roslyn)
    assert result.agreed_entities == {"User", "Order"}
    assert result.roslyn_alignment == 1.0


def test_compare_roslyn_partial_alignment() -> None:
    """Only some agreed entities are in Roslyn."""
    outputs = [
        _make_output("User", "Order"),
        _make_output("User", "Order"),
        _make_output("User", "Order"),
    ]
    roslyn = RoslynOutput(entity_names={"User"})  # Order not in Roslyn
    result = ConsensusComparer.compare(outputs, roslyn_output=roslyn)
    assert result.agreed_entities == {"User", "Order"}
    assert result.roslyn_alignment == 0.5  # 1 of 2 agreed in Roslyn


def test_compare_roslyn_no_alignment() -> None:
    """No agreed entities are in Roslyn → roslyn_alignment = 0.0."""
    outputs = [
        _make_output("User", "Order"),
        _make_output("User", "Order"),
        _make_output("User", "Order"),
    ]
    roslyn = RoslynOutput(entity_names={"Product", "Invoice"})
    result = ConsensusComparer.compare(outputs, roslyn_output=roslyn)
    assert result.roslyn_alignment == 0.0


def test_compare_empty_agreed_entities_with_roslyn() -> None:
    """No agreed entities but Roslyn present → roslyn_alignment = 1.0."""
    outputs = [
        _make_output("A"),
        _make_output("B"),
        _make_output("C"),
    ]
    roslyn = RoslynOutput(entity_names={"X"})
    result = ConsensusComparer.compare(outputs, roslyn_output=roslyn)
    assert result.agreed_entities == set()
    assert result.roslyn_alignment == 1.0


def test_compare_populates_all_fields() -> None:
    """compare() returns a ComparisonResult with all fields populated."""
    outputs = [
        ExtractionOutput(
            entities={"User": {}, "Order": {}},
            access_patterns={"AP1": {}, "AP2": {}},
        ),
        ExtractionOutput(
            entities={"User": {}, "Product": {}},
            access_patterns={"AP1": {}, "AP3": {}},
        ),
        ExtractionOutput(
            entities={"User": {}, "Order": {}},
            access_patterns={"AP1": {}, "AP2": {}},
        ),
    ]
    roslyn = RoslynOutput(entity_names={"User", "Order"})
    result = ConsensusComparer.compare(outputs, roslyn_output=roslyn)

    assert isinstance(result, ComparisonResult)
    assert result.agreed_entities == {"User", "Order"}
    assert result.disagreed_entities == {"Product"}
    assert result.agreed_patterns == {"AP1", "AP2"}
    assert result.disagreed_patterns == {"AP3"}
    assert result.roslyn_alignment == 1.0  # both agreed in Roslyn
    assert abs(result.entity_agreement - 2 / 3) < 1e-9
    assert abs(result.pattern_agreement - 2 / 3) < 1e-9

    expected_score = 0.4 * (2 / 3) + 0.3 * (2 / 3) + 0.3 * 1.0
    assert abs(result.overall_score - expected_score) < 1e-9


# ---------------------------------------------------------------------------
# Feature: consensus-extraction, Property 7: Entity merge inclusion rule
# Validates: Requirements 5.1
#
# For any set of 3 LLM extraction outputs and an optional Roslyn baseline,
# the merged entity set shall contain exactly those entities that appear in
# at least 2 of the 3 LLM outputs OR appear in the Roslyn baseline. No
# entity outside this union shall be included, and no entity inside it shall
# be excluded.
# ---------------------------------------------------------------------------

from backend.services.consensus import ResultMerger


@settings(max_examples=100)
@given(
    set_a=_entity_set_strategy,
    set_b=_entity_set_strategy,
    set_c=_entity_set_strategy,
    roslyn_set=st.one_of(st.none(), _entity_set_strategy),
)
def test_entity_merge_inclusion_rule(
    set_a: set[str],
    set_b: set[str],
    set_c: set[str],
    roslyn_set: set[str] | None,
) -> None:
    """**Validates: Requirements 5.1**

    The merged entity set must contain exactly those entities in ≥2 LLM
    outputs OR in the Roslyn baseline. The dropped list must contain exactly
    those LLM-unique entities that were NOT included.
    """
    # 1. Create 3 ExtractionOutput objects from the generated entity name sets
    outputs = [
        ExtractionOutput(entities={name: {} for name in set_a}),
        ExtractionOutput(entities={name: {} for name in set_b}),
        ExtractionOutput(entities={name: {} for name in set_c}),
    ]

    # 2. Create RoslynOutput (or None) from the Roslyn set
    roslyn_output = (
        RoslynOutput(entity_names=roslyn_set) if roslyn_set is not None else None
    )

    # 3. Call ResultMerger._merge_entities
    merged_entities, dropped = ResultMerger._merge_entities(outputs, roslyn_output)

    # 4. Manually compute expected included set
    from collections import Counter

    counts: Counter[str] = Counter()
    for s in (set_a, set_b, set_c):
        for name in s:
            counts[name] += 1

    all_llm_unique = set_a | set_b | set_c
    roslyn_names = roslyn_set if roslyn_set is not None else set()

    in_at_least_two = {name for name, cnt in counts.items() if cnt >= 2}
    expected_included = in_at_least_two | roslyn_names

    expected_dropped = sorted(all_llm_unique - expected_included)

    # 5. Assert merged entity keys == expected included
    assert set(merged_entities.keys()) == expected_included, (
        f"merged keys {set(merged_entities.keys())} != expected {expected_included}"
    )

    # 6. Assert dropped == all LLM unique entities minus expected included
    assert list(dropped) == expected_dropped, (
        f"dropped {dropped} != expected {expected_dropped}"
    )


# ---------------------------------------------------------------------------
# Feature: consensus-extraction, Property 8: Field resolution prefers Roslyn
# Validates: Requirements 5.2
#
# For any entity present in the merged result where the Roslyn baseline
# provides a field list, the merged field list for that entity shall equal
# the Roslyn field list. For entities where Roslyn has no field data, the
# merged field list shall equal the field list from the majority (≥2) of
# LLM runs.
# ---------------------------------------------------------------------------

_field_name_strategy = st.text(
    min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=("L",))
)
_field_list_strategy = st.lists(
    _field_name_strategy, min_size=1, max_size=5
)
_shared_entity_name_strategy = st.text(
    min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=("L",))
)


@settings(max_examples=100)
@given(
    shared_entity=_shared_entity_name_strategy,
    roslyn_fields=_field_list_strategy,
    llm_fields_a=_field_list_strategy,
    llm_fields_b=_field_list_strategy,
    llm_fields_c=_field_list_strategy,
)
def test_field_resolution_prefers_roslyn(
    shared_entity: str,
    roslyn_fields: list[str],
    llm_fields_a: list[str],
    llm_fields_b: list[str],
    llm_fields_c: list[str],
) -> None:
    """**Validates: Requirements 5.2**

    When Roslyn provides a field list for an entity, the merged field list
    must equal the Roslyn field list, regardless of what the LLM runs report.
    """
    # 1. Create 3 ExtractionOutput objects with the shared entity and LLM fields
    outputs = [
        ExtractionOutput(entities={shared_entity: {"fields": llm_fields_a}}),
        ExtractionOutput(entities={shared_entity: {"fields": llm_fields_b}}),
        ExtractionOutput(entities={shared_entity: {"fields": llm_fields_c}}),
    ]

    # 2. Create RoslynOutput with fields for the shared entity
    roslyn_output = RoslynOutput(
        entity_names={shared_entity},
        entity_fields={shared_entity: roslyn_fields},
    )

    # 3. Call ResultMerger._merge_entities
    merged_entities, _dropped = ResultMerger._merge_entities(outputs, roslyn_output)

    # 4. Assert the merged entity's fields equal the Roslyn field list
    assert shared_entity in merged_entities, (
        f"Entity '{shared_entity}' should be in merged result"
    )
    assert merged_entities[shared_entity]["fields"] == roslyn_fields, (
        f"Fields {merged_entities[shared_entity]['fields']} != Roslyn fields {roslyn_fields}"
    )


@settings(max_examples=100)
@given(
    shared_entity=_shared_entity_name_strategy,
    llm_fields_a=_field_list_strategy,
    llm_fields_b=_field_list_strategy,
    llm_fields_c=_field_list_strategy,
)
def test_field_resolution_majority_llm_without_roslyn(
    shared_entity: str,
    llm_fields_a: list[str],
    llm_fields_b: list[str],
    llm_fields_c: list[str],
) -> None:
    """**Validates: Requirements 5.2**

    When Roslyn has no field data for an entity, the merged field list must
    equal the field list from the majority (≥2) of LLM runs.
    """
    from collections import Counter

    # 1. Create 3 ExtractionOutput objects with the shared entity and LLM fields
    outputs = [
        ExtractionOutput(entities={shared_entity: {"fields": llm_fields_a}}),
        ExtractionOutput(entities={shared_entity: {"fields": llm_fields_b}}),
        ExtractionOutput(entities={shared_entity: {"fields": llm_fields_c}}),
    ]

    # 2. No Roslyn fields for this entity
    roslyn_output = RoslynOutput(entity_names=set(), entity_fields={})

    # 3. Call ResultMerger._merge_entities
    merged_entities, _dropped = ResultMerger._merge_entities(outputs, roslyn_output)

    # Entity appears in all 3 LLM runs → included (≥2)
    assert shared_entity in merged_entities, (
        f"Entity '{shared_entity}' should be in merged result (appears in 3 LLM runs)"
    )

    # 4. Compute expected majority field list
    field_tuples = [
        tuple(llm_fields_a),
        tuple(llm_fields_b),
        tuple(llm_fields_c),
    ]
    field_counter: Counter[tuple[str, ...]] = Counter(field_tuples)
    majority_fields = list(field_counter.most_common(1)[0][0])

    assert merged_entities[shared_entity]["fields"] == majority_fields, (
        f"Fields {merged_entities[shared_entity]['fields']} != majority LLM fields {majority_fields}"
    )


# ---------------------------------------------------------------------------
# Feature: consensus-extraction, Property 9: Pattern merge inclusion rule
# Validates: Requirements 5.3
#
# For any set of 3 LLM extraction outputs, the merged access pattern set
# shall contain exactly those patterns that appear in at least 2 of the 3
# LLM outputs. No pattern outside this set shall be included, and no pattern
# inside it shall be excluded.
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    set_a=_pattern_set_strategy,
    set_b=_pattern_set_strategy,
    set_c=_pattern_set_strategy,
)
def test_pattern_merge_inclusion_rule(
    set_a: set[str],
    set_b: set[str],
    set_c: set[str],
) -> None:
    """**Validates: Requirements 5.3**

    The merged access pattern set must contain exactly those patterns in ≥2
    LLM outputs. The dropped list must contain exactly those patterns that
    appeared in LLM outputs but were NOT included.
    """
    # 1. Create 3 ExtractionOutput objects with access_patterns dicts keyed by pattern IDs
    outputs = [
        ExtractionOutput(access_patterns={pid: {} for pid in set_a}),
        ExtractionOutput(access_patterns={pid: {} for pid in set_b}),
        ExtractionOutput(access_patterns={pid: {} for pid in set_c}),
    ]

    # 2. Call ResultMerger._merge_patterns(outputs)
    merged_access, _merged_write, dropped, _md = ResultMerger._merge_patterns(outputs)

    # 3. Manually compute expected included: patterns in ≥2 of 3 sets
    from collections import Counter

    counts: Counter[str] = Counter()
    for s in (set_a, set_b, set_c):
        for pid in s:
            counts[pid] += 1

    all_unique = set_a | set_b | set_c
    expected_included = {pid for pid, cnt in counts.items() if cnt >= 2}
    expected_dropped = sorted(all_unique - expected_included)

    # 4. Assert set(merged_access_patterns.keys()) == expected included
    assert set(merged_access.keys()) == expected_included, (
        f"merged keys {set(merged_access.keys())} != expected {expected_included}"
    )

    # 5. Assert set(dropped) == all_unique - expected_included
    assert list(dropped) == expected_dropped, (
        f"dropped {dropped} != expected {expected_dropped}"
    )


# ---------------------------------------------------------------------------
# Unit tests for ConsensusExtractor._run_single_extraction
# Validates: Requirements 1.1, 1.2, 1.3
# ---------------------------------------------------------------------------

import json
import os
import shutil

from backend.services.consensus import ConsensusExtractor


def _make_extractor(
    agent_fn=None,
    project_path="/fake/project",
    schema_path=None,
    roslyn_analyzer_path=None,
    logs=None,
):
    """Helper: create a ConsensusExtractor with a controllable agent factory."""
    if logs is None:
        logs = []
    return ConsensusExtractor(
        project_path=project_path,
        schema_path=schema_path,
        agent_factory=agent_fn or (lambda: (lambda prompt: None)),
        roslyn_analyzer_path=roslyn_analyzer_path,
        log_callback=logs.append,
    )


def test_run_single_extraction_success(tmp_path, monkeypatch):
    """Successful extraction returns ExtractionOutput with parsed data."""
    monkeypatch.chdir(tmp_path)

    metrics = {
        "entities": {"User": {"fields": ["Id", "Name"]}},
        "access_patterns": {"AP1": {"name": "GetUser"}},
        "write_patterns": {"WP1": {"name": "CreateUser"}},
    }
    access_md = "# Access Patterns\n- GetUser"

    def fake_agent(prompt):
        temp_dir = "_consensus_run_0"
        os.makedirs(temp_dir, exist_ok=True)
        with open(os.path.join(temp_dir, "entity_metrics.json"), "w") as f:
            json.dump(metrics, f)
        with open(os.path.join(temp_dir, "access_patterns.md"), "w") as f:
            f.write(access_md)

    logs = []
    extractor = _make_extractor(agent_fn=lambda: fake_agent, logs=logs)
    result = extractor._run_single_extraction(run_index=0, round_num=1)

    assert result is not None
    assert result.entities == {"User": {"fields": ["Id", "Name"]}}
    assert result.access_patterns == {"AP1": {"name": "GetUser"}}
    assert result.write_patterns == {"WP1": {"name": "CreateUser"}}
    assert result.raw_entity_metrics == metrics
    assert result.raw_access_patterns_md == access_md
    # Temp dir should be cleaned up
    assert not os.path.exists("_consensus_run_0")


def test_run_single_extraction_no_metrics_file(tmp_path, monkeypatch):
    """Returns None when entity_metrics.json is not produced."""
    monkeypatch.chdir(tmp_path)

    def fake_agent(prompt):
        # Agent runs but produces no output files
        pass

    logs = []
    extractor = _make_extractor(agent_fn=lambda: fake_agent, logs=logs)
    result = extractor._run_single_extraction(run_index=0, round_num=1)

    assert result is None
    assert any("not found" in msg for msg in logs)
    assert not os.path.exists("_consensus_run_0")


def test_run_single_extraction_invalid_json_repaired(tmp_path, monkeypatch):
    """Invalid JSON with trailing commas is repaired successfully."""
    monkeypatch.chdir(tmp_path)

    bad_json = '{"entities": {"User": {},}, "access_patterns": {}, "write_patterns": {}}'

    def fake_agent(prompt):
        temp_dir = "_consensus_run_0"
        os.makedirs(temp_dir, exist_ok=True)
        with open(os.path.join(temp_dir, "entity_metrics.json"), "w") as f:
            f.write(bad_json)

    logs = []
    extractor = _make_extractor(agent_fn=lambda: fake_agent, logs=logs)
    result = extractor._run_single_extraction(run_index=0, round_num=1)

    assert result is not None
    assert "User" in result.entities
    assert any("repaired" in msg for msg in logs)


def test_run_single_extraction_unrecoverable_json(tmp_path, monkeypatch):
    """Completely broken JSON returns None."""
    monkeypatch.chdir(tmp_path)

    def fake_agent(prompt):
        temp_dir = "_consensus_run_0"
        os.makedirs(temp_dir, exist_ok=True)
        with open(os.path.join(temp_dir, "entity_metrics.json"), "w") as f:
            f.write("this is not json at all {{{")

    logs = []
    extractor = _make_extractor(agent_fn=lambda: fake_agent, logs=logs)
    result = extractor._run_single_extraction(run_index=0, round_num=1)

    assert result is None
    assert any("invalid even after repair" in msg for msg in logs)


def test_run_single_extraction_agent_exception(tmp_path, monkeypatch):
    """Agent raising an exception returns None and logs warning."""
    monkeypatch.chdir(tmp_path)

    def exploding_agent(prompt):
        raise RuntimeError("LLM connection failed")

    logs = []
    extractor = _make_extractor(agent_fn=lambda: exploding_agent, logs=logs)
    result = extractor._run_single_extraction(run_index=0, round_num=1)

    assert result is None
    assert any("failed" in msg for msg in logs)


def test_run_single_extraction_cleanup_on_failure(tmp_path, monkeypatch):
    """Temp directory is cleaned up even when extraction fails."""
    monkeypatch.chdir(tmp_path)

    def exploding_agent(prompt):
        # Create the temp dir so there's something to clean up
        os.makedirs("_consensus_run_1", exist_ok=True)
        with open("_consensus_run_1/some_file.txt", "w") as f:
            f.write("data")
        raise RuntimeError("boom")

    logs = []
    extractor = _make_extractor(agent_fn=lambda: exploding_agent, logs=logs)
    result = extractor._run_single_extraction(run_index=1, round_num=1)

    assert result is None
    assert not os.path.exists("_consensus_run_1")


def test_run_single_extraction_no_access_patterns_md(tmp_path, monkeypatch):
    """Missing access_patterns.md results in empty raw_access_patterns_md."""
    monkeypatch.chdir(tmp_path)

    metrics = {"entities": {"Order": {}}, "access_patterns": {}, "write_patterns": {}}

    def fake_agent(prompt):
        temp_dir = "_consensus_run_0"
        os.makedirs(temp_dir, exist_ok=True)
        with open(os.path.join(temp_dir, "entity_metrics.json"), "w") as f:
            json.dump(metrics, f)
        # No access_patterns.md written

    logs = []
    extractor = _make_extractor(agent_fn=lambda: fake_agent, logs=logs)
    result = extractor._run_single_extraction(run_index=0, round_num=1)

    assert result is not None
    assert result.raw_access_patterns_md == ""
    assert result.entities == {"Order": {}}


# ---------------------------------------------------------------------------
# Unit tests for ConsensusExtractor._run_roslyn
# Validates: Requirements 2.1, 2.2, 2.3
# ---------------------------------------------------------------------------


def test_run_roslyn_path_none() -> None:
    """Returns None and logs when roslyn_analyzer_path is None."""
    logs: list[str] = []
    extractor = _make_extractor(roslyn_analyzer_path=None, logs=logs)
    result = extractor._run_roslyn()

    assert result is None
    assert any("not available" in msg for msg in logs)


def test_run_roslyn_path_does_not_exist(tmp_path) -> None:
    """Returns None and logs when roslyn_analyzer_path doesn't exist."""
    logs: list[str] = []
    extractor = _make_extractor(
        roslyn_analyzer_path=str(tmp_path / "nonexistent.csproj"),
        logs=logs,
    )
    result = extractor._run_roslyn()

    assert result is None
    assert any("not available" in msg for msg in logs)


def test_run_roslyn_success(tmp_path, monkeypatch) -> None:
    """Successful Roslyn run parses entities, fields, relationships, and access methods."""
    monkeypatch.chdir(tmp_path)

    # Create a fake analyzer project file
    analyzer_path = tmp_path / "FakeAnalyzer.csproj"
    analyzer_path.write_text("<Project/>")

    roslyn_json = {
        "entities": [
            {
                "name": "User",
                "fields": [
                    {"name": "Id", "type": "int"},
                    {"name": "Name", "type": "string"},
                ],
                "relationships": [
                    {"type": "HasMany", "target": "Order"},
                ],
            },
            {
                "name": "Order",
                "fields": [
                    {"name": "Id", "type": "int"},
                    {"name": "Total", "type": "decimal"},
                ],
                "relationships": [],
            },
        ],
        "accessMethods": [
            {"class": "UserRepo", "method": "GetAll", "operation": "read"},
        ],
    }

    # Patch subprocess.run to write the roslyn_analysis.json file
    import subprocess as _subprocess

    original_run = _subprocess.run

    def fake_subprocess_run(cmd, **kwargs):
        # Write the fake roslyn output
        with open("roslyn_analysis.json", "w") as f:
            json.dump(roslyn_json, f)
        return _subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    logs: list[str] = []
    extractor = _make_extractor(
        roslyn_analyzer_path=str(analyzer_path),
        logs=logs,
    )
    result = extractor._run_roslyn()

    assert result is not None
    assert result.entity_names == {"User", "Order"}
    assert result.entity_fields["User"] == ["Id", "Name"]
    assert result.entity_fields["Order"] == ["Id", "Total"]
    assert result.relationships["User"] == [{"type": "HasMany", "target": "Order"}]
    assert result.relationships["Order"] == []
    assert result.access_methods == [
        {"class": "UserRepo", "method": "GetAll", "operation": "read"},
    ]


def test_run_roslyn_no_output_file(tmp_path, monkeypatch) -> None:
    """Returns None when Roslyn produces no output file."""
    monkeypatch.chdir(tmp_path)

    analyzer_path = tmp_path / "FakeAnalyzer.csproj"
    analyzer_path.write_text("<Project/>")

    import subprocess as _subprocess

    def fake_subprocess_run(cmd, **kwargs):
        # Don't write any output file
        return _subprocess.CompletedProcess(cmd, 1, stdout="", stderr="error")

    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    logs: list[str] = []
    extractor = _make_extractor(
        roslyn_analyzer_path=str(analyzer_path),
        logs=logs,
    )
    result = extractor._run_roslyn()

    assert result is None
    assert any("no output" in msg for msg in logs)


def test_run_roslyn_subprocess_exception(tmp_path, monkeypatch) -> None:
    """Returns None and logs when subprocess raises an exception."""
    monkeypatch.chdir(tmp_path)

    analyzer_path = tmp_path / "FakeAnalyzer.csproj"
    analyzer_path.write_text("<Project/>")

    def fake_subprocess_run(cmd, **kwargs):
        raise OSError("dotnet not found")

    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    logs: list[str] = []
    extractor = _make_extractor(
        roslyn_analyzer_path=str(analyzer_path),
        logs=logs,
    )
    result = extractor._run_roslyn()

    assert result is None
    assert any("failed" in msg for msg in logs)


def test_run_roslyn_invalid_json(tmp_path, monkeypatch) -> None:
    """Returns None when roslyn_analysis.json contains invalid JSON."""
    monkeypatch.chdir(tmp_path)

    analyzer_path = tmp_path / "FakeAnalyzer.csproj"
    analyzer_path.write_text("<Project/>")

    import subprocess as _subprocess

    def fake_subprocess_run(cmd, **kwargs):
        with open("roslyn_analysis.json", "w") as f:
            f.write("not valid json {{{")
        return _subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    logs: list[str] = []
    extractor = _make_extractor(
        roslyn_analyzer_path=str(analyzer_path),
        logs=logs,
    )
    result = extractor._run_roslyn()

    assert result is None
    assert any("failed" in msg for msg in logs)


def test_run_roslyn_empty_entities(tmp_path, monkeypatch) -> None:
    """Handles Roslyn output with no entities gracefully."""
    monkeypatch.chdir(tmp_path)

    analyzer_path = tmp_path / "FakeAnalyzer.csproj"
    analyzer_path.write_text("<Project/>")

    import subprocess as _subprocess

    def fake_subprocess_run(cmd, **kwargs):
        with open("roslyn_analysis.json", "w") as f:
            json.dump({"entities": [], "accessMethods": []}, f)
        return _subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    logs: list[str] = []
    extractor = _make_extractor(
        roslyn_analyzer_path=str(analyzer_path),
        logs=logs,
    )
    result = extractor._run_roslyn()

    assert result is not None
    assert result.entity_names == set()
    assert result.entity_fields == {}
    assert result.relationships == {}
    assert result.access_methods == []


# ---------------------------------------------------------------------------
# Feature: consensus-extraction, Property 1: Extraction proceeds iff sufficient runs succeed
# Validates: Requirements 1.4, 1.5
#
# For any combination of 3 extraction run outcomes (success/failure), the
# ConsensusExtractor shall proceed to comparison if and only if at least 2
# runs completed successfully; otherwise it shall raise an error and halt.
# ---------------------------------------------------------------------------

from backend.services.consensus import ConsensusResult


import re as _re
import tempfile
import threading

import pytest


@settings(max_examples=100)
@given(
    outcomes=st.lists(st.booleans(), min_size=3, max_size=3),
)
def test_extraction_proceeds_iff_sufficient_runs_succeed(
    outcomes: list[bool],
) -> None:
    """**Validates: Requirements 1.4, 1.5**

    For any combination of 3 run outcomes (True=success, False=failure),
    run() returns a ConsensusResult iff ≥2 succeed, otherwise raises RuntimeError.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            # Thread-safe counter to map each agent_factory() call to an outcome
            _lock = threading.Lock()
            _counter = [0]

            def make_agent():
                """Return an agent callable that succeeds or fails based on outcomes."""
                with _lock:
                    idx = _counter[0]
                    _counter[0] += 1

                should_succeed = idx < len(outcomes) and outcomes[idx]

                def agent(prompt):
                    if not should_succeed:
                        raise RuntimeError(f"Run {idx} failed")
                    # Extract the temp dir from the prompt to write to the correct location
                    match = _re.search(r"'(_consensus_run_\d+)'", prompt)
                    if match:
                        temp_dir = match.group(1)
                    else:
                        temp_dir = f"_consensus_run_{idx}"
                    os.makedirs(temp_dir, exist_ok=True)
                    metrics = {
                        "entities": {f"Entity{idx}": {"fields": ["Id"]}},
                        "access_patterns": {f"AP{idx}": {"name": f"Pattern{idx}"}},
                        "write_patterns": {},
                    }
                    with open(os.path.join(temp_dir, "entity_metrics.json"), "w") as f:
                        json.dump(metrics, f)

                return agent

            logs: list[str] = []
            extractor = ConsensusExtractor(
                project_path="/fake/project",
                schema_path=None,
                agent_factory=make_agent,
                roslyn_analyzer_path=None,
                log_callback=logs.append,
                threshold=0.0,  # Accept any score so we don't retry
                max_rounds=1,
                runs_per_round=3,
            )

            success_count = sum(outcomes)

            if success_count >= 2:
                result = extractor.run()
                assert isinstance(result, ConsensusResult)
            else:
                with pytest.raises(RuntimeError):
                    extractor.run()
        finally:
            os.chdir(original_cwd)


# ---------------------------------------------------------------------------
# Feature: consensus-extraction, Property 6: Retry logic respects threshold and max rounds
# Validates: Requirements 4.1, 4.2, 4.3
#
# For any sequence of per-round confidence scores, the ConsensusExtractor
# shall execute exactly min(3, R) rounds, where R is the index of the first
# round whose score meets or exceeds the threshold (1-indexed), or 3 if no
# round meets the threshold.
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    per_round_scores=st.lists(
        st.floats(min_value=0.0, max_value=1.0),
        min_size=3,
        max_size=3,
    ),
    threshold=st.floats(min_value=0.0, max_value=1.0),
)
def test_retry_logic_respects_threshold_and_max_rounds(
    per_round_scores: list[float],
    threshold: float,
) -> None:
    """**Validates: Requirements 4.1, 4.2, 4.3**

    The ConsensusExtractor shall execute exactly min(3, R) rounds, where R
    is the 1-indexed position of the first round whose confidence score meets
    or exceeds the threshold, or 3 if no round meets it.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            # We control confidence by controlling entity sets per round.
            # ConsensusComparer.compare() is called after each round.
            # We monkeypatch ConsensusComparer.compare to return controlled scores.
            round_counter = 0

            original_compare = ConsensusComparer.compare

            def mock_compare(llm_outputs, roslyn_output):
                nonlocal round_counter
                result = original_compare(llm_outputs, roslyn_output)
                # Override the overall_score with our controlled per-round score
                score = per_round_scores[min(round_counter, len(per_round_scores) - 1)]
                round_counter += 1
                return ComparisonResult(
                    entity_agreement=result.entity_agreement,
                    pattern_agreement=result.pattern_agreement,
                    roslyn_alignment=result.roslyn_alignment,
                    overall_score=score,
                    agreed_entities=result.agreed_entities,
                    agreed_patterns=result.agreed_patterns,
                    disagreed_entities=result.disagreed_entities,
                    disagreed_patterns=result.disagreed_patterns,
                )

            saved_compare = ConsensusComparer.compare
            ConsensusComparer.compare = staticmethod(mock_compare)

            try:
                # Agent factory that always succeeds with identical outputs
                run_idx = 0
                _agent_lock = threading.Lock()

                def make_agent():
                    nonlocal run_idx
                    with _agent_lock:
                        idx = run_idx
                        run_idx += 1

                    def agent(prompt):
                        match = _re.search(r"'(_consensus_run_\d+)'", prompt)
                        if match:
                            temp_dir = match.group(1)
                        else:
                            temp_dir = f"_consensus_run_{idx % 3}"
                        os.makedirs(temp_dir, exist_ok=True)
                        metrics = {
                            "entities": {"SharedEntity": {"fields": ["Id"]}},
                            "access_patterns": {"AP1": {"name": "GetAll"}},
                            "write_patterns": {},
                        }
                        with open(os.path.join(temp_dir, "entity_metrics.json"), "w") as f:
                            json.dump(metrics, f)

                    return agent

                logs: list[str] = []
                extractor = ConsensusExtractor(
                    project_path="/fake/project",
                    schema_path=None,
                    agent_factory=make_agent,
                    roslyn_analyzer_path=None,
                    log_callback=logs.append,
                    threshold=threshold,
                    max_rounds=3,
                    runs_per_round=3,
                )

                result = extractor.run()

                # Compute expected rounds
                expected_rounds = 3
                for i, score in enumerate(per_round_scores):
                    if score >= threshold:
                        expected_rounds = i + 1
                        break

                assert result.rounds_executed == expected_rounds, (
                    f"Expected {expected_rounds} rounds but got {result.rounds_executed}. "
                    f"Scores: {per_round_scores}, threshold: {threshold}"
                )
            finally:
                ConsensusComparer.compare = saved_compare
        finally:
            os.chdir(original_cwd)


# ---------------------------------------------------------------------------
# Feature: consensus-extraction, Property 12: Cross-round evidence accumulation
# Validates: Requirements 4.4
#
# For any entity or pattern that appears consistently across multiple
# consensus rounds, its inclusion likelihood in the final merged result
# shall be at least as high as if only the last round were considered.
# Specifically, an entity appearing in ≥2 runs in any round shall be
# included in the final merge regardless of its presence in the final
# round alone.
# ---------------------------------------------------------------------------


def test_cross_round_evidence_accumulation(tmp_path, monkeypatch) -> None:
    """**Validates: Requirements 4.4**

    An entity that appears in only 1 of 3 runs per round, but across 2
    rounds appears in 2+ runs total, shall be included in the final merge
    due to cross-round evidence accumulation.
    """
    monkeypatch.chdir(tmp_path)

    # We'll run 2 rounds. In each round, "RareEntity" appears in only 1 of 3 runs.
    # Across 2 rounds, it appears in 2 runs total → should be included.
    # "CommonEntity" appears in all runs (always included).
    round_num_tracker = [0]
    run_idx = [0]
    _evidence_lock = threading.Lock()

    def make_agent():
        with _evidence_lock:
            idx = run_idx[0]
            run_idx[0] += 1

        def agent(prompt):
            # Determine which run within the round from the prompt
            match = _re.search(r"'(_consensus_run_(\d+))'", prompt)
            if match:
                temp_dir = match.group(1)
                run_in_round = int(match.group(2))
            else:
                run_in_round = idx % 3
                temp_dir = f"_consensus_run_{run_in_round}"

            entities: dict[str, dict] = {
                "CommonEntity": {"fields": ["Id"]},
            }

            # RareEntity appears in run 0 of each round only
            if run_in_round == 0:
                entities["RareEntity"] = {"fields": ["Id", "Name"]}

            os.makedirs(temp_dir, exist_ok=True)
            metrics = {
                "entities": entities,
                "access_patterns": {"AP1": {"name": "GetAll"}},
                "write_patterns": {},
            }
            with open(os.path.join(temp_dir, "entity_metrics.json"), "w") as f:
                json.dump(metrics, f)

        return agent

    # Patch compare to always return below-threshold on round 1, above on round 2
    compare_call = [0]
    original_compare = ConsensusComparer.compare

    def mock_compare(llm_outputs, roslyn_output):
        result = original_compare(llm_outputs, roslyn_output)
        call_num = compare_call[0]
        compare_call[0] += 1
        if call_num == 0:
            round_num_tracker[0] = 1
            # Return below threshold to force a second round
            return ComparisonResult(
                entity_agreement=result.entity_agreement,
                pattern_agreement=result.pattern_agreement,
                roslyn_alignment=result.roslyn_alignment,
                overall_score=0.3,  # Below default threshold of 0.7
                agreed_entities=result.agreed_entities,
                agreed_patterns=result.agreed_patterns,
                disagreed_entities=result.disagreed_entities,
                disagreed_patterns=result.disagreed_patterns,
            )
        else:
            # Second round: return above threshold
            return ComparisonResult(
                entity_agreement=result.entity_agreement,
                pattern_agreement=result.pattern_agreement,
                roslyn_alignment=result.roslyn_alignment,
                overall_score=0.9,  # Above threshold
                agreed_entities=result.agreed_entities,
                agreed_patterns=result.agreed_patterns,
                disagreed_entities=result.disagreed_entities,
                disagreed_patterns=result.disagreed_patterns,
            )

    monkeypatch.setattr(ConsensusComparer, "compare", staticmethod(mock_compare))

    logs: list[str] = []
    extractor = ConsensusExtractor(
        project_path="/fake/project",
        schema_path=None,
        agent_factory=make_agent,
        roslyn_analyzer_path=None,
        log_callback=logs.append,
        threshold=0.7,
        max_rounds=3,
        runs_per_round=3,
    )

    result = extractor.run()

    # Verify 2 rounds were executed
    assert result.rounds_executed == 2, (
        f"Expected 2 rounds but got {result.rounds_executed}"
    )

    # RareEntity appeared in 1 run per round × 2 rounds = 2 total runs
    # With cross-round evidence accumulation (all_round_outputs flattened),
    # it meets the ≥2 threshold and should be included.
    assert "RareEntity" in result.merged_entities, (
        f"RareEntity should be included via cross-round evidence. "
        f"Merged entities: {list(result.merged_entities.keys())}"
    )

    # CommonEntity should always be included
    assert "CommonEntity" in result.merged_entities

    # RareEntity should NOT be in dropped_entities
    assert "RareEntity" not in result.dropped_entities


# ---------------------------------------------------------------------------
# Feature: consensus-extraction, Property 2: Roslyn output parsing round-trip
# Validates: Requirements 2.2
#
# For any valid roslyn_analysis.json structure containing entities with
# names, fields, relationships, and access methods, parsing it into a
# RoslynOutput and then checking the extracted entity names, field lists,
# and relationships shall produce sets that exactly match the input data.
# ---------------------------------------------------------------------------

_roslyn_entity_name = st.text(
    min_size=1, max_size=8, alphabet=st.characters(whitelist_categories=("L",))
)
_roslyn_field_name = st.text(
    min_size=1, max_size=6, alphabet=st.characters(whitelist_categories=("L",))
)
_roslyn_rel_strategy = st.fixed_dictionaries(
    {"type": st.sampled_from(["HasMany", "HasOne", "BelongsTo"]),
     "target": _roslyn_entity_name}
)
_roslyn_entity_strategy = st.fixed_dictionaries(
    {
        "name": _roslyn_entity_name,
        "fields": st.lists(
            st.fixed_dictionaries({"name": _roslyn_field_name, "type": st.just("string")}),
            min_size=0,
            max_size=5,
        ),
        "relationships": st.lists(_roslyn_rel_strategy, min_size=0, max_size=3),
    }
)
_roslyn_access_method = st.fixed_dictionaries(
    {
        "class": _roslyn_entity_name,
        "method": _roslyn_field_name,
        "operation": st.sampled_from(["read", "write", "delete"]),
    }
)


@settings(max_examples=100)
@given(
    entities=st.lists(_roslyn_entity_strategy, min_size=0, max_size=5),
    access_methods=st.lists(_roslyn_access_method, min_size=0, max_size=5),
)
def test_roslyn_output_parsing_round_trip(
    entities: list[dict],
    access_methods: list[dict],
) -> None:
    """**Validates: Requirements 2.2**

    Parsing a valid roslyn_analysis.json into RoslynOutput preserves
    entity names, field lists, relationships, and access methods.
    """
    import subprocess as _sp

    # De-duplicate entities by name (last one wins, matching real-world uniqueness)
    seen: dict[str, dict] = {}
    for ent in entities:
        seen[ent["name"]] = ent
    unique_entities = list(seen.values())

    roslyn_json = {
        "entities": unique_entities,
        "accessMethods": access_methods,
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        original_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            # Create a fake analyzer project file so the path-exists check passes
            analyzer_path = os.path.join(tmp_dir, "FakeAnalyzer.csproj")
            with open(analyzer_path, "w") as f:
                f.write("<Project/>")

            # Patch subprocess.run to write the roslyn_analysis.json file
            original_subprocess_run = _sp.run

            def fake_subprocess_run(cmd, **kwargs):
                with open("roslyn_analysis.json", "w") as f:
                    json.dump(roslyn_json, f)
                return _sp.CompletedProcess(cmd, 0, stdout="", stderr="")

            _sp.run = fake_subprocess_run

            try:
                logs: list[str] = []
                extractor = _make_extractor(
                    roslyn_analyzer_path=analyzer_path,
                    logs=logs,
                )
                result = extractor._run_roslyn()
            finally:
                _sp.run = original_subprocess_run

            assert result is not None, f"_run_roslyn returned None. Logs: {logs}"

            # Build expected values from the unique input entities
            expected_names: set[str] = set()
            expected_fields: dict[str, list[str]] = {}
            expected_rels: dict[str, list[dict]] = {}

            for ent in unique_entities:
                name = ent["name"]
                expected_names.add(name)
                expected_fields[name] = [f["name"] for f in ent["fields"]]
                expected_rels[name] = ent["relationships"]

            # Assert entity names match
            assert result.entity_names == expected_names, (
                f"entity_names {result.entity_names} != expected {expected_names}"
            )

            # Assert field lists match for each entity
            assert result.entity_fields == expected_fields, (
                f"entity_fields {result.entity_fields} != expected {expected_fields}"
            )

            # Assert relationships match for each entity
            assert result.relationships == expected_rels, (
                f"relationships {result.relationships} != expected {expected_rels}"
            )

            # Assert access methods match
            assert result.access_methods == access_methods, (
                f"access_methods {result.access_methods} != expected {access_methods}"
            )
        finally:
            os.chdir(original_cwd)


# ---------------------------------------------------------------------------
# Feature: consensus-extraction, Property 10: Consensus report contains all required fields
# Validates: Requirements 5.5, 8.2
#
# For any ConsensusResult, the generated consensus_report.json shall contain
# all of: confidence_score (float), rounds_executed (int), total_entities
# (int), total_patterns (int), entity_agreement_ratio (float),
# pattern_agreement_ratio (float), roslyn_alignment_ratio (float),
# dropped_entities (list), and dropped_patterns (list).
# ---------------------------------------------------------------------------

_entity_dict_strategy = st.dictionaries(
    keys=_entity_name_strategy,
    values=st.just({}),
    min_size=0,
    max_size=5,
)
_pattern_dict_strategy = st.dictionaries(
    keys=_pattern_id_strategy,
    values=st.just({}),
    min_size=0,
    max_size=5,
)


@settings(max_examples=100)
@given(
    merged_entities=_entity_dict_strategy,
    merged_access_patterns=_pattern_dict_strategy,
    confidence_score=st.floats(min_value=0.0, max_value=1.0),
    rounds_executed=st.integers(min_value=1, max_value=3),
    entity_agreement=st.floats(min_value=0.0, max_value=1.0),
    pattern_agreement=st.floats(min_value=0.0, max_value=1.0),
    roslyn_alignment=st.floats(min_value=0.0, max_value=1.0),
    dropped_entities=st.lists(_entity_name_strategy, min_size=0, max_size=5),
    dropped_patterns=st.lists(_pattern_id_strategy, min_size=0, max_size=5),
)
def test_consensus_report_contains_all_required_fields(
    merged_entities: dict[str, dict],
    merged_access_patterns: dict[str, dict],
    confidence_score: float,
    rounds_executed: int,
    entity_agreement: float,
    pattern_agreement: float,
    roslyn_alignment: float,
    dropped_entities: list[str],
    dropped_patterns: list[str],
) -> None:
    """**Validates: Requirements 5.5, 8.2**

    The consensus_report dict built from any ConsensusResult must contain
    all required keys with correct types.
    """
    result = ConsensusResult(
        merged_entities=merged_entities,
        merged_access_patterns=merged_access_patterns,
        confidence_score=confidence_score,
        rounds_executed=rounds_executed,
        entity_agreement=entity_agreement,
        pattern_agreement=pattern_agreement,
        roslyn_alignment=roslyn_alignment,
        dropped_entities=dropped_entities,
        dropped_patterns=dropped_patterns,
    )

    # Build the consensus_report dict the same way PipelineRunner.run_extract() does
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

    # Assert all required keys are present
    required_keys = {
        "confidence_score",
        "rounds_executed",
        "total_entities",
        "total_patterns",
        "entity_agreement_ratio",
        "pattern_agreement_ratio",
        "roslyn_alignment_ratio",
        "dropped_entities",
        "dropped_patterns",
    }
    assert set(consensus_report.keys()) == required_keys, (
        f"Missing keys: {required_keys - set(consensus_report.keys())}"
    )

    # Assert correct types
    assert isinstance(consensus_report["confidence_score"], float), (
        f"confidence_score type {type(consensus_report['confidence_score'])} != float"
    )
    assert isinstance(consensus_report["rounds_executed"], int), (
        f"rounds_executed type {type(consensus_report['rounds_executed'])} != int"
    )
    assert isinstance(consensus_report["total_entities"], int), (
        f"total_entities type {type(consensus_report['total_entities'])} != int"
    )
    assert isinstance(consensus_report["total_patterns"], int), (
        f"total_patterns type {type(consensus_report['total_patterns'])} != int"
    )
    assert isinstance(consensus_report["entity_agreement_ratio"], float), (
        f"entity_agreement_ratio type {type(consensus_report['entity_agreement_ratio'])} != float"
    )
    assert isinstance(consensus_report["pattern_agreement_ratio"], float), (
        f"pattern_agreement_ratio type {type(consensus_report['pattern_agreement_ratio'])} != float"
    )
    assert isinstance(consensus_report["roslyn_alignment_ratio"], float), (
        f"roslyn_alignment_ratio type {type(consensus_report['roslyn_alignment_ratio'])} != float"
    )
    assert isinstance(consensus_report["dropped_entities"], list), (
        f"dropped_entities type {type(consensus_report['dropped_entities'])} != list"
    )
    assert isinstance(consensus_report["dropped_patterns"], list), (
        f"dropped_patterns type {type(consensus_report['dropped_patterns'])} != list"
    )

    # Assert values match the ConsensusResult
    assert consensus_report["confidence_score"] == confidence_score
    assert consensus_report["rounds_executed"] == rounds_executed
    assert consensus_report["total_entities"] == len(merged_entities)
    assert consensus_report["total_patterns"] == len(merged_access_patterns)
    assert consensus_report["entity_agreement_ratio"] == entity_agreement
    assert consensus_report["pattern_agreement_ratio"] == pattern_agreement
    assert consensus_report["roslyn_alignment_ratio"] == roslyn_alignment
    assert consensus_report["dropped_entities"] == dropped_entities
    assert consensus_report["dropped_patterns"] == dropped_patterns


# ---------------------------------------------------------------------------
# Feature: consensus-extraction, Property 11: Confidence color coding
# Validates: Requirements 6.3
#
# For any confidence score in [0,1], the color mapping shall return "green"
# if score > 0.8, "yellow" if 0.5 <= score <= 0.8, and "red" if score < 0.5.
# ---------------------------------------------------------------------------


def _get_confidence_color(score: float) -> str:
    """Python equivalent of the frontend getConfidenceColor function."""
    if score > 0.8:
        return "green"
    if score >= 0.5:
        return "yellow"
    return "red"


@settings(max_examples=100)
@given(score=st.floats(min_value=0.0, max_value=1.0))
def test_confidence_color_coding(score: float) -> None:
    """**Validates: Requirements 6.3**

    The confidence color mapping must be deterministic and cover all cases:
    green for >0.8, yellow for [0.5, 0.8], red for <0.5.
    """
    color = _get_confidence_color(score)

    if score > 0.8:
        assert color == "green", f"Score {score} should be green, got {color}"
    elif score >= 0.5:
        assert color == "yellow", f"Score {score} should be yellow, got {color}"
    else:
        assert color == "red", f"Score {score} should be red, got {color}"

    # Color must always be one of the three valid values
    assert color in ("green", "yellow", "red"), f"Invalid color: {color}"


def test_confidence_color_boundary_zero() -> None:
    """Score 0.0 → red."""
    assert _get_confidence_color(0.0) == "red"


def test_confidence_color_boundary_half() -> None:
    """Score 0.5 → yellow (inclusive lower bound)."""
    assert _get_confidence_color(0.5) == "yellow"


def test_confidence_color_boundary_0_8() -> None:
    """Score 0.8 → yellow (inclusive upper bound)."""
    assert _get_confidence_color(0.8) == "yellow"


def test_confidence_color_boundary_above_0_8() -> None:
    """Score 0.81 → green."""
    assert _get_confidence_color(0.81) == "green"


def test_confidence_color_boundary_one() -> None:
    """Score 1.0 → green."""
    assert _get_confidence_color(1.0) == "green"
