from __future__ import annotations
from typing import Any, Dict

from src.analysis.training_session import TrainingSession


def session_from_polar_dict(d: Dict[str, Any]) -> TrainingSession:
    distance_km = float(d["distance_km"])
    duration_s = int(d["duration_s"])
    avg_hr = int(d["avg_hr"]) if "avg_hr" in d and d["avg_hr"] is not None else None
    name = str(d.get("name", "polar_session"))

    return TrainingSession(
        distance_km=distance_km,
        duration_s=duration_s,
        avg_hr=avg_hr,
        name=name,
    )