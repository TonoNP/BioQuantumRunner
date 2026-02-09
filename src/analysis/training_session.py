# src/analysis/training_session.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def format_pace(seconds_per_km: float) -> str:
    """
    Format pace given in seconds per km as 'M:SS /km'.
    Example: 292 -> '4:52 /km'
    """
    if seconds_per_km <= 0:
        raise ValueError("seconds_per_km must be > 0")

    total_seconds = int(round(seconds_per_km))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d} /km"


@dataclass(frozen=True)
class TrainingSession:
    """
    Immutable representation of a running session.
    - distance_km: total distance in kilometers
    - duration_s: total moving duration in seconds
    - avg_hr: average heart rate (bpm), optional
    - name: label for the session (e.g., '10K tempo')
    """

    distance_km: float
    duration_s: int
    avg_hr: Optional[int] = None
    name: str = "session"

    def __post_init__(self) -> None:
        if self.distance_km <= 0:
            raise ValueError("distance_km must be > 0")
        if self.duration_s <= 0:
            raise ValueError("duration_s must be > 0")
        if self.avg_hr is not None and self.avg_hr <= 0:
            raise ValueError("avg_hr must be > 0 when provided")

    @property
    def pace_s_per_km(self) -> float:
        """Average pace in seconds per km."""
        return self.duration_s / self.distance_km

    @property
    def pace_str(self) -> str:
        """Average pace formatted as 'M:SS /km'."""
        return format_pace(self.pace_s_per_km)

    def summary(self) -> str:
        hr_part = f", avgHR={self.avg_hr} bpm" if self.avg_hr is not None else ""
        return (
            f"TrainingSession(name='{self.name}', "
            f"distance={self.distance_km:.2f} km, "
            f"duration={self.duration_s} s, "
            f"pace={self.pace_str}"
            f"{hr_part})"
        )