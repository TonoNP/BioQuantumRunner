"""Canonical analytical input and legacy compatibility view for D2."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd


DEFAULT_MASTER = Path("data/processed/sessions_master.parquet")
HISTORICAL_CUTOFF = pd.Timestamp("2025-10-19 23:59:59.999999")

EFFICIENCY_PACE_HR = "efficiency_pace_hr_v1"
EFFICIENCY_SPEED_HR = "efficiency_speed_hr_v2"

Scenario = Literal["canonical", "historical"]

REQUIRED_MASTER_COLUMNS = {
    "source_file",
    "source_path",
    "sha256",
    "session_date",
    "sport",
    "duration_s",
    "distance_km",
    "avg_hr",
    "ingestion_status",
    "modeling_eligible",
}

COMPATIBILITY_COLUMNS = [
    "date",
    "start_time",
    "name",
    "distance_km",
    "duration_s",
    "pace_sec_per_km",
    "avg_hr",
]


def _validate_master_columns(df: pd.DataFrame) -> None:
    missing = REQUIRED_MASTER_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"sessions_master is missing required columns: {sorted(missing)}")


def load_analytical_sessions(
    master_path: Path | str = DEFAULT_MASTER,
    *,
    scenario: Scenario = "canonical",
) -> pd.DataFrame:
    """Load eligible sessions and derive the versioned D2 analytical metrics."""
    if scenario not in {"canonical", "historical"}:
        raise ValueError("scenario must be 'canonical' or 'historical'")

    path = Path(master_path)
    df = pd.read_parquet(path)
    _validate_master_columns(df)

    eligible = df["modeling_eligible"].fillna(False).astype(bool)
    ingested = df["ingestion_status"].eq("ingested")
    df = df.loc[eligible & ingested].copy()

    df["session_date"] = pd.to_datetime(
        df["session_date"], format="mixed", errors="coerce", utc=True
    ).dt.tz_localize(None)
    for column in ("duration_s", "distance_km", "avg_hr"):
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if scenario == "historical":
        df = df[df["session_date"] <= HISTORICAL_CUTOFF].copy()

    valid_pace = df["duration_s"].gt(0) & df["distance_km"].gt(0)
    df["pace_sec_per_km"] = np.where(
        valid_pace,
        df["duration_s"] / df["distance_km"],
        np.nan,
    )

    valid_efficiency = valid_pace & df["avg_hr"].gt(0)
    df[EFFICIENCY_PACE_HR] = np.where(
        valid_efficiency,
        df["pace_sec_per_km"] / df["avg_hr"],
        np.nan,
    )
    speed_kmh = np.where(valid_pace, 3600.0 / df["pace_sec_per_km"], np.nan)
    df[EFFICIENCY_SPEED_HR] = np.where(
        valid_efficiency,
        speed_kmh / df["avg_hr"],
        np.nan,
    )

    return df.sort_values("source_file", kind="stable").reset_index(drop=True)


def build_compatibility_view(df: pd.DataFrame) -> pd.DataFrame:
    """Expose the historical sessions.csv contract from canonical D2 rows."""
    required = {
        "session_date",
        "sport",
        "distance_km",
        "duration_s",
        "pace_sec_per_km",
        "avg_hr",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"analytical sessions are missing columns: {sorted(missing)}")

    start_time = pd.to_datetime(df["session_date"], errors="coerce")
    name = df["sport"].where(df["sport"].notna(), "PolarSession")
    view = pd.DataFrame(
        {
            "date": start_time.dt.normalize(),
            "start_time": start_time,
            "name": name,
            "distance_km": df["distance_km"],
            "duration_s": df["duration_s"],
            "pace_sec_per_km": df["pace_sec_per_km"],
            "avg_hr": df["avg_hr"],
        }
    )
    return view[COMPATIBILITY_COLUMNS].reset_index(drop=True)


def load_compatibility_sessions(
    master_path: Path | str = DEFAULT_MASTER,
    *,
    scenario: Scenario = "canonical",
) -> pd.DataFrame:
    return build_compatibility_view(
        load_analytical_sessions(master_path, scenario=scenario)
    )


def load_historical_validation_sessions(
    master_path: Path | str = DEFAULT_MASTER,
) -> pd.DataFrame:
    """Build the D2-IMP-001 validation-only view with legacy precision."""
    df = load_analytical_sessions(master_path, scenario="historical")
    df["distance_km"] = df["distance_km"].round(2)
    df["duration_s"] = df["duration_s"].round(0)

    valid_pace = df["duration_s"].gt(0) & df["distance_km"].gt(0)
    df["pace_sec_per_km"] = np.where(
        valid_pace,
        df["duration_s"] / df["distance_km"],
        np.nan,
    )
    valid_efficiency = valid_pace & df["avg_hr"].gt(0)
    df[EFFICIENCY_PACE_HR] = np.where(
        valid_efficiency,
        df["pace_sec_per_km"] / df["avg_hr"],
        np.nan,
    )
    speed_kmh = np.where(valid_pace, 3600.0 / df["pace_sec_per_km"], np.nan)
    df[EFFICIENCY_SPEED_HR] = np.where(
        valid_efficiency,
        speed_kmh / df["avg_hr"],
        np.nan,
    )
    return df
