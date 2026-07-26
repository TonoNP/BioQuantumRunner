from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_dataset import canonical_manifest_sha256
from src.ingestion.polar_json import (
    PIPELINE_VERSION,
    SESSION_COLUMNS,
    extract_date_from_filename,
    ingest_polar_file,
)


class D1IngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = self.root / "data/raw/polar"
        self.raw.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_json(self, filename: str, payload: dict, bom: bool = False) -> Path:
        path = self.raw / filename
        encoding = "utf-8-sig" if bom else "utf-8"
        path.write_text(json.dumps(payload), encoding=encoding)
        return path

    def test_legacy_schema_is_normalized_without_rounding(self) -> None:
        path = self.write_json(
            "training-session-2024-02-03-1-a.json",
            {
                "startTime": "2024-02-03T10:11:12.345",
                "duration": "PT2356.934S",
                "distance": 8308.400390625,
                "averageHeartRate": 149,
                "maximumHeartRate": 170,
                "kiloCalories": 600,
                "name": "Running",
            },
        )
        row = ingest_polar_file(path, self.root)
        self.assertEqual(row["ingestion_status"], "ingested")
        self.assertEqual(row["schema_version"], "polar_v1_legacy")
        self.assertEqual(row["pipeline_version"], PIPELINE_VERSION)
        self.assertEqual(row["duration_s"], 2356.934)
        self.assertEqual(row["distance_km"], 8.308400390625)
        self.assertEqual(row["quality_status"], "valid")
        self.assertTrue(row["modeling_eligible"])

    def test_modern_schema_and_utf8_bom_are_supported(self) -> None:
        path = self.write_json(
            "training-session-2026-03-06T17_13_37-1-a.json",
            {
                "startTime": "2026-03-06T17:13:37",
                "durationMillis": 3580376,
                "distanceMeters": 10887.7001953125,
                "hrAvg": 165,
                "hrMax": 180,
                "calories": 730,
                "sport": "RUNNING",
            },
            bom=True,
        )
        row = ingest_polar_file(path, self.root)
        self.assertEqual(row["schema_version"], "polar_v2_modern")
        self.assertEqual(row["source_encoding"], "utf-8-sig")
        self.assertEqual(row["duration_s"], 3580.376)
        self.assertEqual(row["distance_km"], 10.8877001953125)
        self.assertEqual(row["quality_flags"], [])

    def test_partial_optional_metrics_remain_in_master(self) -> None:
        path = self.write_json(
            "training-session-2024-02-03-2-a.json",
            {
                "startTime": "2024-02-03T10:11:12",
                "duration": 100,
                "distance": 1000,
                "name": "Running",
            },
        )
        row = ingest_polar_file(path, self.root)
        self.assertEqual(row["ingestion_status"], "ingested")
        self.assertEqual(row["quality_status"], "partial")
        self.assertEqual(
            row["quality_flags"],
            ["missing_avg_hr", "missing_calories", "missing_max_hr"],
        )
        self.assertTrue(row["modeling_eligible"])

    def test_invalid_numeric_metrics_get_objective_flags(self) -> None:
        path = self.write_json(
            "training-session-2024-02-03-3-a.json",
            {
                "startTime": "2024-02-03T10:11:12",
                "duration": "invalid",
                "distance": "invalid",
                "averageHeartRate": "invalid",
                "maximumHeartRate": 0,
                "kiloCalories": -1,
                "name": "Running",
            },
        )
        row = ingest_polar_file(path, self.root)
        self.assertEqual(row["ingestion_status"], "ingested")
        self.assertEqual(row["quality_status"], "warning")
        self.assertEqual(
            row["quality_flags"],
            [
                "invalid_avg_hr",
                "invalid_distance",
                "invalid_duration",
                "negative_calories",
                "non_positive_max_hr",
            ],
        )
        self.assertIsNone(row["duration_s"])
        self.assertIsNone(row["distance_km"])
        self.assertIsNone(row["avg_hr"])
        self.assertEqual(row["max_hr"], 0)
        self.assertEqual(row["calories"], -1)
        self.assertFalse(row["modeling_eligible"])

    def test_invalid_filename_date_is_non_terminal(self) -> None:
        path = self.write_json(
            "training-session-not-a-date.json",
            {
                "startTime": "2024-02-03T10:11:12",
                "duration": 100,
                "distance": 1000,
                "averageHeartRate": 140,
                "maximumHeartRate": 160,
                "kiloCalories": 50,
                "name": "Running",
            },
        )
        row = ingest_polar_file(path, self.root)
        self.assertIsNone(row["date_from_filename"])
        self.assertIn("invalid_filename_date", row["quality_flags"])
        self.assertEqual(row["quality_status"], "warning")
        self.assertTrue(row["modeling_eligible"])

    def test_hybrid_uses_modern_precedence_and_marks_fallback(self) -> None:
        path = self.write_json(
            "training-session-2026-03-06-2-a.json",
            {
                "startTime": "2026-03-06T10:00:00",
                "durationMillis": 100000,
                "duration": "PT999S",
                "distance": 2000,
                "hrAvg": 150,
                "averageHeartRate": 100,
                "hrMax": 170,
                "calories": 100,
                "name": "Running",
            },
        )
        row = ingest_polar_file(path, self.root)
        self.assertEqual(row["schema_version"], "polar_v2_modern")
        self.assertEqual(row["duration_s"], 100)
        self.assertEqual(row["distance_km"], 2)
        self.assertIn("hybrid_schema", row["quality_flags"])
        self.assertIn("schema_fallback_used", row["quality_flags"])

    def test_binary_and_invalid_json_are_distinct(self) -> None:
        binary = self.raw / "training-session-2024-01-09-1-a.json"
        binary.write_bytes(b"\xff\xfe\x00\x81")
        binary_row = ingest_polar_file(binary, self.root)
        self.assertEqual(binary_row["ingestion_status"], "unrecoverable_binary")
        self.assertEqual(binary_row["error_type"], "BinaryContentError")

        invalid = self.raw / "training-session-2024-01-10-1-a.json"
        invalid.write_text("{not json}", encoding="utf-8")
        invalid_row = ingest_polar_file(invalid, self.root)
        self.assertEqual(invalid_row["ingestion_status"], "invalid_json")
        self.assertEqual(invalid_row["error_type"], "JsonDecodeError")

    def test_source_hash_change_is_a_source_read_error(self) -> None:
        path = self.write_json(
            "training-session-2024-02-03-4-a.json",
            {"duration": 1, "distance": 1},
        )
        original_read_bytes = Path.read_bytes
        calls = 0

        def changing_read_bytes(candidate: Path) -> bytes:
            nonlocal calls
            if candidate.resolve() == path.resolve():
                calls += 1
                return b'{"duration":1,"distance":1}' if calls == 1 else b"changed"
            return original_read_bytes(candidate)

        with patch.object(Path, "read_bytes", changing_read_bytes):
            row = ingest_polar_file(path, self.root)
        self.assertEqual(row["ingestion_status"], "source_read_error")
        self.assertEqual(row["error_type"], "SourceChangedDuringIngestionError")

    def test_manifest_is_independent_of_input_order_and_flag_order(self) -> None:
        first = {column: None for column in SESSION_COLUMNS}
        first.update(
            {
                "source_file": "b.json",
                "quality_flags": ["z", "a"],
                "modeling_eligible": False,
            }
        )
        second = {column: None for column in SESSION_COLUMNS}
        second.update(
            {
                "source_file": "a.json",
                "quality_flags": [],
                "modeling_eligible": True,
            }
        )
        hash_one = canonical_manifest_sha256([first, second], SESSION_COLUMNS)
        first["quality_flags"] = ["a", "z"]
        hash_two = canonical_manifest_sha256([second, first], SESSION_COLUMNS)
        self.assertEqual(hash_one, hash_two)

    def test_filename_date_validation(self) -> None:
        self.assertEqual(
            extract_date_from_filename("training-session-2024-02-29-1-a.json"),
            "2024-02-29",
        )
        self.assertIsNone(
            extract_date_from_filename("training-session-2023-02-29-1-a.json")
        )


if __name__ == "__main__":
    unittest.main()
