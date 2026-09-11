"""Build the authorized synthetic-only Ground Truth Addendum validation fixture."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ground_truth_addendum.canonical import logical_hash
from src.ground_truth_addendum.contracts import ADDENDUM_VERSION
from src.ground_truth_addendum.publication import (
    export_tables,
    feature_snapshot_manifest,
    publish_gold,
    review_data_manifest,
)
from src.ground_truth_addendum.store import GroundTruthStore


FIXED = {
    "threads": [
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
    ],
    "decisions": [
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2",
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3",
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb4",
    ],
}


def _decision(
    *, decision_id: str, thread: str, revision: int, supersedes: str | None,
    source_file: str, source_sha256: str, evidence_level: str,
    function: str | None, function_status: str, decision_timestamp: str,
    label_available_at: str, comment: str,
) -> dict:
    return {
        "decision_id": decision_id,
        "annotation_thread_id": thread,
        "revision": revision,
        "supersedes_decision_id": supersedes,
        "decision_kind": "annotation" if revision == 1 else "correction",
        "runner_id": "synthetic_runner_001",
        "source_file": source_file,
        "source_sha256": source_sha256,
        "author_id": "synthetic_reviewer",
        "author_role": "data_owner",
        "evidence_observed_at": decision_timestamp,
        "decision_timestamp": decision_timestamp,
        "effective_from": source_file.split("synthetic_session_", 1)[1][:10] + "T06:00:00Z",
        "label_available_at": label_available_at,
        "evidence_type": "synthetic_training_log",
        "evidence_reference": f"synthetic://{source_file}",
        "evidence_level": evidence_level,
        "session_context": "training_environment",
        "session_context_status": "asserted",
        "workout_structure": "single_exercise",
        "workout_structure_status": "asserted",
        "primary_function": function,
        "primary_function_status": function_status,
        "primary_function_subtype": None,
        "primary_function_subtype_status": "abstained",
        "component_role": "main_set",
        "component_role_status": "asserted",
        "performance_relevance": "low" if function in {"easy", "recovery"} else "moderate",
        "performance_relevance_status": "asserted",
        "training_load_relevance": "moderate",
        "training_load_relevance_status": "asserted",
        "uncertainty_reason": "subtype not supported by synthetic evidence",
        "comment": comment,
        "code_commit": "synthetic-validation",
        "contract_version": ADDENDUM_VERSION,
    }


def build(output_dir: Path) -> dict:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    database = output_dir / "ground_truth_synthetic.sqlite"
    sessions = [
        ("synthetic_session_2023-05-01_a.json", "1" * 64, "2023-05-01"),
        ("synthetic_session_2024-06-01_b.json", "2" * 64, "2024-06-01"),
        ("synthetic_session_2025-07-01_c.json", "3" * 64, "2025-07-01"),
    ]
    source_manifest = logical_hash(
        [{"runner_id": "synthetic_runner_001", "source_file": f, "source_sha256": h, "session_date": d} for f, h, d in sessions],
        domain="d4-gt-synthetic-source-v1",
    )
    with GroundTruthStore(database) as store:
        store.initialize()
        for source_file, source_sha256, session_date in sessions:
            store.add_source_session({
                "runner_id": "synthetic_runner_001",
                "source_file": source_file,
                "source_sha256": source_sha256,
                "session_date": session_date,
                "source_manifest": source_manifest,
            })

        population_manifest = store.source_population_manifest()
        features = [
            {"runner_id": "synthetic_runner_001", "source_file": f, "relative_pace_percentile": i / 4}
            for i, (f, _, _) in enumerate(sessions, start=1)
        ]
        feature_manifest = feature_snapshot_manifest(
            features, feature_contract_version="synthetic-features-v1",
            knowledge_cutoff="2026-08-01T00:00:00Z",
        )
        batch_id = store.create_sampling_batch({
            "runner_id": "synthetic_runner_001",
            "sampling_strategy_version": "synthetic-stratified-v1",
            "sampling_purpose": "pilot",
            "population_manifest": population_manifest,
            "population_size": 3,
            "requested_unit_count": 2,
            "selection_method": "stratified",
            "random_seed": 17,
            "strata_definition": {"period": ["development", "validation"]},
            "selection_algorithm": "synthetic_fixture_only",
            "feature_snapshot_manifest": feature_manifest,
            "knowledge_cutoff": "2026-08-01T00:00:00Z",
            "created_at": "2026-08-01T00:00:00Z",
            "created_by": "synthetic_builder",
            "code_commit": "synthetic-validation",
            "notes": "No real BioQuantumRunner sessions are present.",
        })
        for order, (source_file, source_sha256, session_date) in enumerate(sessions[:2], start=1):
            visible = [{"runner_id": "synthetic_runner_001", "source_file": source_file, "source_sha256": source_sha256}]
            data_manifest = review_data_manifest(
                visible, semantics_mode="as_of", knowledge_cutoff="2026-08-01T00:00:00Z"
            )
            _, record_id = store.create_review_unit({
                "runner_id": "synthetic_runner_001",
                "review_unit_type": "individual_session",
                "sampling_batch_id": batch_id,
                "sampling_strategy_version": "synthetic-stratified-v1",
                "sampling_stratum": "synthetic_period",
                "selection_reason": "synthetic validation fixture",
                "selection_probability": 2 / 3,
                "selection_probability_missing_reason": None,
                "temporal_partition": "development" if session_date.startswith("2023") else "validation",
                "review_status": "completed",
                "reviewer_id": "synthetic_reviewer",
                "reviewer_role": "data_owner",
                "semantics_mode": "as_of",
                "knowledge_cutoff": "2026-08-01T00:00:00Z",
                "data_manifest": data_manifest,
                "feature_contract_version": "synthetic-features-v1",
                "code_commit": "synthetic-validation",
            })
            store.add_review_membership({
                "review_unit_record_id": record_id,
                "runner_id": "synthetic_runner_001",
                "source_file": source_file,
                "source_sha256": source_sha256,
                "presentation_order": 1,
                "membership_reason": "synthetic individual review",
            })
        store.lock_sampling_batch(batch_id)

        for thread, (source_file, _, _) in zip(FIXED["threads"], sessions):
            store.create_annotation_thread(
                runner_id="synthetic_runner_001", source_file=source_file,
                opened_by="synthetic_reviewer", opened_at="2026-01-01T00:00:00Z",
                annotation_thread_id=thread,
            )
        store.add_session_decision(_decision(
            decision_id=FIXED["decisions"][0], thread=FIXED["threads"][0], revision=1,
            supersedes=None, source_file=sessions[0][0], source_sha256=sessions[0][1],
            evidence_level="verified", function="easy", function_status="asserted",
            decision_timestamp="2024-01-01T00:00:00Z", label_available_at="2024-01-01T00:00:00Z",
            comment="synthetic verified decision",
        ))
        store.add_session_decision(_decision(
            decision_id=FIXED["decisions"][1], thread=FIXED["threads"][0], revision=2,
            supersedes=FIXED["decisions"][0], source_file=sessions[0][0], source_sha256=sessions[0][1],
            evidence_level="verified", function="recovery", function_status="asserted",
            decision_timestamp="2026-01-02T00:00:00Z", label_available_at="2026-01-02T00:00:00Z",
            comment="synthetic correction available only in 2026",
        ))
        store.add_session_decision(_decision(
            decision_id=FIXED["decisions"][2], thread=FIXED["threads"][1], revision=1,
            supersedes=None, source_file=sessions[1][0], source_sha256=sessions[1][1],
            evidence_level="reported", function="sustained_quality", function_status="asserted",
            decision_timestamp="2024-06-02T00:00:00Z", label_available_at="2024-06-02T00:00:00Z",
            comment="synthetic reported decision",
        ))
        store.add_session_decision(_decision(
            decision_id=FIXED["decisions"][3], thread=FIXED["threads"][2], revision=1,
            supersedes=None, source_file=sessions[2][0], source_sha256=sessions[2][1],
            evidence_level="verified", function=None, function_status="abstained",
            decision_timestamp="2025-07-02T00:00:00Z", label_available_at="2025-07-02T00:00:00Z",
            comment="synthetic explicit abstention",
        ))

        publication_dir = output_dir / "publications"
        core = publish_gold(
            store, product="gold_core", knowledge_cutoff="2026-08-01T00:00:00Z",
            published_at="2026-08-01T00:00:00Z", code_commit="synthetic-validation",
            output_dir=publication_dir,
            publication_id="99999999-9999-4999-8999-999999999991",
        )
        extended = publish_gold(
            store, product="gold_extended", knowledge_cutoff="2026-08-01T00:00:00Z",
            published_at="2026-08-01T00:00:00Z", code_commit="synthetic-validation",
            output_dir=publication_dir,
            publication_id="99999999-9999-4999-8999-999999999992",
        )
        table_hashes = export_tables(store, output_dir / "snapshots")
        summary = {
            "synthetic_only": True,
            "real_session_count": 0,
            "synthetic_session_count": 3,
            "review_unit_count": 2,
            "selected_real_review_units": 0,
            "schema_manifest": store.schema_manifest(),
            "population_manifest": population_manifest,
            "gold_core_logical_hash": core["logical_hash"],
            "gold_extended_logical_hash": extended["logical_hash"],
            "table_logical_hashes": table_hashes,
        }
    (output_dir / "validation_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
