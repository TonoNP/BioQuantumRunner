"""Build and publish the canonical D1 Polar ingestion artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.polar_json import (  # noqa: E402
    ERROR_COLUMNS,
    PIPELINE_VERSION,
    SESSION_COLUMNS,
    extract_date_from_filename,
    ingest_polar_file,
)


CURRENT_CORPUS_EXPECTATIONS = {
    "total_files_discovered": 2855,
    "sessions_ingested": 2851,
    "unrecoverable_binary": 4,
    "invalid_json": 0,
    "unsupported_schema": 0,
    "normalization_errors": 0,
    "source_read_errors": 0,
    "unclassified_files": 0,
}

CURRENT_BINARY_INVENTORY = {
    "training-session-2022-07-07-7438082946-d27d5b16-ac92-449e-9352-d2497e3d1426.json": (
        63773,
        "dd809e58f6acc86ac731937597c5dfc0815523d917241923d13e1f77cf4f0790",
    ),
    "training-session-2022-10-25-7511911729-e68bd47f-625d-471b-8bfd-8fd390e6dd03.json": (
        65280,
        "fc432c53294bf76102a4a9301f7c0bba592daee28bc06d5749bce5203cbca179",
    ),
    "training-session-2023-03-21-7605645063-2925b53c-bf1a-47d0-87c2-e3eb54e8af69.json": (
        65415,
        "5533caaa5d838b7e68ebf3c11dc2fa96af75ccb7f0865e01e695bfe226c56ee7",
    ),
    "training-session-2024-01-09-7795413708-f3155683-6b5a-4026-a662-716862f6b95c.json": (
        61113,
        "acca125e706ce0fecde07aa5b9105c0c612db4fa73cfd8a152283f5c14a14465",
    ),
}

CANONICAL_TARGETS = {
    "sessions_csv": Path("data/processed/sessions_master.csv"),
    "sessions_parquet": Path("data/processed/sessions_master.parquet"),
    "errors_csv": Path("data/errors/ingestion_errors.csv"),
    "errors_parquet": Path("data/errors/ingestion_errors.parquet"),
    "summary_json": Path("data/processed/ingestion_summary.json"),
}


def _json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def canonical_manifest_sha256(rows: list[dict[str, Any]], columns: list[str]) -> str:
    canonical_rows: list[dict[str, Any]] = []
    for source in sorted(rows, key=lambda row: row["source_file"]):
        row: dict[str, Any] = {}
        for column in columns:
            value = _json_scalar(source.get(column))
            if column == "quality_flags":
                value = sorted(value or [])
            row[column] = value
        canonical_rows.append(row)
    payload = json.dumps(
        canonical_rows,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _csv_value(column: str, value: Any) -> str | int | float:
    if value is None:
        return ""
    if column == "quality_flags":
        return json.dumps(sorted(value), ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for source in rows:
            writer.writerow(
                {column: _csv_value(column, source.get(column)) for column in columns}
            )


def write_parquet(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows, columns=columns)
    if "quality_flags" in frame.columns:
        frame["quality_flags"] = frame["quality_flags"].apply(lambda value: list(value or []))
    frame.to_parquet(path, index=False, engine="pyarrow")


def _read_csv_logical(path: Path, columns: list[str]) -> list[dict[str, Any]]:
    numeric = {
        "file_size_bytes",
        "duration_s",
        "distance_km",
        "avg_hr",
        "max_hr",
        "calories",
    }
    boolean = {"modeling_eligible"}
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise ValueError(f"Unexpected CSV columns in {path}")
        for raw in reader:
            row: dict[str, Any] = {}
            for column in columns:
                value = raw[column]
                if value == "":
                    row[column] = None
                elif column == "quality_flags":
                    row[column] = json.loads(value)
                elif column in boolean:
                    if value not in {"true", "false"}:
                        raise ValueError(f"Invalid CSV boolean in {path}: {value}")
                    row[column] = value == "true"
                elif column == "file_size_bytes":
                    row[column] = int(value)
                elif column in numeric:
                    row[column] = float(value)
                else:
                    row[column] = value
            rows.append(row)
    return rows


def _read_parquet_logical(path: Path, columns: list[str]) -> list[dict[str, Any]]:
    frame = pd.read_parquet(path, engine="pyarrow")
    if list(frame.columns) != columns:
        raise ValueError(f"Unexpected Parquet columns in {path}")
    rows: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        row: dict[str, Any] = {}
        for column in columns:
            value = raw.get(column)
            if isinstance(value, float) and math.isnan(value):
                value = None
            if column == "quality_flags":
                value = [] if value is None else list(value)
            row[column] = _json_scalar(value)
        rows.append(row)
    return rows


def _write_and_verify_dataset(
    csv_path: Path,
    parquet_path: Path,
    rows: list[dict[str, Any]],
    columns: list[str],
) -> str:
    write_csv(csv_path, rows, columns)
    write_parquet(parquet_path, rows, columns)
    expected_hash = canonical_manifest_sha256(rows, columns)
    csv_hash = canonical_manifest_sha256(_read_csv_logical(csv_path, columns), columns)
    parquet_hash = canonical_manifest_sha256(
        _read_parquet_logical(parquet_path, columns), columns
    )
    if not expected_hash == csv_hash == parquet_hash:
        raise ValueError(f"CSV/Parquet logical mismatch for {csv_path.stem}")
    return expected_hash


def _unexpected_error(path: Path, project_root: Path, error: Exception) -> dict[str, Any]:
    try:
        content = path.read_bytes()
        source_hash = hashlib.sha256(content).hexdigest()
        size = len(content)
    except OSError:
        source_hash = hashlib.sha256(b"").hexdigest()
        size = 0
    row = {column: None for column in ERROR_COLUMNS}
    row.update(
        {
            "source_file": path.name,
            "source_path": path.resolve().relative_to(project_root.resolve()).as_posix(),
            "date_from_filename": extract_date_from_filename(path.name),
            "ingestion_status": "normalization_error",
            "error_type": "UnexpectedIngestionError",
            "error_message": f"Unexpected ingestion failure: {type(error).__name__}",
            "file_size_bytes": size,
            "sha256": source_hash,
            "modeling_eligible": False,
        }
    )
    return row


def _build_summary(
    *,
    project_root: Path,
    sessions: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    sessions_hash: str,
    errors_hash: str,
    validation_failures: list[str],
    run_timestamp: str,
) -> dict[str, Any]:
    statuses = [row["ingestion_status"] for row in errors]
    session_dates = sorted(
        row["session_date"] for row in sessions if row.get("session_date") is not None
    )
    return {
        "run_timestamp_utc": run_timestamp,
        "pipeline_version": PIPELINE_VERSION,
        "source_directory": "data/raw/polar",
        "total_files_discovered": len(sessions) + len(errors),
        "total_files_accounted": len(sessions) + len(errors),
        "sessions_ingested": len(sessions),
        "unrecoverable_binary": statuses.count("unrecoverable_binary"),
        "pending_manual_reconstruction": statuses.count("unrecoverable_binary"),
        "invalid_json": statuses.count("invalid_json"),
        "unsupported_schema": statuses.count("unsupported_schema"),
        "normalization_errors": statuses.count("normalization_error"),
        "source_read_errors": statuses.count("source_read_error"),
        "unclassified_files": statuses.count("unclassified"),
        "legacy_schema_count": sum(
            row["schema_version"] == "polar_v1_legacy" for row in sessions
        ),
        "modern_schema_count": sum(
            row["schema_version"] == "polar_v2_modern" for row in sessions
        ),
        "files_with_quality_warnings": sum(
            row["quality_status"] == "warning" for row in sessions
        ),
        "modeling_eligible_count": sum(row["modeling_eligible"] for row in sessions),
        "modeling_excluded_count": sum(
            not row["modeling_eligible"] for row in sessions
        ),
        "date_min": session_dates[0] if session_dates else None,
        "date_max": session_dates[-1] if session_dates else None,
        "sessions_master_sha256": sessions_hash,
        "ingestion_errors_sha256": errors_hash,
        "validation_status": "failed" if validation_failures else "passed",
        "validation_failures": validation_failures,
    }


def _validate_current_corpus(
    sessions: list[dict[str, Any]], errors: list[dict[str, Any]]
) -> list[str]:
    failures: list[str] = []
    statuses = [row["ingestion_status"] for row in errors]
    actual = {
        "total_files_discovered": len(sessions) + len(errors),
        "sessions_ingested": len(sessions),
        "unrecoverable_binary": statuses.count("unrecoverable_binary"),
        "invalid_json": statuses.count("invalid_json"),
        "unsupported_schema": statuses.count("unsupported_schema"),
        "normalization_errors": statuses.count("normalization_error"),
        "source_read_errors": statuses.count("source_read_error"),
        "unclassified_files": statuses.count("unclassified"),
    }
    for key, expected in CURRENT_CORPUS_EXPECTATIONS.items():
        if actual[key] != expected:
            failures.append(f"{key}: expected {expected}, found {actual[key]}")

    session_names = {row["source_file"] for row in sessions}
    error_names = {row["source_file"] for row in errors}
    if len(session_names) != len(sessions):
        failures.append("sessions_master contains duplicate source_file values")
    if len(error_names) != len(errors):
        failures.append("ingestion_errors contains duplicate source_file values")
    if session_names & error_names:
        failures.append("sessions_master and ingestion_errors intersect")
    if len(session_names | error_names) != 2855:
        failures.append("source_file union does not contain 2,855 unique files")

    schemas = {row["schema_version"] for row in sessions}
    if not {"polar_v1_legacy", "polar_v2_modern"}.issubset(schemas):
        failures.append("both supported Polar schemas are not represented")

    dates = sorted(row["session_date"] for row in sessions if row["session_date"])
    if not dates or not dates[-1].startswith("2026-03"):
        failures.append("date_max is not coherent with March 2026")

    binary_rows = {
        row["source_file"]: row
        for row in errors
        if row["ingestion_status"] == "unrecoverable_binary"
    }
    if set(binary_rows) != set(CURRENT_BINARY_INVENTORY):
        failures.append("unrecoverable_binary inventory differs from approved Annex D")
    for filename, (expected_size, expected_hash) in CURRENT_BINARY_INVENTORY.items():
        row = binary_rows.get(filename)
        if row is None:
            continue
        if row["file_size_bytes"] != expected_size or row["sha256"] != expected_hash:
            failures.append(f"binary evidence mismatch: {filename}")
        if row["modeling_eligible"] is not False:
            failures.append(f"binary is modeling eligible: {filename}")
        for field in (
            "session_date",
            "sport",
            "duration_s",
            "distance_km",
            "avg_hr",
            "max_hr",
            "calories",
        ):
            if row[field] is not None:
                failures.append(f"binary metric is not null: {filename}.{field}")

    if any(row["pipeline_version"] != PIPELINE_VERSION for row in sessions):
        failures.append("sessions_master contains an invalid pipeline_version")
    return failures


def _promote(project_root: Path, staging: Path) -> None:
    backup = staging / "_previous"
    backup.mkdir(parents=True, exist_ok=True)
    moved_existing: list[tuple[Path, Path]] = []
    promoted: list[Path] = []
    try:
        for key, relative_target in CANONICAL_TARGETS.items():
            target = project_root / relative_target
            staged = staging / relative_target
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                saved = backup / relative_target
                saved.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, saved)
                moved_existing.append((saved, target))
            os.replace(staged, target)
            promoted.append(target)
    except Exception:
        for target in reversed(promoted):
            if target.exists():
                target.unlink()
        for saved, target in reversed(moved_existing):
            if saved.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(saved, target)
        raise


def build_dataset(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    project_root = project_root.resolve()
    raw_dir = project_root / "data/raw/polar"
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"Raw directory not found: {raw_dir}")

    run_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_id = run_timestamp.replace(":", "-")
    staging = project_root / "data/.d1_staging" / run_id
    staging.mkdir(parents=True, exist_ok=False)

    json_files = sorted(raw_dir.glob("*.json"), key=lambda path: path.name)
    sessions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for path in json_files:
        try:
            row = ingest_polar_file(path, project_root)
        except Exception as error:
            row = _unexpected_error(path, project_root, error)
        if row["ingestion_status"] == "ingested":
            sessions.append(row)
        else:
            errors.append(row)

    sessions.sort(key=lambda row: row["source_file"])
    errors.sort(key=lambda row: row["source_file"])

    sessions_hash = canonical_manifest_sha256(sessions, SESSION_COLUMNS)
    errors_hash = canonical_manifest_sha256(errors, ERROR_COLUMNS)
    validation_failures = _validate_current_corpus(sessions, errors)
    output_error: Exception | None = None
    try:
        verified_sessions_hash = _write_and_verify_dataset(
            staging / CANONICAL_TARGETS["sessions_csv"],
            staging / CANONICAL_TARGETS["sessions_parquet"],
            sessions,
            SESSION_COLUMNS,
        )
        verified_errors_hash = _write_and_verify_dataset(
            staging / CANONICAL_TARGETS["errors_csv"],
            staging / CANONICAL_TARGETS["errors_parquet"],
            errors,
            ERROR_COLUMNS,
        )
        if verified_sessions_hash != sessions_hash or verified_errors_hash != errors_hash:
            validation_failures.append("verified logical hashes differ from source rows")
    except Exception as error:
        output_error = error
        validation_failures.append(f"artifact generation failed: {type(error).__name__}")

    summary = _build_summary(
        project_root=project_root,
        sessions=sessions,
        errors=errors,
        sessions_hash=sessions_hash,
        errors_hash=errors_hash,
        validation_failures=validation_failures,
        run_timestamp=run_timestamp,
    )
    summary_path = staging / CANONICAL_TARGETS["summary_json"]
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if validation_failures:
        detail = f"; output error: {output_error}" if output_error else ""
        raise RuntimeError(
            "D1 validation failed; diagnostic artifacts retained at "
            f"{staging}: {'; '.join(validation_failures)}{detail}"
        )

    _promote(project_root, staging)
    previous = staging / "_previous"
    if previous.exists():
        shutil.rmtree(previous)
    shutil.rmtree(staging)
    return summary


def main() -> int:
    try:
        summary = build_dataset()
    except Exception as error:
        print(f"D1 FAILED: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
