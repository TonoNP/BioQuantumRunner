from __future__ import annotations

import sqlite3

import pytest

from src.ground_truth_addendum.store import GroundTruthStore, LockedTestAccessError
from src.ground_truth_addendum.migration_v1_to_v2 import migrate_legacy_session_decisions


RUNNER = "synthetic_runner"
SOURCE = "synthetic_2023.json"
SHA = "a" * 64
T1 = "11111111-1111-4111-8111-111111111111"
T2 = "22222222-2222-4222-8222-222222222222"
C1 = "33333333-3333-4333-8333-333333333331"
C2 = "33333333-3333-4333-8333-333333333332"
E1 = "44444444-4444-4444-8444-444444444444"


@pytest.fixture
def store(tmp_path):
    with GroundTruthStore(tmp_path / "claims.sqlite") as value:
        value.initialize()
        value.add_source_session({
            "runner_id": RUNNER, "source_file": SOURCE, "source_sha256": SHA,
            "session_date": "2023-01-01", "source_manifest": "f" * 64,
        })
        yield value


def claim(*, claim_id=C1, thread=T1, dimension="primary_function", value="easy",
          status="asserted", level="verified", kind="human_report", revision=1,
          supersedes=None, available="2024-01-01T00:00:00Z"):
    return {
        "claim_id": claim_id, "annotation_thread_id": thread, "revision": revision,
        "supersedes_claim_id": supersedes,
        "decision_kind": "annotation" if revision == 1 else "correction",
        "runner_id": RUNNER, "subject_kind": "recorded_session", "subject_key": SOURCE,
        "source_file": SOURCE, "source_sha256": SHA, "dimension_name": dimension,
        "claim_value": value, "claim_status": status, "claim_kind": kind,
        "evidence_level": level, "author_id": "synthetic", "author_role": "reviewer",
        "rationale": "synthetic only", "uncertainty_reason": None,
        "evidence_observed_at": "2023-01-01T00:00:00Z",
        "decision_timestamp": "2024-01-01T00:00:00Z",
        "effective_from": "2023-01-01T00:00:00Z", "label_available_at": available,
        "provenance_granularity": "atomic", "legacy_decision_id": None,
        "code_commit": "synthetic-test",
    }


def thread(store, thread_id=T1, dimension="primary_function"):
    return store.create_claim_thread_v2(
        runner_id=RUNNER, subject_kind="recorded_session", subject_key=SOURCE,
        opened_by=f"synthetic-{dimension}", opened_at="2024-01-01T00:00:00Z",
        annotation_thread_id=thread_id,
    )


def test_claims_keep_dimension_specific_evidence_levels(store):
    thread(store, T1, "function")
    thread(store, T2, "structure")
    store.add_semantic_claim_v2(claim())
    store.add_semantic_claim_v2(claim(
        claim_id=C2, thread=T2, dimension="workout_structure", value="repetitive",
        level="reported", kind="human_report",
    ))
    core = store.build_dimension_gold_v2(product="gold_core", knowledge_cutoff="2025-01-01T00:00:00Z")
    extended = store.build_dimension_gold_v2(product="gold_extended", knowledge_cutoff="2025-01-01T00:00:00Z")
    assert [row["dimension_name"] for row in core] == ["primary_function"]
    assert {row["dimension_name"] for row in extended} == {"primary_function", "workout_structure"}


def test_complementary_claims_are_not_conflict(store):
    thread(store, T1); thread(store, T2)
    store.add_semantic_claim_v2(claim())
    store.add_semantic_claim_v2(claim(claim_id=C2, thread=T2, dimension="component_role", value="main_set"))
    rows = store.build_dimension_gold_v2(product="gold_core", knowledge_cutoff="2025-01-01T00:00:00Z")
    assert len(rows) == 2
    assert all(row["resolution_status"] == "resolved" for row in rows)


def test_same_dimension_contradiction_is_explicit(store):
    thread(store, T1); thread(store, T2)
    store.add_semantic_claim_v2(claim())
    store.add_semantic_claim_v2(claim(claim_id=C2, thread=T2, value="recovery"))
    row = store.build_dimension_gold_v2(product="gold_core", knowledge_cutoff="2025-01-01T00:00:00Z")[0]
    assert row["resolution_status"] == "conflicted"
    assert row["reason_code"] == "CONFLICT_UNRESOLVED"
    assert set(row["source_claim_ids"]) == {C1, C2}


def test_independent_agreement_preserves_both_claims(store):
    thread(store, T1); thread(store, T2)
    store.add_semantic_claim_v2(claim())
    store.add_semantic_claim_v2(claim(claim_id=C2, thread=T2))
    row = store.build_dimension_gold_v2(product="gold_core", knowledge_cutoff="2025-01-01T00:00:00Z")[0]
    assert row["reason_code"] == "AGREEMENT_NO_ADJUDICATION"
    assert row["source_claim_ids"] == [C1, C2]


@pytest.mark.parametrize("status,value,reason,valid", [
    ("asserted", "easy", None, True), ("asserted", None, None, False),
    ("unknown", None, None, True), ("unknown", "easy", None, False),
    ("abstained", None, "insufficient evidence", True),
    ("abstained", "easy", "insufficient evidence", False),
    ("uncertain", "easy", "two plausible meanings", True),
    ("uncertain", "easy", None, False),
])
def test_status_value_invariants(store, status, value, reason, valid):
    thread(store)
    row = claim(status=status, value=value); row["uncertainty_reason"] = reason
    if valid:
        store.add_semantic_claim_v2(row)
    else:
        with pytest.raises(ValueError):
            store.add_semantic_claim_v2(row)


def test_missing_annotation_is_distinct_from_unknown(store):
    assert store.build_dimension_gold_v2(product="gold_core", knowledge_cutoff="2025-01-01T00:00:00Z") == []
    thread(store); store.add_semantic_claim_v2(claim(status="unknown", value=None))
    row = store.build_dimension_gold_v2(product="gold_core", knowledge_cutoff="2025-01-01T00:00:00Z")[0]
    assert row["reason_code"] == "UNKNOWN"


def test_evidence_catalog_and_provenance_are_auditable(store):
    store.add_evidence_record_v2({
        "evidence_id": E1, "runner_id": RUNNER, "evidence_type_id": "human_contemporary_log",
        "source_system": "synthetic_diary", "source_locator": "synthetic://entry/1",
        "source_content_sha256": None, "evidence_observed_at": "2023-01-01T00:00:00Z",
        "recorded_at": "2024-01-01T00:00:00Z", "scientific_purpose": "classification test",
        "data_minimization_note": "synthetic relevant excerpt only", "code_commit": "synthetic-test",
    })
    thread(store); store.add_semantic_claim_v2(claim())
    link = store.link_claim_evidence_v2(claim_id=C1, evidence_id=E1, support_role="support")
    row = store.connection.execute(
        "SELECT * FROM ground_truth_claim_evidence_links_v2 WHERE claim_evidence_link_id=?", (link,)
    ).fetchone()
    assert row["support_role"] == "support"
    bad = dict(claim(claim_id=C2, thread=T2)); thread(store, T2)
    store.add_semantic_claim_v2(bad)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.link_claim_evidence_v2(claim_id=C2, evidence_id="55555555-5555-4555-8555-555555555555", support_role="support")


def test_claim_as_of_and_correction_do_not_rewrite_history(store):
    thread(store); store.add_semantic_claim_v2(claim())
    corrected = claim(
        claim_id=C2, revision=2, supersedes=C1, value="recovery",
        available="2026-01-01T00:00:00Z",
    )
    corrected["decision_timestamp"] = "2026-01-01T00:00:00Z"
    store.add_semantic_claim_v2(corrected)
    old = store.latest_semantic_claims_as_of_v2("2025-01-01T00:00:00Z")
    new = store.latest_semantic_claims_as_of_v2("2026-01-01T00:00:00Z")
    assert old[0]["claim_id"] == C1 and new[0]["claim_id"] == C2


def test_claim_history_is_append_only(store):
    thread(store); store.add_semantic_claim_v2(claim())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.connection.execute("UPDATE ground_truth_semantic_claims_v2 SET claim_value='changed'")
    store.connection.rollback()


def test_membership_provenance_and_as_of_are_atomic(store):
    workout_id = "55555555-5555-4555-8555-555555555555"
    legacy_thread = "66666666-6666-4666-8666-666666666666"
    group_decision = "77777777-7777-4777-8777-777777777777"
    membership_thread = "88888888-8888-4888-8888-888888888888"
    membership_id = "99999999-9999-4999-8999-999999999999"
    store.create_thread(
        runner_id=RUNNER, target_kind="workout_group", target_key=workout_id,
        opened_by="synthetic", opened_at="2024-01-01T00:00:00Z",
        annotation_thread_id=legacy_thread,
    )
    store.add_workout_group({
        "group_decision_id": group_decision, "workout_group_id": workout_id,
        "annotation_thread_id": legacy_thread, "revision": 1,
        "supersedes_group_decision_id": None, "decision_kind": "annotation",
        "runner_id": RUNNER, "group_status": "confirmed", "evidence_level": "reported",
        "evidence_types": ["synthetic_fixture"], "evidence_reference": "synthetic://group",
        "decision_timestamp": "2024-01-01T00:00:00Z",
        "label_available_at": "2024-01-01T00:00:00Z", "author_id": "synthetic",
        "author_role": "reviewer", "code_commit": "synthetic-test",
    })
    store.create_claim_thread_v2(
        runner_id=RUNNER, subject_kind="workout_membership",
        subject_key=f"{workout_id}|{SOURCE}", opened_by="synthetic",
        opened_at="2025-01-01T00:00:00Z", annotation_thread_id=membership_thread,
    )
    store.add_evidence_record_v2({
        "evidence_id": E1, "runner_id": RUNNER, "evidence_type_id": "synthetic_fixture",
        "source_system": "synthetic", "source_locator": "synthetic://membership",
        "source_content_sha256": None, "evidence_observed_at": "2023-01-01T00:00:00Z",
        "recorded_at": "2025-01-01T00:00:00Z", "scientific_purpose": "membership test",
        "data_minimization_note": "synthetic only", "code_commit": "synthetic-test",
    })
    store.add_workout_membership_v2({
        "membership_decision_id": membership_id, "annotation_thread_id": membership_thread,
        "revision": 1, "supersedes_membership_decision_id": None,
        "decision_kind": "annotation", "runner_id": RUNNER,
        "workout_group_id": workout_id, "group_decision_id": group_decision,
        "source_file": SOURCE, "source_sha256": SHA, "membership_state": "included",
        "component_order": 1, "component_role": "warmup", "claim_kind": "human_report",
        "evidence_level": "reported", "author_id": "synthetic", "author_role": "reviewer",
        "rationale": "synthetic composition", "uncertainty_reason": None,
        "evidence_observed_at": "2023-01-01T00:00:00Z",
        "decision_timestamp": "2025-01-01T00:00:00Z",
        "effective_from": "2023-01-01T00:00:00Z",
        "label_available_at": "2025-01-01T00:00:00Z", "code_commit": "synthetic-test",
    })
    store.link_membership_evidence_v2(
        membership_decision_id=membership_id, evidence_id=E1, support_role="support"
    )
    assert store.latest_workout_memberships_as_of_v2("2024-12-31T23:59:59Z") == []
    rows = store.latest_workout_memberships_as_of_v2("2025-01-01T00:00:00Z")
    assert rows[0]["source_file"] == SOURCE and rows[0]["component_role"] == "warmup"


def test_unknown_membership_cannot_silently_assert_role(store):
    row = {
        "membership_decision_id": "99999999-9999-4999-8999-999999999999",
        "membership_state": "unknown", "component_order": 1, "component_role": "warmup",
        "claim_kind": "human_report", "evidence_level": "reported",
        "uncertainty_reason": "not known",
    }
    with pytest.raises(ValueError, match="cannot assert"):
        store.add_workout_membership_v2(row)


def test_cross_runner_claim_is_rejected(store):
    store.add_source_session({
        "runner_id": "runner_two", "source_file": "synthetic_two.json", "source_sha256": "b" * 64,
        "session_date": "2023-01-02", "source_manifest": "f" * 64,
    })
    thread(store)
    bad = claim(); bad["runner_id"] = "runner_two"
    with pytest.raises(sqlite3.IntegrityError):
        store.add_semantic_claim_v2(bad)


@pytest.mark.parametrize("purpose", [
    "training", "calibration", "feature_selection", "rule_selection",
    "threshold_selection", "active_learning", "architecture_optimization",
])
def test_locked_test_protection_is_unchanged(store, purpose):
    store.add_source_session({
        "runner_id": RUNNER, "source_file": "synthetic_locked_2025.json",
        "source_sha256": "c" * 64, "session_date": "2025-01-01", "source_manifest": "f" * 64,
    })
    with pytest.raises(LockedTestAccessError):
        store.assert_purpose_allowed(purpose=purpose, source_files=["synthetic_locked_2025.json"])


def test_legacy_migration_is_additive_deterministic_and_does_not_invent_atomic_provenance(store):
    legacy_thread = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    legacy_decision = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    store.create_annotation_thread(
        runner_id=RUNNER, source_file=SOURCE, opened_by="synthetic",
        opened_at="2024-01-01T00:00:00Z", annotation_thread_id=legacy_thread,
    )
    store.add_session_decision({
        "decision_id": legacy_decision, "annotation_thread_id": legacy_thread,
        "revision": 1, "supersedes_decision_id": None, "decision_kind": "annotation",
        "runner_id": RUNNER, "source_file": SOURCE, "source_sha256": SHA,
        "author_id": "synthetic", "author_role": "reviewer",
        "evidence_observed_at": "2023-01-01T00:00:00Z",
        "decision_timestamp": "2024-01-01T00:00:00Z",
        "effective_from": "2023-01-01T00:00:00Z",
        "label_available_at": "2024-01-01T00:00:00Z",
        "evidence_type": "synthetic_legacy", "evidence_reference": "synthetic://legacy",
        "evidence_level": "reported", "session_context": "training_environment",
        "session_context_status": "asserted", "workout_structure": "single_exercise",
        "workout_structure_status": "asserted", "primary_function": "easy",
        "primary_function_status": "asserted", "primary_function_subtype": None,
        "primary_function_subtype_status": "abstained", "component_role": "main_set",
        "component_role_status": "asserted", "performance_relevance": "low",
        "performance_relevance_status": "asserted", "training_load_relevance": "moderate",
        "training_load_relevance_status": "asserted",
        "uncertainty_reason": "synthetic subtype abstention", "comment": "synthetic legacy",
        "code_commit": "synthetic", "contract_version": "d4-ground-truth-addendum-1.0",
    })
    first = migrate_legacy_session_decisions(
        store, migration_timestamp="2026-01-01T00:00:00Z", code_commit="synthetic"
    )
    second = migrate_legacy_session_decisions(
        store, migration_timestamp="2026-01-01T00:00:00Z", code_commit="synthetic"
    )
    assert first["claims_added"] == 7 and second["claims_added"] == 0
    assert first["logical_manifest"] == second["logical_manifest"]
    rows = store.connection.execute(
        "SELECT claim_kind,provenance_granularity FROM ground_truth_semantic_claims_v2"
    ).fetchall()
    assert {(row["claim_kind"], row["provenance_granularity"]) for row in rows} == {
        ("legacy_unclassified", "legacy_decision_wide")
    }
    assert store.connection.execute("SELECT COUNT(*) FROM ground_truth_session_decisions").fetchone()[0] == 1


def test_empty_component_v3_tables_do_not_change_v2_gold(store):
    thread(store); store.add_semantic_claim_v2(claim())
    before = store.build_dimension_gold_v2(
        product="gold_core", knowledge_cutoff="2025-01-01T00:00:00Z"
    )
    assert store.connection.execute(
        "SELECT COUNT(*) FROM ground_truth_workout_components_v3"
    ).fetchone()[0] == 0
    assert store.connection.execute(
        "SELECT COUNT(*) FROM ground_truth_component_claims_v3"
    ).fetchone()[0] == 0
    after = store.build_dimension_gold_v2(
        product="gold_core", knowledge_cutoff="2025-01-01T00:00:00Z"
    )
    assert before == after
