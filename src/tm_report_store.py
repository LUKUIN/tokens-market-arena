"""Persistent settlement snapshots and independent report exports."""

import json
from pathlib import Path
import re

from tm_storage import atomic_write, json_bytes


def settlement_path(home, session_id):
    if not isinstance(session_id, str) or not re.fullmatch(r"[0-9a-f]{16}", session_id):
        raise ValueError("Invalid session ID")
    return Path(home) / "reports" / "Settlement Snapshots" / (session_id + ".json")


def export_report(home, name, html, summary):
    root = Path(home) / "reports"
    status = {}
    for key, folder, extension, content in (
        ("html", "HTML Reports", ".html", html.encode("utf-8")),
        ("json", "JSON Reports", ".json", json_bytes(summary)),
    ):
        path = root / folder / (name + extension)
        try:
            atomic_write(path, content)
        except OSError as exc:
            status[key] = {"ok": False, "error": str(exc)}
        else:
            status[key] = {"ok": True, "path": str(path)}
    return status


def read_settlement(path):
    return json.loads(Path(path).read_bytes())
