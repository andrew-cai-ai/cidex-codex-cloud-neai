"""Shared helpers for radar notify scripts."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EMAIL_ENV_PATH = ROOT / "config" / "email.env"


@dataclass
class StepResult:
    name: str
    ok: bool
    output: str


def run_command(name: str, command: list[str], cwd: Path = ROOT, timeout: int = 180) -> StepResult:
    proc = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    return StepResult(name=name, ok=proc.returncode == 0, output=proc.stdout.strip())


def load_env_file(path: Path = EMAIL_ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_latest_json(raw_dir: Path) -> dict | None:
    raw_files = sorted(raw_dir.glob("*.json"))
    if not raw_files:
        return None
    try:
        return json.loads(raw_files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def truncate(value: str, length: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) <= length:
        return value
    return value[: length - 1].rstrip() + "..."
