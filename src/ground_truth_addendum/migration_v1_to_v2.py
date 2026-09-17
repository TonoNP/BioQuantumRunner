"""Deterministic, additive projection of legacy D4 decisions into atomic claims.

The projection never changes v1 rows.  Because v1 evidence metadata applied to
the whole decision, migrated claims are explicitly marked legacy_decision_wide
and legacy_unclassified instead of inventing dimension-level provenance.
"""

from __future__ import annotations

from typing import Any

from .canonical import logical_records_hash
from .ids import deterministic_id
from .store import GroundTruthStore


DIMENSION_FIELDS = (
    ("session_context", "session_context_status"),
    ("workout_structure", "workout_structure_status"),
    ("primary_function", "primary_function_status"),
    ("primary_function_subtype", "primary_function_subtype_status"),
    ("component_role", "component_role_status"),
    ("performance_relevance", "performance_relevance_status"),
    ("training_load_relevance", "training_load_relevance_status"),
)


def migrate_legacy_session_decisions(
    store: GroundTruthStore, *, migration_timestamp: str, code_commit: str
) -> dict[str, Any]:
    legacy = [dict(row) for row in store.connection.execute(
        "SELECT * FROM ground_truth_session_decisions ORDER BY runner_id,source_file,annotation_thread_id,revision"
    ).fetchall()]
    claims_added = 0
    evidence_added = 0
    for decision in legacy:
        evidence_id = deterministic_id("legacy-evidence-v2", (decision["decision_id"],))
        if store.connection.execute(
            "SELECT 1 FROM ground_truth_evidence_records_v2 WHERE evidence_id=?", (evidence_id,)
        ).fetchone() is None:
            store.add_evidence_record_v2({
                "evidence_id": evidence_id,
                "runner_id": decision["runner_id"],
                "evidence_type_id": "legacy_decision_evidence",
                "source_system": "d4_ground_truth_v1",
                "source_locator": f"{decision['evidence_type']}::{decision['evidence_reference']}",
                "source_content_sha256": None,
                "evidence_observed_at": decision["evidence_observed_at"],
                "recorded_at": migration_timestamp,
                "scientific_purpose": "lossless provenance-preserving v1 to v2 projection",
                "data_minimization_note": "references only the existing v1 decision; no new evidence imported",
                "code_commit": code_commit,
            })
            evidence_added += 1
        for dimension, status_field in DIMENSION_FIELDS:
            thread_id = deterministic_id(
                "legacy-claim-thread-v2", (decision["annotation_thread_id"], dimension)
            )
            if store.connection.execute(
                "SELECT 1 FROM ground_truth_claim_threads_v2 WHERE annotation_thread_id=?", (thread_id,)
            ).fetchone() is None:
                store.create_claim_thread_v2(
                    runner_id=decision["runner_id"], subject_kind="recorded_session",
                    subject_key=decision["source_file"], opened_by="d4_v1_migration",
                    opened_at=migration_timestamp, annotation_thread_id=thread_id,
                )
            claim_id = deterministic_id("legacy-claim-v2", (decision["decision_id"], dimension))
            if store.connection.execute(
                "SELECT 1 FROM ground_truth_semantic_claims_v2 WHERE claim_id=?", (claim_id,)
            ).fetchone() is not None:
                continue
            supersedes = None
            if decision["supersedes_decision_id"]:
                supersedes = deterministic_id(
                    "legacy-claim-v2", (decision["supersedes_decision_id"], dimension)
                )
            store.add_semantic_claim_v2({
                "claim_id": claim_id, "annotation_thread_id": thread_id,
                "revision": decision["revision"], "supersedes_claim_id": supersedes,
                "decision_kind": "migration", "runner_id": decision["runner_id"],
                "subject_kind": "recorded_session", "subject_key": decision["source_file"],
                "source_file": decision["source_file"], "source_sha256": decision["source_sha256"],
                "dimension_name": dimension, "claim_value": decision[dimension],
                "claim_status": decision[status_field], "claim_kind": "legacy_unclassified",
                "evidence_level": decision["evidence_level"], "author_id": decision["author_id"],
                "author_role": decision["author_role"], "rationale": decision["comment"],
                "uncertainty_reason": decision["uncertainty_reason"] or (
                    "legacy_v1_reason_not_recorded"
                    if decision[status_field] in {"uncertain", "abstained", "not_applicable"}
                    else None
                ),
                "evidence_observed_at": decision["evidence_observed_at"],
                "decision_timestamp": decision["decision_timestamp"],
                "effective_from": decision["effective_from"],
                "label_available_at": decision["label_available_at"],
                "provenance_granularity": "legacy_decision_wide",
                "legacy_decision_id": decision["decision_id"], "code_commit": code_commit,
            })
            store.link_claim_evidence_v2(
                claim_id=claim_id, evidence_id=evidence_id, support_role="provenance_only",
                rationale="v1 evidence applied to the full decision; atomic support is not inferred",
            )
            claims_added += 1
    migrated = [dict(row) for row in store.connection.execute(
        """SELECT claim_id,legacy_decision_id,dimension_name,claim_value,claim_status,
                  evidence_level,provenance_granularity
           FROM ground_truth_semantic_claims_v2
           WHERE legacy_decision_id IS NOT NULL
           ORDER BY claim_id"""
    ).fetchall()]
    return {
        "legacy_decision_count": len(legacy), "claims_added": claims_added,
        "evidence_added": evidence_added, "migrated_claim_count": len(migrated),
        "logical_manifest": logical_records_hash(
            migrated, domain="d4-gt-v1-to-v2-migration-v1", order_by=("claim_id",)
        ),
    }
