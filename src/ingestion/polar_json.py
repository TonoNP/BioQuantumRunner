"""Canonical Polar JSON ingestion for BioQuantumRunner D1."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.analysis.training_session import TrainingSession


PIPELINE_VERSION = "d1-1.1"

SESSION_COLUMNS = [
    "source_file",
    "source_path",
    "sha256",
    "file_size_bytes",
    "source_encoding",
    "schema_version",
    "ingestion_status",
    "pipeline_version",
    "date_from_filename",
    "session_date",
    "sport",
    "duration_s",
    "distance_km",
    "avg_hr",
    "max_hr",
    "calories",
    "quality_status",
    "quality_flags",
    "modeling_eligible",
]

ERROR_COLUMNS = [
    "source_file",
    "source_path",
    "date_from_filename",
    "ingestion_status",
    "error_type",
    "error_message",
    "file_size_bytes",
    "sha256",
    "session_date",
    "sport",
    "duration_s",
    "distance_km",
    "avg_hr",
    "max_hr",
    "calories",
    "modeling_eligible",
]

WARNING_FLAGS = {
    "filename_date_mismatch",
    "hybrid_schema",
    "invalid_avg_hr",
    "invalid_calories",
    "invalid_distance",
    "invalid_duration",
    "invalid_filename_date",
    "invalid_max_hr",
    "negative_calories",
    "negative_distance",
    "non_positive_avg_hr",
    "non_positive_duration",
    "non_positive_max_hr",
    "schema_fallback_used",
}

FILENAME_DATE_RE = re.compile(r"^training-session-(\d{4}-\d{2}-\d{2})(?:-|T)")
MODERN_INDICATORS = {"durationMillis", "distanceMeters", "hrAvg"}
LEGACY_INDICATORS = {
    "duration",
    "distance",
    "averageHeartRate",
    "maximumHeartRate",
    "kiloCalories",
}


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def extract_date_from_filename(filename: str) -> str | None:
    match = FILENAME_DATE_RE.match(filename)
    if not match:
        return None
    candidate = match.group(1)
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def _relative_source_path(path: Path, project_root: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def _parse_iso_datetime(value: Any) -> tuple[str | None, bool]:
    if value is None or isinstance(value, (dict, list, bool)):
        return None, False
    text = str(value).strip()
    if not text:
        return None, False
    parse_value = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        datetime.fromisoformat(parse_value)
    except ValueError:
        return None, False
    return text, True


def _as_float(value: Any) -> tuple[float | None, bool]:
    if value is None:
        return None, True
    if isinstance(value, bool) or isinstance(value, (dict, list)):
        return None, False
    try:
        number = float(value)
        return (number, True) if math.isfinite(number) else (None, False)
    except (TypeError, ValueError, OverflowError):
        return None, False


def _legacy_duration(value: Any) -> tuple[float | None, bool]:
    if value is None:
        return None, True
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("PT") and text.endswith("S"):
            value = text[2:-1]
    return _as_float(value)


def _select_value(
    data: dict[str, Any], primary: str, secondary: str
) -> tuple[Any, bool, bool]:
    """Return value, whether any field exists, and whether fallback was used."""
    if primary in data and data.get(primary) is not None:
        return data.get(primary), True, False
    if secondary in data and data.get(secondary) is not None:
        return data.get(secondary), True, True
    return None, primary in data or secondary in data, False


def _detect_schema(data: dict[str, Any]) -> tuple[str | None, bool]:
    has_modern = any(key in data for key in MODERN_INDICATORS)
    has_legacy = any(key in data for key in LEGACY_INDICATORS)
    if has_modern:
        return "polar_v2_modern", has_legacy
    if has_legacy:
        return "polar_v1_legacy", False
    return None, False


def _decode_json(content: bytes) -> tuple[dict[str, Any] | None, str | None, str]:
    decoded_any = False
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            text = content.decode(encoding)
            decoded_any = True
        except UnicodeDecodeError:
            continue
        try:
            value = json.loads(
                text,
                parse_constant=lambda constant: (_ for _ in ()).throw(
                    ValueError(f"Non-standard JSON constant: {constant}")
                ),
            )
        except (json.JSONDecodeError, UnicodeError, ValueError):
            continue
        if not isinstance(value, dict):
            return None, encoding, "invalid_json"
        return value, encoding, "ok"
    return None, None, "invalid_json" if decoded_any else "unrecoverable_binary"


def _error_row(
    *,
    path: Path,
    project_root: Path,
    content: bytes,
    source_hash: str,
    ingestion_status: str,
    error_type: str,
    error_message: str,
) -> dict[str, Any]:
    row = {column: None for column in ERROR_COLUMNS}
    row.update(
        {
            "source_file": path.name,
            "source_path": _relative_source_path(path, project_root),
            "date_from_filename": extract_date_from_filename(path.name),
            "ingestion_status": ingestion_status,
            "error_type": error_type,
            "error_message": error_message,
            "file_size_bytes": len(content),
            "sha256": source_hash,
            "modeling_eligible": False,
        }
    )
    return row


def _normalise_session(
    *,
    data: dict[str, Any],
    path: Path,
    project_root: Path,
    content: bytes,
    source_hash: str,
    source_encoding: str,
) -> dict[str, Any] | None:
    schema, is_hybrid = _detect_schema(data)
    if schema is None:
        return None

    flags: set[str] = set()
    if is_hybrid:
        flags.add("hybrid_schema")

    date_from_filename = extract_date_from_filename(path.name)
    if date_from_filename is None:
        flags.add("invalid_filename_date")

    session_date, session_date_valid = _parse_iso_datetime(data.get("startTime"))
    if not session_date_valid:
        flags.add("missing_session_date")
    elif date_from_filename and session_date[:10] != date_from_filename:
        flags.add("filename_date_mismatch")

    modern = schema == "polar_v2_modern"

    duration_value, duration_present, fallback = _select_value(
        data,
        "durationMillis" if modern else "duration",
        "duration" if modern else "durationMillis",
    )
    if fallback:
        flags.add("schema_fallback_used")
    if not duration_present or duration_value is None:
        duration_s = None
        flags.add("missing_duration")
    else:
        if modern and not fallback:
            raw_duration, duration_valid = _as_float(duration_value)
            duration_s = raw_duration / 1000.0 if duration_valid else None
        elif modern and fallback:
            duration_s, duration_valid = _legacy_duration(duration_value)
        elif not modern and not fallback:
            duration_s, duration_valid = _legacy_duration(duration_value)
        else:
            raw_duration, duration_valid = _as_float(duration_value)
            duration_s = raw_duration / 1000.0 if duration_valid else None
        if not duration_valid:
            flags.add("invalid_duration")
        elif duration_s is not None and duration_s <= 0:
            flags.add("non_positive_duration")

    distance_value, distance_present, fallback = _select_value(
        data,
        "distanceMeters" if modern else "distance",
        "distance" if modern else "distanceMeters",
    )
    if fallback:
        flags.add("schema_fallback_used")
    if not distance_present or distance_value is None:
        distance_km = None
        flags.add("missing_distance")
    else:
        distance_m, distance_valid = _as_float(distance_value)
        distance_km = distance_m / 1000.0 if distance_valid else None
        if not distance_valid:
            flags.add("invalid_distance")
        elif distance_km is not None and distance_km < 0:
            flags.add("negative_distance")

    def optional_numeric(
        primary: str,
        secondary: str,
        missing_flag: str,
        invalid_flag: str,
        non_positive_flag: str | None = None,
        negative_flag: str | None = None,
    ) -> float | None:
        value, present, used_fallback = _select_value(data, primary, secondary)
        if used_fallback:
            flags.add("schema_fallback_used")
        if not present or value is None:
            flags.add(missing_flag)
            return None
        number, valid = _as_float(value)
        if not valid:
            flags.add(invalid_flag)
            return None
        if non_positive_flag and number is not None and number <= 0:
            flags.add(non_positive_flag)
        if negative_flag and number is not None and number < 0:
            flags.add(negative_flag)
        return number

    avg_hr = optional_numeric(
        "hrAvg" if modern else "averageHeartRate",
        "averageHeartRate" if modern else "hrAvg",
        "missing_avg_hr",
        "invalid_avg_hr",
        non_positive_flag="non_positive_avg_hr",
    )
    max_hr = optional_numeric(
        "hrMax" if modern else "maximumHeartRate",
        "maximumHeartRate" if modern else "hrMax",
        "missing_max_hr",
        "invalid_max_hr",
        non_positive_flag="non_positive_max_hr",
    )
    calories = optional_numeric(
        "calories" if modern else "kiloCalories",
        "kiloCalories" if modern else "calories",
        "missing_calories",
        "invalid_calories",
        negative_flag="negative_calories",
    )

    sport_value = data.get("sport")
    if sport_value is None or str(sport_value).strip() == "":
        sport_value = data.get("name")
    sport = None if sport_value is None or str(sport_value).strip() == "" else str(sport_value)
    if sport is None:
        flags.add("missing_sport")

    ordered_flags = sorted(flags)
    quality_status = (
        "warning"
        if flags & WARNING_FLAGS
        else "partial"
        if ordered_flags
        else "valid"
    )
    modeling_eligible = bool(
        session_date_valid
        and duration_s is not None
        and duration_s > 0
        and distance_km is not None
        and distance_km > 0
    )

    return {
        "source_file": path.name,
        "source_path": _relative_source_path(path, project_root),
        "sha256": source_hash,
        "file_size_bytes": len(content),
        "source_encoding": source_encoding,
        "schema_version": schema,
        "ingestion_status": "ingested",
        "pipeline_version": PIPELINE_VERSION,
        "date_from_filename": date_from_filename,
        "session_date": session_date,
        "sport": sport,
        "duration_s": duration_s,
        "distance_km": distance_km,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "calories": calories,
        "quality_status": quality_status,
        "quality_flags": ordered_flags,
        "modeling_eligible": modeling_eligible,
    }


def ingest_polar_file(path: str | Path, project_root: str | Path) -> dict[str, Any]:
    """Ingest one Polar source and return exactly one classified result."""
    source_path = Path(path).resolve()
    root = Path(project_root).resolve()
    try:
        content_before = source_path.read_bytes()
    except OSError as error:
        empty = b""
        return _error_row(
            path=source_path,
            project_root=root,
            content=empty,
            source_hash=sha256_bytes(empty),
            ingestion_status="source_read_error",
            error_type="SourceReadError",
            error_message=f"Unable to read source file: {type(error).__name__}",
        )

    hash_before = sha256_bytes(content_before)
    data, encoding, decode_status = _decode_json(content_before)

    try:
        content_after = source_path.read_bytes()
    except OSError as error:
        return _error_row(
            path=source_path,
            project_root=root,
            content=content_before,
            source_hash=hash_before,
            ingestion_status="source_read_error",
            error_type="SourceReadError",
            error_message=f"Unable to re-read source file: {type(error).__name__}",
        )

    if sha256_bytes(content_after) != hash_before:
        return _error_row(
            path=source_path,
            project_root=root,
            content=content_before,
            source_hash=hash_before,
            ingestion_status="source_read_error",
            error_type="SourceChangedDuringIngestionError",
            error_message="Source SHA-256 changed during ingestion",
        )

    if decode_status == "unrecoverable_binary":
        return _error_row(
            path=source_path,
            project_root=root,
            content=content_before,
            source_hash=hash_before,
            ingestion_status="unrecoverable_binary",
            error_type="BinaryContentError",
            error_message="Unable to decode source as UTF-8 or UTF-8-SIG",
        )
    if decode_status == "invalid_json" or data is None or encoding is None:
        return _error_row(
            path=source_path,
            project_root=root,
            content=content_before,
            source_hash=hash_before,
            ingestion_status="invalid_json",
            error_type="JsonDecodeError",
            error_message="Decoded source is not a valid JSON object",
        )

    row = _normalise_session(
        data=data,
        path=source_path,
        project_root=root,
        content=content_before,
        source_hash=hash_before,
        source_encoding=encoding,
    )
    if row is None:
        return _error_row(
            path=source_path,
            project_root=root,
            content=content_before,
            source_hash=hash_before,
            ingestion_status="unsupported_schema",
            error_type="UnsupportedSchemaError",
            error_message="JSON object does not match a supported Polar schema",
        )
    return row


def session_from_polar_json(path: str | Path) -> TrainingSession:
    """Compatibility adapter from canonical ingestion to TrainingSession."""
    source = Path(path).resolve()
    project_root = source
    while project_root.parent != project_root and project_root.name != "data":
        project_root = project_root.parent
    root = project_root.parent if project_root.name == "data" else source.parent
    row = ingest_polar_file(source, root)
    if row.get("ingestion_status") != "ingested":
        raise ValueError(f"Cannot create TrainingSession: {row.get('error_type')}")
    if row["distance_km"] is None or row["duration_s"] is None:
        raise ValueError("Cannot create TrainingSession without distance and duration")
    return TrainingSession(
        name=row["sport"] or "PolarSession",
        distance_km=row["distance_km"],
        duration_s=int(round(row["duration_s"])),
        avg_hr=int(round(row["avg_hr"])) if row["avg_hr"] is not None else None,
        start_time=row["session_date"],
        date=row["session_date"][:10] if row["session_date"] else None,
    )
