"""Shared D2 input adapter for historical analytical scripts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analysis.d2_dataset import (  # noqa: E402
    DEFAULT_MASTER,
    EFFICIENCY_PACE_HR,
    EFFICIENCY_SPEED_HR,
    Scenario,
    build_compatibility_view,
    load_analytical_sessions,
)


def load_sessions(
    *,
    scenario: Scenario = "canonical",
    master_path: Path | str = DEFAULT_MASTER,
):
    analytical = load_analytical_sessions(master_path, scenario=scenario)
    compatibility = build_compatibility_view(analytical)
    compatibility[EFFICIENCY_PACE_HR] = analytical[EFFICIENCY_PACE_HR].to_numpy()
    compatibility[EFFICIENCY_SPEED_HR] = analytical[EFFICIENCY_SPEED_HR].to_numpy()
    return compatibility


__all__ = [
    "EFFICIENCY_PACE_HR",
    "EFFICIENCY_SPEED_HR",
    "load_sessions",
]
