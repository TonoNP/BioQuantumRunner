from pathlib import Path

import pandas as pd
import pytest

from src.analysis.d2_dataset import (
    COMPATIBILITY_COLUMNS,
    EFFICIENCY_PACE_HR,
    EFFICIENCY_SPEED_HR,
    build_compatibility_view,
    load_analytical_sessions,
    load_historical_validation_sessions,
)


def _write_master(monkeypatch, tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "sessions_master.parquet"
    frame = pd.DataFrame(rows)
    monkeypatch.setattr(pd, "read_parquet", lambda candidate: frame.copy())
    return path


def _row(**overrides):
    row = {
        "source_file": "2025-01-01.json",
        "source_path": "data/raw/polar/2025-01-01.json",
        "sha256": "a" * 64,
        "session_date": "2025-01-01T08:00:00",
        "sport": None,
        "duration_s": 3600.0,
        "distance_km": 12.0,
        "avg_hr": 150.0,
        "ingestion_status": "ingested",
        "modeling_eligible": True,
    }
    row.update(overrides)
    return row


def test_filters_noneligible_and_computes_both_versioned_efficiencies(monkeypatch, tmp_path):
    path = _write_master(
        monkeypatch,
        tmp_path,
        [_row(), _row(source_file="excluded.json", modeling_eligible=False)],
    )

    result = load_analytical_sessions(path)

    assert result["source_file"].tolist() == ["2025-01-01.json"]
    assert result.loc[0, "pace_sec_per_km"] == pytest.approx(300.0)
    assert result.loc[0, EFFICIENCY_PACE_HR] == pytest.approx(2.0)
    assert result.loc[0, EFFICIENCY_SPEED_HR] == pytest.approx(0.08)
    assert "efficiency" not in result.columns


def test_historical_scenario_uses_approved_cutoff(monkeypatch, tmp_path):
    path = _write_master(
        monkeypatch,
        tmp_path,
        [
            _row(),
            _row(source_file="later.json", session_date="2025-10-20T00:00:00"),
        ],
    )

    result = load_analytical_sessions(path, scenario="historical")

    assert result["source_file"].tolist() == ["2025-01-01.json"]


def test_accepts_mixed_legacy_and_modern_iso_dates(monkeypatch, tmp_path):
    path = _write_master(
        monkeypatch,
        tmp_path,
        [
            _row(),
            _row(
                source_file="modern.json",
                session_date="2026-03-06T18:45:00.000Z",
            ),
        ],
    )

    result = load_analytical_sessions(path)

    assert result["session_date"].notna().all()
    assert result["session_date"].max() == pd.Timestamp("2026-03-06T18:45:00")


def test_compatibility_view_preserves_legacy_contract(monkeypatch, tmp_path):
    path = _write_master(monkeypatch, tmp_path, [_row()])
    analytical = load_analytical_sessions(path)

    view = build_compatibility_view(analytical)

    assert list(view.columns) == COMPATIBILITY_COLUMNS
    assert view.loc[0, "name"] == "PolarSession"
    assert view.loc[0, "date"] == pd.Timestamp("2025-01-01")
    assert view.loc[0, "start_time"] == pd.Timestamp("2025-01-01T08:00:00")


def test_rejects_unknown_scenario(monkeypatch, tmp_path):
    path = _write_master(monkeypatch, tmp_path, [_row()])
    with pytest.raises(ValueError, match="scenario"):
        load_analytical_sessions(path, scenario="mixed")


def test_current_corpus_has_separate_approved_baselines():
    master = Path("data/processed/sessions_master.parquet")
    historical = load_analytical_sessions(master, scenario="historical")
    canonical = load_analytical_sessions(master, scenario="canonical")

    assert len(historical) == 2703
    assert historical["session_date"].max() <= pd.Timestamp("2025-10-19 23:59:59.999999")
    assert len(canonical) == 2842
    assert canonical["session_date"].max() == pd.Timestamp("2026-03-06 17:13:37")
    assert canonical["session_date"].notna().all()


def test_historical_validation_precision_is_isolated(monkeypatch, tmp_path):
    path = _write_master(
        monkeypatch,
        tmp_path,
        [_row(distance_km=9.996, duration_s=3000.4)],
    )

    production = load_analytical_sessions(path, scenario="historical")
    validation = load_historical_validation_sessions(path)

    assert production.loc[0, "distance_km"] == pytest.approx(9.996)
    assert production.loc[0, "duration_s"] == pytest.approx(3000.4)
    assert validation.loc[0, "distance_km"] == pytest.approx(10.0)
    assert validation.loc[0, "duration_s"] == pytest.approx(3000.0)
    assert validation.loc[0, "pace_sec_per_km"] == pytest.approx(300.0)


def test_current_historical_validation_reproduces_reference_populations():
    df = load_historical_validation_sessions()
    base = df.dropna(subset=["pace_sec_per_km", "avg_hr", "distance_km"])

    model = base[
        (base["distance_km"] >= 10)
        & (base["avg_hr"] >= 140)
        & (base["pace_sec_per_km"] < 600)
        & (base["distance_km"] < 50)
    ]
    weekly = base[
        (base["distance_km"] >= 8)
        & (base["avg_hr"] > 90)
        & (base["pace_sec_per_km"] < 600)
        & (base["distance_km"] < 50)
    ]
    best = base[
        (base["distance_km"] >= 10)
        & (base["avg_hr"] > 90)
        & (base["pace_sec_per_km"] < 600)
        & (base["distance_km"] < 50)
    ]
    long_runs = base[
        (base["distance_km"] >= 16)
        & (base["avg_hr"] > 90)
        & (base["pace_sec_per_km"] < 600)
        & (base["distance_km"] < 50)
    ]

    assert (len(model), len(weekly), len(best), len(long_runs)) == (550, 1025, 571, 128)
