"""Append-only answer audit log (JSON Lines), so every answer can be reviewed later."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import AUDIT_PATH

_lock = threading.Lock()


def append(record: dict[str, Any], path: Path = AUDIT_PATH) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **record}
    line = json.dumps(record, ensure_ascii=False, default=str)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def recent(limit: int = 20, path: Path = AUDIT_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with _lock:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
