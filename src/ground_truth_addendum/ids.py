"""Versioned identifier strategy for the Ground Truth Addendum."""

from __future__ import annotations

import uuid
from typing import Iterable


ID_STRATEGY_VERSION = "d4-gt-id-v1"
PROJECT_NAMESPACE = uuid.UUID("6be1118a-bf63-5caa-93d9-e33ffb83be42")


def _part(value: object) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("deterministic ID parts cannot be empty")
    return text


def deterministic_id(entity: str, parts: Iterable[object]) -> str:
    """UUIDv5 for reproducible objects; inputs must already be semantic and canonical."""
    name = ":".join(["bqr", "d4-gt", ID_STRATEGY_VERSION, _part(entity), *(_part(v) for v in parts)])
    return str(uuid.uuid5(PROJECT_NAMESPACE, name))


def new_event_id() -> str:
    """UUIDv4 for a human decision or event with identity independent of content."""
    return str(uuid.uuid4())


def validate_uuid(value: str, *, version: int) -> None:
    parsed = uuid.UUID(value)
    if parsed.version != version:
        raise ValueError(f"expected UUIDv{version}: {value}")

