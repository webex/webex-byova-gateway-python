"""Sanitised local run-artifact generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def redact_destination(destination: str) -> str:
    """Preserve only the final four characters of a call destination."""
    return f"***{destination[-4:]}" if len(destination) > 4 else "***"


def write_artifact(directory: Path, payload: dict[str, Any]) -> Path:
    """Write a readable, token-free result file for a caller run."""
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"byova-e2e-{timestamp}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path
