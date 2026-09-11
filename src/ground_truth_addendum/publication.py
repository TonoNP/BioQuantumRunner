"""Reproducible Parquet/JSON publications derived from the SQLite authority."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from .canonical import binary_file_hash, canonical_json, logical_hash, logical_records_hash
from .contracts import ADDENDUM_VERSION, SCHEMA_VERSION
from .ids import new_event_id
from .ids import validate_uuid
from .store import GroundTruthStore


def feature_snapshot_manifest(
    rows: Sequence[Mapping[str, Any]], *, feature_contract_version: str, knowledge_cutoff: str
) -> str:
    payload = {
        "feature_contract_version": feature_contract_version,
        "knowledge_cutoff": knowledge_cutoff,
        "rows_hash": logical_records_hash(
            rows, domain="d4-gt-feature-snapshot-rows-v1", order_by=("runner_id", "source_file")
        ),
    }
    return logical_hash(payload, domain="d4-gt-feature-snapshot-manifest-v1")


def review_data_manifest(
    rows: Sequence[Mapping[str, Any]], *, semantics_mode: str, knowledge_cutoff: str
) -> str:
    payload = {
        "semantics_mode": semantics_mode,
        "knowledge_cutoff": knowledge_cutoff,
        "visible_rows_hash": logical_records_hash(
            rows, domain="d4-gt-review-visible-rows-v1", order_by=("runner_id", "source_file")
        ),
    }
    return logical_hash(payload, domain="d4-gt-review-data-manifest-v1")


def publish_gold(
    store: GroundTruthStore,
    *,
    product: str,
    knowledge_cutoff: str,
    published_at: str,
    code_commit: str,
    output_dir: Path,
    publication_id: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = store.build_gold(product=product, knowledge_cutoff=knowledge_cutoff)
    order = ("runner_id", "source_file", "annotation_thread_id", "revision")
    records = sorted(records, key=lambda row: tuple(str(row.get(key, "")) for key in order))
    content_hash = logical_records_hash(records, domain=f"d4-gt-{product}-rows-v1", order_by=order)
    population_manifest = store.source_population_manifest()
    evidence_manifest = logical_records_hash(
        [
            {
                "decision_id": row["decision_id"],
                "evidence_level": row["evidence_level"],
                "evidence_type": row["evidence_type"],
                "evidence_reference": row["evidence_reference"],
                "label_available_at": row["label_available_at"],
            }
            for row in records
        ],
        domain=f"d4-gt-{product}-evidence-v1",
        order_by=("decision_id",),
    )

    parquet_path = output_dir / f"{product}.parquet"
    frame = pd.DataFrame(records)
    if not frame.empty:
        frame = frame.reindex(sorted(frame.columns), axis=1)
    frame.to_parquet(parquet_path, index=False)
    binary_hash = binary_file_hash(parquet_path)
    publication_id = publication_id or new_event_id()
    validate_uuid(publication_id, version=4)
    receipt = {
        "publication_id": publication_id,
        "product_name": product,
        "published_at": published_at,
        "knowledge_cutoff": knowledge_cutoff,
        "population_manifest": population_manifest,
        "evidence_manifest": evidence_manifest,
        "logical_hash": content_hash,
        "binary_hash": binary_hash,
        "row_count": len(records),
        "contract_version": ADDENDUM_VERSION,
        "schema_version": SCHEMA_VERSION,
        "code_commit": code_commit,
        "receipt_path": f"{product}.receipt.json",
        "logical_hash_is_not_binary_hash": True,
    }
    receipt_path = output_dir / receipt["receipt_path"]
    receipt_path.write_text(canonical_json(receipt) + "\n", encoding="utf-8", newline="\n")
    with store.transaction() as db:
        db.execute(
            """INSERT INTO ground_truth_publications
            (publication_id,product_name,published_at,knowledge_cutoff,population_manifest,
             evidence_manifest,logical_hash,binary_hash,row_count,contract_version,
             schema_version,code_commit,receipt_path)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                publication_id, product, published_at, knowledge_cutoff, population_manifest,
                evidence_manifest, content_hash, binary_hash, len(records), ADDENDUM_VERSION,
                SCHEMA_VERSION, code_commit, receipt["receipt_path"],
            ),
        )
    return receipt


def export_tables(store: GroundTruthStore, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for table in store.table_names():
        frame = pd.read_sql_query(f"SELECT * FROM {table}", store.connection)
        if not frame.empty:
            frame = frame.sort_values(list(frame.columns), kind="stable").reset_index(drop=True)
        path = output_dir / f"{table}.parquet"
        frame.to_parquet(path, index=False)
        hashes[table] = logical_records_hash(
            frame.fillna("").to_dict("records"),
            domain=f"d4-gt-table-{table}-v1",
            order_by=tuple(frame.columns),
        )
    return hashes
