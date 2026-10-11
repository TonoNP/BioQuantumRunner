from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from scripts.build_ground_truth_addendum_synthetic import build
from src.ground_truth_addendum.canonical import canonical_json, logical_hash, logical_records_hash
from src.ground_truth_addendum.compatibility import to_frozen_d4_rows
from src.ground_truth_addendum.contracts import ADDENDUM_VERSION
from src.ground_truth_addendum.ids import deterministic_id
from src.ground_truth_addendum.store import GroundTruthStore, LockedTestAccessError


RUNNER = "synthetic_runner"
SOURCE = "synthetic_session_2023-01-01.json"
SHA = "a" * 64
THREAD_1 = "11111111-1111-4111-8111-111111111111"
THREAD_2 = "22222222-2222-4222-8222-222222222222"
DECISION_1 = "33333333-3333-4333-8333-333333333331"
DECISION_2 = "33333333-3333-4333-8333-333333333332"
DECISION_OTHER = "44444444-4444-4444-8444-444444444444"


@pytest.fixture
def store(tmp_path):
    with GroundTruthStore(tmp_path / "ground_truth.sqlite") as value:
        value.initialize()
        value.add_source_session({
            "runner_id": RUNNER,
            "source_file": SOURCE,
            "source_sha256": SHA,
            "session_date": "2023-01-01",
            "source_manifest": "f" * 64,
        })
        yield value


def decision(
    *, decision_id=DECISION_1, thread=THREAD_1, revision=1, supersedes=None,
    level="verified", function="easy", status="asserted",
    timestamp="2024-01-01T00:00:00Z", available=None,
):
    return {
        "decision_id": decision_id,
        "annotation_thread_id": thread,
        "revision": revision,
        "supersedes_decision_id": supersedes,
        "decision_kind": "annotation" if revision == 1 else "correction",
        "runner_id": RUNNER,
        "source_file": SOURCE,
        "source_sha256": SHA,
        "author_id": "synthetic_author",
        "author_role": "data_owner",
        "evidence_observed_at": timestamp,
        "decision_timestamp": timestamp,
        "effective_from": "2023-01-01T00:00:00Z",
        "label_available_at": available or timestamp,
        "evidence_type": "synthetic_log",
        "evidence_reference": "synthetic://evidence",
        "evidence_level": level,
        "session_context": "training_environment",
        "session_context_status": "asserted",
        "workout_structure": "single_exercise",
        "workout_structure_status": "asserted",
        "primary_function": function,
        "primary_function_status": status,
        "primary_function_subtype": None,
        "primary_function_subtype_status": "abstained",
        "component_role": "main_set",
        "component_role_status": "asserted",
        "performance_relevance": "low",
        "performance_relevance_status": "asserted",
        "training_load_relevance": "moderate",
        "training_load_relevance_status": "asserted",
        "uncertainty_reason": "synthetic subtype abstention",
        "comment": "synthetic only",
        "code_commit": "synthetic-test",
        "contract_version": ADDENDUM_VERSION,
    }


def open_thread(store, thread=THREAD_1, author="synthetic_author"):
    return store.create_annotation_thread(
        runner_id=RUNNER, source_file=SOURCE, opened_by=author,
        opened_at="2024-01-01T00:00:00Z", annotation_thread_id=thread,
    )


def test_schema_contains_all_contract_and_technical_tables(store):
    assert set(store.table_names()) == {
        "ground_truth_annotation_threads", "ground_truth_group_memberships",
        "ground_truth_publications", "ground_truth_review_unit_memberships",
        "ground_truth_review_units", "ground_truth_sampling_batches",
        "ground_truth_session_decisions", "ground_truth_source_sessions",
        "ground_truth_workout_groups", "ground_truth_claim_threads_v2",
        "ground_truth_evidence_type_catalog_v2", "ground_truth_evidence_records_v2",
        "ground_truth_semantic_claims_v2", "ground_truth_claim_evidence_links_v2",
        "ground_truth_workout_memberships_v2", "ground_truth_membership_evidence_links_v2",
        "ground_truth_activity_type_catalog_v3", "ground_truth_workout_components_v3",
        "ground_truth_component_evidence_links_v3",
        "ground_truth_component_claim_threads_v3", "ground_truth_component_claims_v3",
        "ground_truth_component_claim_evidence_links_v3",
    }


def test_historical_decision_cannot_be_updated_or_deleted(store):
    open_thread(store); store.add_session_decision(decision())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.connection.execute("UPDATE ground_truth_session_decisions SET comment='changed'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.connection.execute("DELETE FROM ground_truth_session_decisions")
    store.connection.rollback()


def test_decision_id_is_globally_unique(store):
    open_thread(store); store.add_session_decision(decision())
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        store.add_session_decision(decision())


def test_supersedes_chain_must_be_immediate_and_same_thread(store):
    open_thread(store); store.add_session_decision(decision())
    with pytest.raises(sqlite3.IntegrityError, match="supersedes"):
        store.add_session_decision(decision(
            decision_id=DECISION_2, revision=2, supersedes=DECISION_OTHER,
            timestamp="2024-02-01T00:00:00Z",
        ))


def test_independent_opinion_is_preserved_in_separate_thread(store):
    open_thread(store, THREAD_1); open_thread(store, THREAD_2, "second_reviewer")
    store.add_session_decision(decision())
    store.add_session_decision(decision(decision_id=DECISION_OTHER, thread=THREAD_2, function="steady"))
    rows = store.latest_session_decisions_as_of("2025-01-01T00:00:00Z")
    assert {row["annotation_thread_id"] for row in rows} == {THREAD_1, THREAD_2}
    assert store.build_gold(product="gold_core", knowledge_cutoff="2025-01-01T00:00:00Z") == []
    with pytest.raises(ValueError, match="explicitly resolved"):
        to_frozen_d4_rows(rows)


def test_unknown_foreign_key_and_wrong_source_hash_are_rejected(store):
    open_thread(store)
    bad = decision(); bad["source_sha256"] = "b" * 64
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.add_session_decision(bad)


def test_deterministic_ids_are_idempotent_and_domain_separated():
    first = deterministic_id("review-unit", (RUNNER, SOURCE, SHA))
    assert first == deterministic_id("review-unit", (RUNNER, SOURCE, SHA))
    assert first != deterministic_id("sampling-batch", (RUNNER, SOURCE, SHA))


def test_logical_hash_is_independent_of_mapping_and_record_order():
    assert canonical_json({"b": 2, "a": 1}) == canonical_json({"a": 1, "b": 2})
    left = [{"id": "b", "v": 2}, {"id": "a", "v": 1}]
    right = list(reversed(left))
    assert logical_records_hash(left, domain="test", order_by=("id",)) == logical_records_hash(right, domain="test", order_by=("id",))
    assert logical_hash({"value": 1}, domain="logical") != logical_hash({"value": 1}, domain="binary")


def test_as_of_reconstruction_uses_prior_revision_until_correction_available(store):
    open_thread(store); store.add_session_decision(decision())
    store.add_session_decision(decision(
        decision_id=DECISION_2, revision=2, supersedes=DECISION_1,
        function="recovery", timestamp="2026-01-01T00:00:00Z",
    ))
    old = store.latest_session_decisions_as_of("2025-12-31T23:59:59Z")
    new = store.latest_session_decisions_as_of("2026-01-01T00:00:00Z")
    assert old[0]["decision_id"] == DECISION_1
    assert new[0]["decision_id"] == DECISION_2


def test_future_evidence_is_excluded_from_as_of(store):
    open_thread(store)
    store.add_session_decision(decision(
        timestamp="2025-01-01T00:00:00Z", available="2026-01-01T00:00:00Z"
    ))
    assert store.latest_session_decisions_as_of("2025-06-01T00:00:00Z") == []


def test_gold_core_and_extended_remain_distinct_and_reported_is_preserved(store):
    open_thread(store)
    store.add_session_decision(decision(level="reported"))
    assert store.build_gold(product="gold_core", knowledge_cutoff="2025-01-01T00:00:00Z") == []
    extended = store.build_gold(product="gold_extended", knowledge_cutoff="2025-01-01T00:00:00Z")
    assert len(extended) == 1
    assert extended[0]["evidence_level"] == "reported"
    assert extended[0]["gold_product"] == "gold_extended"


def test_abstention_is_preserved_per_dimension(store):
    open_thread(store)
    row = decision(function=None, status="abstained")
    store.add_session_decision(row)
    selected = store.build_gold(product="gold_core", knowledge_cutoff="2025-01-01T00:00:00Z")[0]
    assert selected["primary_function"] is None
    assert selected["primary_function_status"] == "abstained"
    assert selected["primary_function_subtype_status"] == "abstained"


@pytest.mark.parametrize("purpose", [
    "training", "calibration", "feature_selection", "rule_selection",
    "threshold_selection", "active_learning", "architecture_optimization",
])
def test_locked_test_is_rejected_for_every_adaptive_purpose(tmp_path, purpose):
    with GroundTruthStore(tmp_path / "locked.sqlite") as value:
        value.initialize()
        value.add_source_session({
            "runner_id": RUNNER, "source_file": "synthetic_locked_2025.json",
            "source_sha256": "c" * 64, "session_date": "2025-01-01",
            "source_manifest": "d" * 64,
        })
        with pytest.raises(LockedTestAccessError, match="locked_test"):
            value.assert_purpose_allowed(purpose=purpose, source_files=["synthetic_locked_2025.json"])


def test_locked_test_descriptive_integrity_access_is_allowed(tmp_path):
    with GroundTruthStore(tmp_path / "locked.sqlite") as value:
        value.initialize()
        value.add_source_session({
            "runner_id": RUNNER, "source_file": "synthetic_locked_2025.json",
            "source_sha256": "c" * 64, "session_date": "2025-01-01",
            "source_manifest": "d" * 64,
        })
        value.assert_purpose_allowed(purpose="technical_integrity", source_files=["synthetic_locked_2025.json"])


def test_sampling_batch_lock_is_irreversible_and_blocks_new_memberships(store):
    population = store.source_population_manifest()
    batch = store.create_sampling_batch({
        "runner_id": RUNNER, "sampling_strategy_version": "synthetic-v1",
        "sampling_purpose": "pilot", "population_manifest": population,
        "population_size": 1, "requested_unit_count": 1, "selection_method": "census",
        "random_seed": None, "strata_definition": {}, "selection_algorithm": "synthetic",
        "feature_snapshot_manifest": None, "knowledge_cutoff": "2024-01-01T00:00:00Z",
        "created_at": "2024-01-01T00:00:00Z", "created_by": "synthetic",
        "code_commit": "synthetic-test", "notes": None,
    })
    _, record = store.create_review_unit({
        "runner_id": RUNNER, "review_unit_type": "individual_session",
        "sampling_batch_id": batch, "sampling_strategy_version": "synthetic-v1",
        "sampling_stratum": "synthetic", "selection_reason": "synthetic",
        "selection_probability": 1.0, "selection_probability_missing_reason": None,
        "temporal_partition": "development", "review_status": "created",
        "reviewer_id": None, "reviewer_role": None, "semantics_mode": "as_of",
        "knowledge_cutoff": "2024-01-01T00:00:00Z", "data_manifest": "d" * 64,
        "feature_contract_version": "synthetic-v1", "code_commit": "synthetic-test",
    })
    store.lock_sampling_batch(batch)
    with pytest.raises(sqlite3.IntegrityError, match="locked batch"):
        store.add_review_membership({
            "review_unit_record_id": record, "runner_id": RUNNER, "source_file": SOURCE,
            "source_sha256": SHA, "presentation_order": 1, "membership_reason": "late insert",
        })
    with pytest.raises(ValueError, match="already locked"):
        store.lock_sampling_batch(batch)


def test_session_identity_is_preserved_inside_workout_group(store):
    workout_id = "55555555-5555-4555-8555-555555555555"
    thread = "66666666-6666-4666-8666-666666666666"
    group_decision = "77777777-7777-4777-8777-777777777777"
    membership = "88888888-8888-4888-8888-888888888888"
    store.create_thread(
        runner_id=RUNNER, target_kind="workout_group", target_key=workout_id,
        opened_by="synthetic_author", opened_at="2024-01-01T00:00:00Z",
        annotation_thread_id=thread,
    )
    store.add_workout_group({
        "group_decision_id": group_decision, "workout_group_id": workout_id,
        "annotation_thread_id": thread, "revision": 1, "supersedes_group_decision_id": None,
        "decision_kind": "annotation", "runner_id": RUNNER, "group_status": "confirmed",
        "evidence_level": "verified", "evidence_types": ["synthetic_log", "synthetic_laps"],
        "evidence_reference": "synthetic://group", "decision_timestamp": "2024-01-01T00:00:00Z",
        "label_available_at": "2024-01-01T00:00:00Z", "author_id": "synthetic_author",
        "author_role": "data_owner", "code_commit": "synthetic-test",
    })
    store.add_group_membership({
        "membership_decision_id": membership, "annotation_thread_id": thread, "revision": 1,
        "supersedes_membership_decision_id": None, "workout_group_id": workout_id,
        "group_decision_id": group_decision, "runner_id": RUNNER, "source_file": SOURCE,
        "source_sha256": SHA, "membership_status": "included", "component_order": 1,
        "component_role": "main_set", "evidence_level": "verified",
        "decision_timestamp": "2024-01-01T00:00:00Z", "label_available_at": "2024-01-01T00:00:00Z",
    })
    row = store.connection.execute("SELECT * FROM ground_truth_group_memberships").fetchone()
    assert row["source_file"] == SOURCE and row["source_sha256"] == SHA


def test_multi_runner_sessions_cannot_be_cross_referenced(store):
    store.add_source_session({
        "runner_id": "synthetic_runner_two", "source_file": "synthetic_two_2023.json",
        "source_sha256": "e" * 64, "session_date": "2023-02-01", "source_manifest": "f" * 64,
    })
    open_thread(store)
    bad = decision(); bad["runner_id"] = "synthetic_runner_two"
    with pytest.raises(sqlite3.IntegrityError):
        store.add_session_decision(bad)


def test_two_complete_synthetic_builds_have_identical_logical_hashes(tmp_path):
    first = build(tmp_path / "first")
    second = build(tmp_path / "second")
    assert first["schema_manifest"] == second["schema_manifest"]
    assert first["population_manifest"] == second["population_manifest"]
    assert first["gold_core_logical_hash"] == second["gold_core_logical_hash"]
    assert first["gold_extended_logical_hash"] == second["gold_extended_logical_hash"]
    assert first["table_logical_hashes"] == second["table_logical_hashes"]


def test_synthetic_builder_contains_no_real_ground_truth_or_review_units(tmp_path):
    summary = build(tmp_path / "build")
    assert summary["synthetic_only"] is True
    assert summary["real_session_count"] == 0
    assert summary["selected_real_review_units"] == 0
    db = sqlite3.connect(tmp_path / "build" / "ground_truth_synthetic.sqlite")
    files = [row[0] for row in db.execute("SELECT source_file FROM ground_truth_source_sessions")]
    assert files and all(name.startswith("synthetic_") for name in files)
    db.close()


def test_frozen_d1_d2_d3_and_d4_inputs_match_recorded_hashes():
    root = Path(__file__).resolve().parents[1]
    d123 = json.loads((root / "reports/d4_frozen_inputs.json").read_text(encoding="utf-8"))["sha256"]
    d4 = json.loads((root / "tests/fixtures/d4_frozen_manifest.json").read_text(encoding="utf-8"))
    local = json.loads((root / "tests/fixtures/preimplementation_local_manifest.json").read_text(encoding="utf-8"))
    for relative, expected in {**d123, **d4, **local}.items():
        actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        assert actual == expected, relative
