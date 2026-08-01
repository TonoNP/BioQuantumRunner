"""Generate the deterministic D2 baseline validation summary."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analysis.d2_dataset import (  # noqa: E402
    DEFAULT_MASTER,
    HISTORICAL_CUTOFF,
    load_analytical_sessions,
    load_historical_validation_sessions,
)

OUTPUT = Path("reports/d2_validation_summary.json")
HISTORICAL_REFERENCES = {
    "hr_pace_model": 550,
    "weekly_analysis": 1025,
    "best_form_10km": 571,
    "long_runs_16km": 128,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _populations(df):
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
    slope, intercept = np.polyfit(model["pace_sec_per_km"], model["avg_hr"], 1)
    return {
        "hr_pace_model": len(model),
        "weekly_analysis": len(weekly),
        "best_form_10km": len(best),
        "long_runs_16km": len(long_runs),
        "hr_pace_slope": float(slope),
        "hr_pace_intercept": float(intercept),
    }


def main() -> None:
    historical_legacy = load_historical_validation_sessions()
    historical_full_precision = load_analytical_sessions(scenario="historical")
    canonical = load_analytical_sessions(scenario="canonical")

    migration = _populations(historical_legacy)
    precision = _populations(historical_full_precision)
    temporal = _populations(canonical)
    actual_references = {key: migration[key] for key in HISTORICAL_REFERENCES}

    summary = {
        "validation_contract": "D2-IMP-001",
        "source": {
            "path": DEFAULT_MASTER.as_posix(),
            "sha256": _sha256(DEFAULT_MASTER),
        },
        "historical_cutoff": HISTORICAL_CUTOFF.isoformat(),
        "session_counts": {
            "historical_validation": len(historical_legacy),
            "historical_full_precision": len(historical_full_precision),
            "canonical_full_period": len(canonical),
        },
        "migration_compatibility": {
            "expected": HISTORICAL_REFERENCES,
            "actual": actual_references,
            "passed": actual_references == HISTORICAL_REFERENCES,
        },
        "effects": {
            "historical_legacy_precision": migration,
            "historical_canonical_precision": precision,
            "canonical_precision_full_period": temporal,
        },
    }
    if not summary["migration_compatibility"]["passed"]:
        raise ValueError("historical migration baseline does not match references")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(OUTPUT)
    print(f"Saved: {OUTPUT}")


if __name__ == "__main__":
    main()
