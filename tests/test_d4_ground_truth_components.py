from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.ground_truth_addendum.components import (
    evaluate_unknown_context,
    summarize_observed_load,
    validate_component,
    validate_component_claim,
)
from src.ground_truth_addendum.contracts import ACTIVITY_CATALOG_VERSION, COMPONENT_VERSION
from src.ground_truth_addendum.migration_v2_to_v3 import (
    materialize_membership_projection_v3,
    project_memberships_v2_as_recorded_components,
)
from src.ground_truth_addendum.store import GroundTruthStore, LockedTestAccessError


RUNNER = "synthetic_component_runner"
SOURCE_1 = "synthetic_component_one.json"
SOURCE_2 = "synthetic_component_two.json"
SHA_1 = "1" * 64
SHA_2 = "2" * 64
WORKOUT = "10000000-0000-4000-8000-000000000001"
GROUP_THREAD = "10000000-0000-4000-8000-000000000002"
GROUP_DECISION = "10000000-0000-4000-8000-000000000003"
MEMBER_THREAD_1 = "10000000-0000-4000-8000-000000000004"
MEMBER_THREAD_2 = "10000000-0000-4000-8000-000000000005"
MEMBERSHIP_1 = "10000000-0000-4000-8000-000000000006"
MEMBERSHIP_2 = "10000000-0000-4000-8000-000000000007"
EVIDENCE = "10000000-0000-4000-8000-000000000008"
EVIDENCE_2 = "10000000-0000-4000-8000-000000000009"
C_RECORDED = "20000000-0000-4000-8000-000000000001"
C_UNRECORDED = "20000000-0000-4000-8000-000000000002"
C_UNKNOWN = "20000000-0000-4000-8000-000000000003"
D_RECORDED = "30000000-0000-4000-8000-000000000001"
D_UNRECORDED = "30000000-0000-4000-8000-000000000002"
D_UNKNOWN = "30000000-0000-4000-8000-000000000003"
CLAIM_THREAD = "40000000-0000-4000-8000-000000000001"
CLAIM_1 = "50000000-0000-4000-8000-000000000001"
CLAIM_2 = "50000000-0000-4000-8000-000000000002"
TS = "2024-01-01T00:00:00Z"


@pytest.fixture
def store(tmp_path):
    with GroundTruthStore(tmp_path / "synthetic_components.sqlite") as value:
        value.initialize()
        for source, sha, day in ((SOURCE_1, SHA_1, "2023-01-01"), (SOURCE_2, SHA_2, "2025-01-02")):
            value.add_source_session({
                "runner_id": RUNNER, "source_file": source, "source_sha256": sha,
                "session_date": day, "source_manifest": "f" * 64,
            })
        value.create_thread(
            runner_id=RUNNER, target_kind="workout_group", target_key=WORKOUT,
            opened_by="synthetic", opened_at=TS, annotation_thread_id=GROUP_THREAD,
        )
        value.add_workout_group({
            "group_decision_id": GROUP_DECISION, "workout_group_id": WORKOUT,
            "annotation_thread_id": GROUP_THREAD, "revision": 1,
            "supersedes_group_decision_id": None, "decision_kind": "annotation",
            "runner_id": RUNNER, "group_status": "confirmed", "evidence_level": "verified",
            "evidence_types": ["synthetic_fixture"], "evidence_reference": "synthetic://group",
            "decision_timestamp": TS, "label_available_at": TS, "author_id": "synthetic",
            "author_role": "test", "code_commit": "synthetic-test",
        })
        for evidence_id, locator in ((EVIDENCE, "synthetic://evidence/1"), (EVIDENCE_2, "synthetic://evidence/2")):
            value.add_evidence_record_v2({
                "evidence_id": evidence_id, "runner_id": RUNNER,
                "evidence_type_id": "synthetic_fixture", "source_system": "synthetic",
                "source_locator": locator, "source_content_sha256": None,
                "evidence_observed_at": "2023-01-01T00:00:00Z", "recorded_at": TS,
                "scientific_purpose": "D4.1 synthetic component fixture",
                "data_minimization_note": "synthetic only", "code_commit": "synthetic-test",
            })
        for thread_id, membership_id, source, sha, order, evidence_id in (
            (MEMBER_THREAD_1, MEMBERSHIP_1, SOURCE_1, SHA_1, 1, EVIDENCE),
            (MEMBER_THREAD_2, MEMBERSHIP_2, SOURCE_2, SHA_2, 2, EVIDENCE_2),
        ):
            value.create_claim_thread_v2(
                runner_id=RUNNER, subject_kind="workout_membership",
                subject_key=f"{WORKOUT}|{source}", opened_by="synthetic", opened_at=TS,
                annotation_thread_id=thread_id,
            )
            value.add_workout_membership_v2({
                "membership_decision_id": membership_id, "annotation_thread_id": thread_id,
                "revision": 1, "supersedes_membership_decision_id": None,
                "decision_kind": "annotation", "runner_id": RUNNER,
                "workout_group_id": WORKOUT, "group_decision_id": GROUP_DECISION,
                "source_file": source, "source_sha256": sha, "membership_state": "included",
                "component_order": order, "component_role": "main_set",
                "claim_kind": "human_report", "evidence_level": "reported",
                "author_id": "synthetic", "author_role": "test", "rationale": "synthetic",
                "uncertainty_reason": None, "evidence_observed_at": "2023-01-01T00:00:00Z",
                "decision_timestamp": TS, "effective_from": "2023-01-01T00:00:00Z",
                "label_available_at": TS, "code_commit": "synthetic-test",
            })
            value.link_membership_evidence_v2(
                membership_decision_id=membership_id, evidence_id=evidence_id, support_role="support"
            )
        yield value


def component(state: str, *, order: int = 1, decision: str | None = None,
              component_id: str | None = None, membership: str | None = None):
    if state == "recorded":
        decision, component_id, membership = decision or D_RECORDED, component_id or C_RECORDED, membership or MEMBERSHIP_1
        activity = catalog = uncertainty = None
    elif state == "unrecorded":
        decision, component_id, membership = decision or D_UNRECORDED, component_id or C_UNRECORDED, None
        activity, catalog, uncertainty = "running_drills", ACTIVITY_CATALOG_VERSION, None
    else:
        decision, component_id, membership = decision or D_UNKNOWN, component_id or C_UNKNOWN, None
        activity = catalog = None; uncertainty = "synthetic unknown context"
    return {
        "component_decision_id": decision, "component_id": component_id,
        "supersedes_component_decision_id": None, "decision_kind": "annotation",
        "runner_id": RUNNER, "workout_group_id": WORKOUT, "group_decision_id": GROUP_DECISION,
        "component_order": order, "recording_state": state,
        "membership_decision_id": membership, "activity_catalog_version": catalog,
        "activity_type_id": activity, "component_role": None,
        "start_time": None, "end_time": None, "temporal_precision": "unknown",
        "duration_s": None, "duration_basis": "unknown", "claim_kind": "human_report",
        "evidence_level": "reported", "author_id": "synthetic", "author_role": "test",
        "evidence_observed_at": "2023-01-01T00:00:00Z", "decision_timestamp": TS,
        "effective_from": "2023-01-01T00:00:00Z", "label_available_at": TS,
        "uncertainty_reason": uncertainty, "rationale": "synthetic only",
        "code_commit": "synthetic-test", "contract_version": COMPONENT_VERSION,
    }


def claim(*, dimension="repetition_count_intended", claim_id=CLAIM_1,
          thread=CLAIM_THREAD, status="asserted", kind="integer", integer=10,
          numeric=None, lower=None, upper=None, unit=None, qualifier="exact",
          item_index=None, level="reported", revision=1, supersedes=None,
          available=TS):
    return {
        "claim_id": claim_id, "annotation_thread_id": thread, "revision": revision,
        "supersedes_claim_id": supersedes, "decision_kind": "annotation" if revision == 1 else "correction",
        "runner_id": RUNNER, "component_id": C_RECORDED, "dimension_name": dimension,
        "item_index": item_index, "claim_status": status, "value_kind": kind,
        "integer_value": integer, "numeric_value": numeric, "text_value": None,
        "range_lower_value": lower, "range_upper_value": upper, "unit": unit,
        "value_qualifier": qualifier, "claim_kind": "human_report",
        "evidence_level": level, "author_id": "synthetic", "author_role": "test",
        "rationale": "synthetic only", "uncertainty_reason": None,
        "evidence_observed_at": "2023-01-01T00:00:00Z", "decision_timestamp": TS,
        "effective_from": "2023-01-01T00:00:00Z", "label_available_at": available,
        "code_commit": "synthetic-test", "contract_version": COMPONENT_VERSION,
    }


def add_component(store, row, evidence_id=EVIDENCE):
    store.add_workout_component_v3(row, evidence_links=[{
        "evidence_id": evidence_id, "support_role": "support", "rationale": "synthetic"
    }])


def add_claim(store, row, evidence_id=EVIDENCE):
    store.add_component_claim_v3(row, evidence_links=[{
        "evidence_id": evidence_id, "support_role": "support", "rationale": "synthetic"
    }])


def test_catalog_is_versioned_and_unknown_is_not_an_activity(store):
    values = {row[0] for row in store.connection.execute(
        "SELECT activity_type_id FROM ground_truth_activity_type_catalog_v3"
    )}
    assert "running_drills" in values and "unknown" not in values


def test_recorded_component_is_valid_and_derives_session_identity(store):
    add_component(store, component("recorded"))
    row = store.connection.execute(
        """SELECT m.source_file,m.source_sha256 FROM ground_truth_workout_components_v3 c
           JOIN ground_truth_workout_memberships_v2 m ON m.membership_decision_id=c.membership_decision_id"""
    ).fetchone()
    assert tuple(row) == (SOURCE_1, SHA_1)


@pytest.mark.parametrize("mutation,message", [
    ({"membership_decision_id": None}, "requires membership"),
    ({"activity_type_id": "running_drills"}, "derive activity"),
])
def test_invalid_recorded_components_are_rejected(mutation, message):
    row = component("recorded"); row.update(mutation)
    with pytest.raises(ValueError, match=message): validate_component(row)


def test_recorded_component_with_cross_runner_membership_is_rejected(store):
    row = component("recorded"); row["runner_id"] = "synthetic_other_runner"
    with pytest.raises(sqlite3.IntegrityError, match="identity mismatch"):
        add_component(store, row)


def test_unrecorded_running_drills_is_valid_and_has_no_instrumental_identity(store):
    add_component(store, component("unrecorded"))
    columns = {row[1] for row in store.connection.execute("PRAGMA table_info(ground_truth_workout_components_v3)")}
    assert "source_file" not in columns and "source_sha256" not in columns


@pytest.mark.parametrize("mutation,message", [
    ({"membership_decision_id": MEMBERSHIP_1}, "cannot reference membership"),
    ({"activity_type_id": None}, "requires activity_type"),
    ({"activity_type_id": "unknown"}, "unsupported activity_type"),
])
def test_invalid_unrecorded_components_are_rejected(mutation, message):
    row = component("unrecorded"); row.update(mutation)
    with pytest.raises(ValueError, match=message): validate_component(row)


def test_unknown_component_is_valid(store):
    add_component(store, component("unknown"))
    assert store.connection.execute("SELECT recording_state FROM ground_truth_workout_components_v3").fetchone()[0] == "unknown"


@pytest.mark.parametrize("mutation,message", [
    ({"membership_decision_id": MEMBERSHIP_1}, "cannot reference membership"),
    ({"activity_type_id": "rest"}, "cannot assert activity_type"),
    ({"component_role": "recovery_segment"}, "cannot assert component_role"),
    ({"uncertainty_reason": None}, "requires uncertainty_reason"),
])
def test_invalid_unknown_components_are_rejected(mutation, message):
    row = component("unknown"); row.update(mutation)
    with pytest.raises(ValueError, match=message): validate_component(row)


def test_temporal_gap_does_not_create_component(store):
    before = store.connection.execute("SELECT COUNT(*) FROM ground_truth_workout_components_v3").fetchone()[0]
    projected = project_memberships_v2_as_recorded_components(store, knowledge_cutoff=TS)
    after = store.connection.execute("SELECT COUNT(*) FROM ground_truth_workout_components_v3").fetchone()[0]
    assert len(projected) == 2 and before == after == 0


def test_component_requires_evidence(store):
    with pytest.raises(ValueError, match="requires evidence"):
        store.add_workout_component_v3(component("unrecorded"), evidence_links=[])


def test_component_and_claim_history_are_append_only(store):
    add_component(store, component("recorded"))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.connection.execute("UPDATE ground_truth_workout_components_v3 SET component_order=2")
    store.connection.rollback()


@pytest.mark.parametrize("dimension", [
    "repetition_count_intended", "repetition_count_executed", "repetition_count_observed",
])
def test_count_dimensions_are_distinct_and_typed(dimension):
    validate_component_claim(claim(dimension=dimension))


@pytest.mark.parametrize("dimension", [
    "repetition_distance_nominal", "repetition_distance_executed",
])
def test_distance_dimensions_accept_approximate_nominal_or_execution(dimension):
    validate_component_claim(claim(
        dimension=dimension, kind="numeric", integer=None, numeric=100.0,
        unit="m", qualifier="approximate",
    ))


def test_individual_measured_distance_requires_item_index():
    row = claim(
        dimension="repetition_distance_measured", kind="numeric", integer=None,
        numeric=0.98, unit="km", qualifier="exact",
    )
    with pytest.raises(ValueError, match="requires item_index"): validate_component_claim(row)
    row["item_index"] = 1; validate_component_claim(row)


@pytest.mark.parametrize("dimension", ["repetition_count_observed", "repetition_distance_measured"])
def test_observed_or_measured_unknown_is_valid(dimension):
    row = claim(dimension=dimension, status="unknown", kind="none", integer=None, qualifier=None)
    validate_component_claim(row)


@pytest.mark.parametrize("mutation", [
    {"numeric_value": 1.0}, {"text_value": "opaque"}, {"unit": "m"},
    {"value_qualifier": "approximate"},
])
def test_unknown_claim_cannot_carry_value(mutation):
    row = claim(status="unknown", kind="none", integer=None, qualifier=None); row.update(mutation)
    with pytest.raises(ValueError): validate_component_claim(row)


@pytest.mark.parametrize("row", [
    claim(kind="integer", integer=-1),
    claim(kind="integer", integer=10, unit="m"),
    claim(dimension="repetition_distance_nominal", kind="numeric", integer=None, numeric=100, unit="s", qualifier="exact"),
    claim(dimension="repetition_distance_nominal", kind="range", integer=None, lower=110, upper=90, unit="m", qualifier="range"),
    claim(dimension="repetition_distance_nominal", kind="range", integer=None, lower=90, upper=110, unit="m", qualifier="approximate"),
])
def test_semantically_impossible_typed_values_are_rejected(row):
    with pytest.raises(ValueError): validate_component_claim(row)


def test_case_d_intended_can_coexist_with_unknown_observation(store):
    add_component(store, component("recorded"))
    t1 = store.create_component_claim_thread_v3(
        runner_id=RUNNER, component_id=C_RECORDED, dimension_name="repetition_count_intended",
        opened_by="synthetic", opened_at=TS, annotation_thread_id=CLAIM_THREAD,
    )
    add_claim(store, claim(thread=t1))
    t2 = store.create_component_claim_thread_v3(
        runner_id=RUNNER, component_id=C_RECORDED, dimension_name="repetition_count_observed",
        opened_by="synthetic", opened_at=TS,
    )
    add_claim(store, claim(
        claim_id="50000000-0000-4000-8000-000000000003", thread=t2,
        dimension="repetition_count_observed", status="unknown", kind="none",
        integer=None, qualifier=None,
    ))
    assert len(store.latest_component_claims_as_of_v3(TS, purpose="technical_integrity")) == 2


def test_case_e_six_individual_measurements_coexist(store):
    add_component(store, component("recorded"))
    for index, distance in enumerate((0.98, 1.01, 1.03, 0.99, 1.00, 1.02), 1):
        thread_id = f"60000000-0000-4000-8000-{index:012d}"
        claim_id = f"70000000-0000-4000-8000-{index:012d}"
        store.create_component_claim_thread_v3(
            runner_id=RUNNER, component_id=C_RECORDED,
            dimension_name="repetition_distance_measured", item_index=index,
            opened_by="synthetic", opened_at=TS, annotation_thread_id=thread_id,
        )
        add_claim(store, claim(
            claim_id=claim_id, thread=thread_id, dimension="repetition_distance_measured",
            kind="numeric", integer=None, numeric=distance, unit="km", qualifier="exact",
            item_index=index, level="verified",
        ))
    assert len(store.latest_component_claims_as_of_v3(TS, purpose="technical_integrity")) == 6


def test_claim_as_of_hides_retrospective_evidence(store):
    add_component(store, component("recorded"))
    store.create_component_claim_thread_v3(
        runner_id=RUNNER, component_id=C_RECORDED, dimension_name="repetition_count_intended",
        opened_by="synthetic", opened_at=TS, annotation_thread_id=CLAIM_THREAD,
    )
    row = claim(available="2026-01-01T00:00:00Z"); row["decision_timestamp"] = "2026-01-01T00:00:00Z"
    add_claim(store, row)
    assert store.latest_component_claims_as_of_v3("2025-01-01T00:00:00Z", purpose="technical_integrity") == []
    assert len(store.latest_component_claims_as_of_v3("2026-01-01T00:00:00Z", purpose="technical_integrity")) == 1


def test_component_label_cannot_be_epistemically_backdated(store):
    row = component("recorded")
    row["decision_timestamp"] = "2026-01-01T00:00:00Z"
    row["label_available_at"] = "2025-12-31T23:59:59Z"
    with pytest.raises(ValueError, match="cannot precede decision_timestamp"):
        add_component(store, row)


def test_claim_label_cannot_be_epistemically_backdated(store):
    add_component(store, component("recorded"))
    store.create_component_claim_thread_v3(
        runner_id=RUNNER, component_id=C_RECORDED,
        dimension_name="repetition_count_intended", opened_by="synthetic",
        opened_at=TS, annotation_thread_id=CLAIM_THREAD,
    )
    row = claim(available="2025-12-31T23:59:59Z")
    row["decision_timestamp"] = "2026-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="cannot precede decision_timestamp"):
        add_claim(store, row)


def test_gold_core_excludes_reported_and_extended_preserves_it(store):
    add_component(store, component("recorded"))
    store.create_component_claim_thread_v3(
        runner_id=RUNNER, component_id=C_RECORDED, dimension_name="repetition_count_intended",
        opened_by="synthetic", opened_at=TS, annotation_thread_id=CLAIM_THREAD,
    )
    add_claim(store, claim(level="reported"))
    assert store.build_component_gold_v3(product="gold_core", knowledge_cutoff=TS, purpose="evaluation") == []
    extended = store.build_component_gold_v3(product="gold_extended", knowledge_cutoff=TS, purpose="evaluation")
    assert extended[0]["evidence_levels"] == ["reported"]


@pytest.mark.parametrize("dependency,expected", [
    ("none", "usable"), ("contextual", "usable_with_context_warning"),
    ("structural", "abstain_unknown_context"), ("quantitative", "abstain_unknown_context"),
])
def test_unknown_context_dependency_is_explicit(dependency, expected):
    result = evaluate_unknown_context(
        [component("recorded"), component("unknown", order=2)], dependency=dependency,
        contract_version=COMPONENT_VERSION, knowledge_cutoff=TS,
    )
    assert result["result"] == expected


def test_unknown_load_is_not_zero_load():
    rows = [component("recorded"), component("unknown", order=2)]
    result = summarize_observed_load(rows, {C_RECORDED: 12.5})
    assert result == {
        "observed_load": 12.5, "unobserved_context_present": True,
        "total_load_status": "incomplete", "observed_component_ids": [C_RECORDED],
        "missing_load_component_ids": [C_UNKNOWN], "measured_component_count": 1,
        "total_component_count": 2, "coverage_fraction": 0.5,
    }


def test_missing_recorded_load_is_not_implicit_zero():
    result = summarize_observed_load([component("recorded")], {})
    assert result["observed_load"] == 0
    assert result["missing_load_component_ids"] == [C_RECORDED]
    assert result["total_load_status"] == "incomplete"
    assert result["coverage_fraction"] == 0


def test_explicit_zero_load_is_distinct_from_missing():
    result = summarize_observed_load([component("recorded")], {C_RECORDED: 0.0})
    assert result["observed_load"] == 0
    assert result["missing_load_component_ids"] == []
    assert result["total_load_status"] == "complete"
    assert result["coverage_fraction"] == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, "1"])
def test_nonfinite_or_non_numeric_component_duration_is_rejected(value):
    row = component("unrecorded"); row["duration_basis"] = "estimated"; row["duration_s"] = value
    with pytest.raises(ValueError):
        validate_component(row)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, "1"])
def test_nonfinite_or_non_numeric_claim_value_is_rejected(value):
    row = claim(dimension="repetition_distance_nominal", kind="numeric", integer=None,
                numeric=value, unit="m", qualifier="approximate")
    with pytest.raises(ValueError):
        validate_component_claim(row)


def test_component_correction_preserves_history_and_as_of(store):
    first = component("recorded"); add_component(store, first)
    second = component("recorded", decision="30000000-0000-4000-8000-000000000099")
    second.update({
        "supersedes_component_decision_id": D_RECORDED, "decision_kind": "correction",
        "rationale": "corrected synthetic rationale", "decision_timestamp": "2025-01-01T00:00:00Z",
        "label_available_at": "2025-01-01T00:00:00Z",
    })
    add_component(store, second)
    assert store.connection.execute("SELECT COUNT(*) FROM ground_truth_workout_components_v3").fetchone()[0] == 2
    old = store.latest_workout_components_as_of_v3("2024-06-01T00:00:00Z", purpose="evaluation")
    new = store.latest_workout_components_as_of_v3("2025-06-01T00:00:00Z", purpose="evaluation")
    assert old[0]["component_decision_id"] == D_RECORDED
    assert new[0]["component_decision_id"] == second["component_decision_id"]


def test_component_correction_cannot_change_identity_or_branch(store):
    add_component(store, component("recorded"))
    bad = component("recorded", decision="30000000-0000-4000-8000-000000000098", component_id=C_UNRECORDED)
    bad.update({"supersedes_component_decision_id": D_RECORDED, "decision_kind": "correction"})
    with pytest.raises(sqlite3.IntegrityError, match="supersedes"):
        add_component(store, bad)


def test_asserted_claim_requires_traceable_evidence(store):
    add_component(store, component("recorded"))
    store.create_component_claim_thread_v3(
        runner_id=RUNNER, component_id=C_RECORDED, dimension_name="repetition_count_intended",
        opened_by="synthetic", opened_at=TS, annotation_thread_id=CLAIM_THREAD,
    )
    with pytest.raises(ValueError, match="requires evidence"):
        store.add_component_claim_v3(claim())
    add_claim(store, claim())
    assert store.connection.execute(
        "SELECT COUNT(*) FROM ground_truth_component_claim_evidence_links_v3"
    ).fetchone()[0] == 1


def test_locked_test_cannot_bypass_v3_component_or_claim_queries(store):
    locked_component = component(
        "recorded", order=2, decision="30000000-0000-4000-8000-000000000097",
        component_id="20000000-0000-4000-8000-000000000097", membership=MEMBERSHIP_2,
    )
    add_component(store, locked_component, EVIDENCE_2)
    with pytest.raises(LockedTestAccessError):
        store.latest_workout_components_as_of_v3(TS, purpose="training")
    assert len(store.latest_workout_components_as_of_v3(TS, purpose="evaluation")) == 1


def test_case_a_b_and_c_are_contractually_different():
    case_a = [component("recorded"), component("unrecorded", order=2), component("recorded", order=3)]
    case_b = [component("recorded"), component("unknown", order=2), component("recorded", order=3)]
    case_c = [component("recorded"), component("recorded", order=2)]
    assert [row["recording_state"] for row in case_a] == ["recorded", "unrecorded", "recorded"]
    assert [row["recording_state"] for row in case_b] == ["recorded", "unknown", "recorded"]
    assert len(case_c) == 2


def test_read_only_projection_is_deterministic_and_does_not_write(store):
    first = project_memberships_v2_as_recorded_components(store, knowledge_cutoff=TS)
    second = project_memberships_v2_as_recorded_components(store, knowledge_cutoff=TS)
    assert first == second and len(first) == 2
    assert store.connection.execute("SELECT COUNT(*) FROM ground_truth_workout_components_v3").fetchone()[0] == 0


def test_explicit_materialization_is_idempotent(store):
    first = materialize_membership_projection_v3(
        store, knowledge_cutoff=TS, migration_timestamp="2026-01-01T00:00:00Z",
        code_commit="synthetic-test",
    )
    second = materialize_membership_projection_v3(
        store, knowledge_cutoff=TS, migration_timestamp="2026-01-01T00:00:00Z",
        code_commit="synthetic-test",
    )
    assert first["added_count"] == 2 and second["added_count"] == 0
    assert first["logical_manifest"] == second["logical_manifest"]
    assert first["materialized_count"] == second["materialized_count"] == 2


def test_migrated_components_are_visible_at_inclusive_as_of_boundary(store):
    migration_timestamp = "2026-01-01T00:00:00Z"
    materialize_membership_projection_v3(
        store, knowledge_cutoff=TS, migration_timestamp=migration_timestamp,
        code_commit="synthetic-test",
    )
    before = store.latest_workout_components_as_of_v3(
        "2025-12-31T23:59:59.999999Z", purpose="technical_integrity"
    )
    exact = store.latest_workout_components_as_of_v3(
        migration_timestamp, purpose="technical_integrity"
    )
    after = store.latest_workout_components_as_of_v3(
        "2026-01-01T00:00:00.000001Z", purpose="technical_integrity"
    )
    assert before == []
    assert len(exact) == len(after) == 2


@pytest.mark.parametrize("equivalent_cutoff", [
    "2026-01-01T00:00:00Z",
    "2026-01-01T00:00:00+00:00",
    "2026-01-01T00:00:00.000000+00:00",
    "2025-12-31T18:00:00-06:00",
])
def test_migration_timestamp_iso_equivalence_is_observable_as_of(store, equivalent_cutoff):
    materialize_membership_projection_v3(
        store, knowledge_cutoff=TS,
        migration_timestamp="2025-12-31T18:00:00-06:00",
        code_commit="synthetic-test",
    )
    rows = store.latest_workout_components_as_of_v3(
        equivalent_cutoff, purpose="technical_integrity"
    )
    assert len(rows) == 2
    assert {row["decision_timestamp"] for row in rows} == {
        "2026-01-01T00:00:00.000000Z"
    }
    assert {row["label_available_at"] for row in rows} == {
        "2026-01-01T00:00:00.000000Z"
    }


def test_migration_preserves_distinct_microsecond_instants(store):
    materialize_membership_projection_v3(
        store, knowledge_cutoff=TS,
        migration_timestamp="2026-01-01T00:00:00.000001Z",
        code_commit="synthetic-test",
    )
    assert store.latest_workout_components_as_of_v3(
        "2026-01-01T00:00:00.000000Z", purpose="technical_integrity"
    ) == []
    assert len(store.latest_workout_components_as_of_v3(
        "2026-01-01T00:00:00.000001Z", purpose="technical_integrity"
    )) == 2


def test_migration_rejects_timezone_naive_timestamp_without_writes(store):
    with pytest.raises(ValueError, match="timezone"):
        materialize_membership_projection_v3(
            store, knowledge_cutoff=TS,
            migration_timestamp="2026-01-01T00:00:00",
            code_commit="synthetic-test",
        )
    assert store.connection.execute(
        "SELECT COUNT(*) FROM ground_truth_workout_components_v3"
    ).fetchone()[0] == 0


def test_equivalent_migration_timestamps_are_idempotent_and_preserve_v2(store):
    v2_before = [tuple(row) for row in store.connection.execute(
        "SELECT * FROM ground_truth_workout_memberships_v2 ORDER BY membership_decision_id"
    ).fetchall()]
    gold_before = store.build_dimension_gold_v2(
        product="gold_extended", knowledge_cutoff=TS
    )
    first = materialize_membership_projection_v3(
        store, knowledge_cutoff=TS,
        migration_timestamp="2026-01-01T00:00:00Z",
        code_commit="synthetic-test",
    )
    second = materialize_membership_projection_v3(
        store, knowledge_cutoff=TS,
        migration_timestamp="2025-12-31T18:00:00-06:00",
        code_commit="synthetic-test",
    )
    v2_after = [tuple(row) for row in store.connection.execute(
        "SELECT * FROM ground_truth_workout_memberships_v2 ORDER BY membership_decision_id"
    ).fetchall()]
    assert first["added_count"] == 2 and second["added_count"] == 0
    assert first["logical_manifest"] == second["logical_manifest"]
    assert v2_after == v2_before
    assert store.build_dimension_gold_v2(
        product="gold_extended", knowledge_cutoff=TS
    ) == gold_before


def test_populated_migration_is_reproducible_across_two_databases(store, tmp_path):
    results = []
    for name in ("copy_one.sqlite", "copy_two.sqlite"):
        path = Path(tmp_path) / name
        replica_connection = sqlite3.connect(path)
        store.connection.backup(replica_connection)
        replica_connection.close()
        with GroundTruthStore(path) as replica:
            result = materialize_membership_projection_v3(
                replica, knowledge_cutoff=TS,
                migration_timestamp="2025-12-31T18:00:00-06:00",
                code_commit="synthetic-test",
            )
            rows = replica.latest_workout_components_as_of_v3(
                "2026-01-01T00:00:00Z", purpose="technical_integrity"
            )
            results.append((result["logical_manifest"], rows))
    assert results[0] == results[1]


def test_materialization_is_atomic_on_intermediate_failure(store):
    store.connection.execute(
        """CREATE TRIGGER synthetic_abort_second_component
           BEFORE INSERT ON ground_truth_workout_components_v3
           WHEN NEW.component_order=2
           BEGIN SELECT RAISE(ABORT, 'synthetic migration failure'); END"""
    )
    with pytest.raises(sqlite3.IntegrityError, match="synthetic migration failure"):
        materialize_membership_projection_v3(
            store, knowledge_cutoff=TS, migration_timestamp="2026-01-01T00:00:00Z",
            code_commit="synthetic-test",
        )
    assert store.connection.execute("SELECT COUNT(*) FROM ground_truth_workout_components_v3").fetchone()[0] == 0


def test_migration_manifest_excludes_unrelated_v3_components(store):
    add_component(store, component("unrecorded", order=3))
    result = materialize_membership_projection_v3(
        store, knowledge_cutoff=TS, migration_timestamp="2026-01-01T00:00:00Z",
        code_commit="synthetic-test",
    )
    assert result["materialized_count"] == 2


def test_schema_and_synthetic_results_are_reproducible(tmp_path):
    manifests = []
    for name in ("first", "second"):
        with GroundTruthStore(tmp_path / f"{name}.sqlite") as value:
            value.initialize()
            manifests.append(value.schema_manifest())
            assert value.connection.execute("SELECT COUNT(*) FROM ground_truth_workout_components_v3").fetchone()[0] == 0
    assert manifests[0] == manifests[1]


def test_component_correction_cannot_precede_predecessor_decision(store):
    add_component(store, component("recorded"))
    correction = component(
        "recorded", decision="30000000-0000-4000-8000-000000000091"
    )
    correction.update({
        "supersedes_component_decision_id": D_RECORDED,
        "decision_kind": "correction",
        "decision_timestamp": "2023-01-01T00:00:00Z",
    })
    before = store.connection.execute(
        "SELECT COUNT(*) FROM ground_truth_workout_components_v3"
    ).fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="temporal regression"):
        add_component(store, correction)
    after = store.connection.execute(
        "SELECT COUNT(*) FROM ground_truth_workout_components_v3"
    ).fetchone()[0]
    assert before == after == 1


def test_component_correction_cannot_regress_predecessor_availability(store):
    original = component("recorded")
    original["label_available_at"] = "2025-01-01T00:00:00Z"
    add_component(store, original)
    correction = component(
        "recorded", decision="30000000-0000-4000-8000-000000000090"
    )
    correction.update({
        "supersedes_component_decision_id": D_RECORDED,
        "decision_kind": "correction",
        "decision_timestamp": "2024-06-01T00:00:00Z",
        "label_available_at": "2024-06-01T00:00:00Z",
    })
    with pytest.raises(sqlite3.IntegrityError, match="temporal regression"):
        add_component(store, correction)
    assert store.connection.execute(
        "SELECT COUNT(*) FROM ground_truth_workout_components_v3"
    ).fetchone()[0] == 1


def test_component_future_evidence_is_rejected_atomically(store):
    future_evidence = "10000000-0000-4000-8000-000000000099"
    store.add_evidence_record_v2({
        "evidence_id": future_evidence, "runner_id": RUNNER,
        "evidence_type_id": "synthetic_fixture", "source_system": "synthetic",
        "source_locator": "synthetic://future", "source_content_sha256": None,
        "evidence_observed_at": "2026-01-01T00:00:00Z",
        "recorded_at": "2026-01-01T00:00:00Z",
        "scientific_purpose": "future synthetic evidence",
        "data_minimization_note": "synthetic only", "code_commit": "synthetic-test",
    })
    with pytest.raises(sqlite3.IntegrityError, match="unavailable"):
        add_component(store, component("recorded"), future_evidence)
    assert store.connection.execute(
        "SELECT COUNT(*) FROM ground_truth_workout_components_v3"
    ).fetchone()[0] == 0
    assert store.connection.execute(
        "SELECT COUNT(*) FROM ground_truth_component_evidence_links_v3"
    ).fetchone()[0] == 0


def test_valid_component_correction_reconstructs_chain_before_and_after(store):
    add_component(store, component("recorded"))
    correction = component(
        "recorded", decision="30000000-0000-4000-8000-000000000092"
    )
    correction.update({
        "supersedes_component_decision_id": D_RECORDED,
        "decision_kind": "correction",
        "decision_timestamp": "2025-01-01T00:00:00Z",
        "label_available_at": "2025-01-01T00:00:00Z",
    })
    add_component(store, correction)
    before = store.latest_workout_components_as_of_v3(
        "2024-12-31T23:59:59Z", purpose="evaluation"
    )
    after = store.latest_workout_components_as_of_v3(
        "2025-01-01T00:00:00Z", purpose="evaluation"
    )
    assert [row["component_decision_id"] for row in before] == [D_RECORDED]
    assert [row["component_decision_id"] for row in after] == [correction["component_decision_id"]]


def test_component_revision_cannot_branch_from_same_predecessor(store):
    add_component(store, component("recorded"))
    first = component("recorded", decision="30000000-0000-4000-8000-000000000093")
    first.update({
        "supersedes_component_decision_id": D_RECORDED,
        "decision_kind": "correction",
        "decision_timestamp": "2025-01-01T00:00:00Z",
        "label_available_at": "2025-01-01T00:00:00Z",
    })
    add_component(store, first)
    branch = dict(first)
    branch["component_decision_id"] = "30000000-0000-4000-8000-000000000094"
    with pytest.raises(sqlite3.IntegrityError, match="already superseded"):
        add_component(store, branch)


@pytest.mark.parametrize("purpose", ["model_training", "unknown_consumer", "evaluation_typo"])
def test_unknown_purpose_fails_closed_even_without_locked_test(store, purpose):
    add_component(store, component("recorded"))
    with pytest.raises(ValueError, match="unknown access purpose"):
        store.latest_workout_components_as_of_v3(TS, purpose=purpose)


def test_unknown_purpose_fails_closed_on_empty_claim_and_gold_results(store):
    with pytest.raises(ValueError, match="unknown access purpose"):
        store.latest_component_claims_as_of_v3(TS, purpose="model_training")
    with pytest.raises(ValueError, match="unknown access purpose"):
        store.build_component_gold_v3(
            product="gold_core", knowledge_cutoff=TS, purpose="model_training"
        )


def test_allowed_adaptive_purpose_can_use_ordinary_partition(store):
    add_component(store, component("recorded"))
    rows = store.latest_workout_components_as_of_v3(TS, purpose="training")
    assert [row["component_id"] for row in rows] == [C_RECORDED]


def test_locked_test_fail_closed_is_equivalent_for_components_claims_and_gold(store):
    locked_component = component(
        "recorded", order=2, decision="30000000-0000-4000-8000-000000000095",
        component_id="20000000-0000-4000-8000-000000000095", membership=MEMBERSHIP_2,
    )
    add_component(store, locked_component, EVIDENCE_2)
    thread_id = store.create_component_claim_thread_v3(
        runner_id=RUNNER, component_id=locked_component["component_id"],
        dimension_name="repetition_count_intended", opened_by="synthetic", opened_at=TS,
    )
    locked_claim = claim(
        claim_id="50000000-0000-4000-8000-000000000095", thread=thread_id
    )
    locked_claim["component_id"] = locked_component["component_id"]
    add_claim(store, locked_claim, EVIDENCE_2)
    calls = (
        lambda: store.latest_workout_components_as_of_v3(TS, purpose="model_training"),
        lambda: store.latest_component_claims_as_of_v3(TS, purpose="model_training"),
        lambda: store.build_component_gold_v3(
            product="gold_extended", knowledge_cutoff=TS, purpose="model_training"
        ),
    )
    for call in calls:
        with pytest.raises(ValueError, match="unknown access purpose"):
            call()
    assert len(store.latest_workout_components_as_of_v3(TS, purpose="evaluation")) == 1
    assert len(store.latest_component_claims_as_of_v3(TS, purpose="audit")) == 1


def test_component_claim_correction_cannot_backdate_knowledge(store):
    add_component(store, component("recorded"))
    store.create_component_claim_thread_v3(
        runner_id=RUNNER, component_id=C_RECORDED,
        dimension_name="repetition_count_intended", opened_by="synthetic",
        opened_at=TS, annotation_thread_id=CLAIM_THREAD,
    )
    add_claim(store, claim())
    correction = claim(
        claim_id=CLAIM_2, revision=2, supersedes=CLAIM_1,
        available="2023-01-01T00:00:00Z",
    )
    correction["decision_timestamp"] = "2023-01-01T00:00:00Z"
    with pytest.raises(sqlite3.IntegrityError, match="temporal regression"):
        add_claim(store, correction)
    assert store.connection.execute(
        "SELECT COUNT(*) FROM ground_truth_component_claims_v3"
    ).fetchone()[0] == 1
