"""Explicit, idempotent v2 membership projection for D4.1.

Projection is read-only.  Materialization is a separate operation and is never
called by store initialization.  Neither path creates gap or unknown
components.
"""

from __future__ import annotations

from typing import Any

from .canonical import logical_records_hash
from .contracts import COMPONENT_MIGRATION_VERSION, COMPONENT_VERSION
from .ids import deterministic_id
from .store import GroundTruthStore, _utc_timestamp


def project_memberships_v2_as_recorded_components(
    store: GroundTruthStore, *, knowledge_cutoff: str
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for membership in store.latest_workout_memberships_as_of_v2(knowledge_cutoff):
        if membership["membership_state"] != "included":
            continue
        component_id = deterministic_id(
            "membership-component-v3",
            (
                membership["runner_id"], membership["workout_group_id"],
                membership["membership_decision_id"], COMPONENT_MIGRATION_VERSION,
            ),
        )
        projected.append({
            "component_id": component_id,
            "runner_id": membership["runner_id"],
            "workout_group_id": membership["workout_group_id"],
            "group_decision_id": membership["group_decision_id"],
            "component_order": membership["component_order"],
            "recording_state": "recorded",
            "membership_decision_id": membership["membership_decision_id"],
            "activity_catalog_version": None,
            "activity_type_id": None,
            "component_role": membership["component_role"],
            "start_time": None,
            "end_time": None,
            "temporal_precision": "unknown",
            "duration_s": None,
            "duration_basis": "unknown",
            "claim_kind": membership["claim_kind"],
            "evidence_level": membership["evidence_level"],
            "author_id": membership["author_id"],
            "author_role": membership["author_role"],
            "evidence_observed_at": membership["evidence_observed_at"],
            "decision_timestamp": membership["decision_timestamp"],
            "effective_from": membership["effective_from"],
            "label_available_at": membership["label_available_at"],
            "uncertainty_reason": None,
            "rationale": "read-only projection of an included v2 recorded-session membership",
            "contract_version": COMPONENT_VERSION,
            "projection_only": True,
        })
    projected.sort(key=lambda row: (row["runner_id"], row["workout_group_id"], row["component_order"], row["component_id"]))
    return projected


def materialize_membership_projection_v3(
    store: GroundTruthStore, *, knowledge_cutoff: str,
    migration_timestamp: str, code_commit: str,
) -> dict[str, Any]:
    """Materialize only explicit recorded-membership projections.

    Memberships without pre-existing evidence links are deliberately skipped;
    provenance is never manufactured.
    """
    normalized_migration_timestamp = _utc_timestamp(migration_timestamp)
    projected = project_memberships_v2_as_recorded_components(
        store, knowledge_cutoff=knowledge_cutoff
    )
    added = skipped_without_evidence = already_present = 0
    prepared: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for raw in projected:
        row = dict(raw); row.pop("projection_only")
        component_decision_id = deterministic_id(
            "membership-component-decision-v3", (row["component_id"], row["group_decision_id"], COMPONENT_MIGRATION_VERSION),
        )
        if store.connection.execute("SELECT 1 FROM ground_truth_workout_components_v3 WHERE component_decision_id=?", (component_decision_id,)).fetchone():
            already_present += 1; continue
        evidence = [dict(item) for item in store.connection.execute(
            """SELECT evidence_id,support_role,rationale
               FROM ground_truth_membership_evidence_links_v2
               WHERE membership_decision_id=? ORDER BY evidence_id,support_role""",
            (row["membership_decision_id"],),
        ).fetchall()]
        if not evidence:
            skipped_without_evidence += 1
            continue
        row.update({
            "component_decision_id": component_decision_id,
            "supersedes_component_decision_id": None,
            "decision_kind": "migration",
            "decision_timestamp": normalized_migration_timestamp,
            "label_available_at": max(
                _utc_timestamp(str(row["label_available_at"])),
                normalized_migration_timestamp,
            ),
            "code_commit": code_commit,
        })
        prepared.append((row, evidence))
    columns = (
        "component_decision_id", "component_id", "supersedes_component_decision_id", "decision_kind",
        "runner_id", "workout_group_id", "group_decision_id", "component_order", "recording_state",
        "membership_decision_id", "activity_catalog_version", "activity_type_id", "component_role",
        "start_time", "end_time", "temporal_precision", "duration_s", "duration_basis", "claim_kind",
        "evidence_level", "author_id", "author_role", "evidence_observed_at", "decision_timestamp",
        "effective_from", "label_available_at", "uncertainty_reason", "rationale", "code_commit", "contract_version",
    )
    with store.transaction() as db:
        for row, evidence in prepared:
            store._insert_workout_component_v3(db, row, evidence, columns=columns)
            added += 1
    migrated_ids = [row["component_decision_id"] for row, _ in prepared]
    if not migrated_ids:
        migrated_ids = [deterministic_id(
            "membership-component-decision-v3", (row["component_id"], row["group_decision_id"], COMPONENT_MIGRATION_VERSION)
        ) for row in projected]
    marks = ",".join("?" for _ in migrated_ids) or "NULL"
    materialized = [dict(row) for row in store.connection.execute(
        f"""SELECT component_decision_id,component_id,runner_id,workout_group_id,
                  group_decision_id,component_order,recording_state,membership_decision_id
           FROM ground_truth_workout_components_v3
           WHERE component_decision_id IN ({marks}) ORDER BY component_decision_id""", migrated_ids
    ).fetchall()]
    return {
        "migration_version": COMPONENT_MIGRATION_VERSION,
        "projected_count": len(projected),
        "added_count": added,
        "already_present_count": already_present,
        "skipped_without_evidence_count": skipped_without_evidence,
        "materialized_count": len(materialized),
        "logical_manifest": logical_records_hash(
            materialized, domain="d4-gt-v2-to-v3-membership-migration-v1",
            order_by=("component_decision_id",),
        ),
    }
