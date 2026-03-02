# src/ingestion/polar_json.py
from __future__ import annotations

import json
from pathlib import Path

from src.analysis.training_session import TrainingSession


def _parse_duration_seconds(duration_value) -> int:
    """
    Polar export suele traer:
      - "duration": "PT4194.878S" (ISO-8601 simplificado)
      - a veces puede venir como número (segundos) en otros exports
    """
    if duration_value is None:
        raise ValueError("Missing 'duration' in Polar JSON")

    # Caso numérico
    if isinstance(duration_value, (int, float)):
        return int(round(duration_value))

    if not isinstance(duration_value, str):
        raise ValueError(f"Unsupported duration type: {type(duration_value)}")

    s = duration_value.strip()

    # Esperamos algo como PT4194.878S
    if s.startswith("PT") and s.endswith("S"):
        num = s[2:-1]  # "4194.878"
        try:
            return int(round(float(num)))
        except ValueError as e:
            raise ValueError(f"Cannot parse duration: {duration_value}") from e

    # Si llega en formato raro, intenta float directo
    try:
        return int(round(float(s)))
    except ValueError as e:
        raise ValueError(f"Cannot parse duration: {duration_value}") from e


def session_from_polar_json(path: str | Path) -> TrainingSession:
    """
    Lee un JSON exportado por Polar (training-session-*.json)
    y lo convierte a TrainingSession.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    # Distancia viene en metros en tu ejemplo: "distance": 14280.2998...
    distance_m = data.get("distance")
    if distance_m is None:
        raise ValueError("Missing 'distance' in Polar JSON")
    distance_km = float(distance_m) / 1000.0

    duration_s = _parse_duration_seconds(data.get("duration"))

    avg_hr = data.get("averageHeartRate")
    # algunos exports pueden no traer HR
    avg_hr = int(avg_hr) if avg_hr is not None else None

    name = data.get("name") or "PolarSession"

    start_time = data.get("startTime")

    if not start_time:
        exercises = data.get("exercises") or []
        if exercises and isinstance(exercises[0], dict):
            start_time = exercises[0].get("startTime")

    date = start_time[:10] if start_time else None
    # ----------------------------

    return TrainingSession(
        name=name,
        distance_km=round(distance_km, 2),
        duration_s=duration_s,
        avg_hr=avg_hr,
        start_time=start_time,   # ← agrega esto
        date=date                # ← agrega esto
    )
  

    