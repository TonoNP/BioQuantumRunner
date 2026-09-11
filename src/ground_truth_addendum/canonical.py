"""Deterministic logical serialization and hashing.

Physical file hashes and logical hashes are deliberately different concepts.
The functions here hash normalized scientific content, never filesystem layout.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


CANONICALIZATION_VERSION = "bqr-canonical-json-v1"


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal is not canonical")
        normalized = value.normalize()
        return format(normalized, "f") if normalized != 0 else "0"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float is not canonical")
        return 0 if value == 0 else json.loads(json.dumps(value, allow_nan=False))
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime is not canonical")
        utc = value.astimezone(timezone.utc)
        text = utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
        return text
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {unicodedata.normalize("NFC", str(k)): _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    envelope = {"canonicalization_version": CANONICALIZATION_VERSION, "payload": _normalize(value)}
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def logical_hash(value: Any, *, domain: str) -> str:
    material = f"{domain}\n{canonical_json(value)}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def logical_records_hash(
    records: Iterable[Mapping[str, Any]], *, domain: str, order_by: Sequence[str]
) -> str:
    normalized = [_normalize(dict(record)) for record in records]
    normalized.sort(key=lambda row: tuple(canonical_json(row.get(key)) for key in order_by))
    return logical_hash(normalized, domain=domain)


def binary_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

