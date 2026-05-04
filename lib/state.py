"""状态持久化：agent IDs / 监督日志 / 升级 escalation / worker run dataclasses。"""

from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def expand(p: str | Path) -> Path:
    return Path(os.path.expanduser(str(p)))


def workers_root() -> Path:
    """Where each worker's state directory lives (state/workers/<id>/)."""
    return Path(__file__).resolve().parents[1] / "state" / "workers"


@dataclass
class WorkerRunInfo:
    """Normalized worker-run state, used by every worker backend."""

    id: str
    status: str  # CREATING | RUNNING | FINISHED | ERROR | CANCELLED
    started_at: float | None = None
    completed_at: float | None = None
    pid: int | None = None
    exit_code: int | None = None
    output_path: str | None = None
    prompt_preview: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in {"FINISHED", "ERROR", "CANCELLED"}

    @property
    def is_active(self) -> bool:
        return self.status in {"CREATING", "RUNNING"}

    def elapsed_seconds(self, now: float | None = None) -> float | None:
        if self.started_at is None:
            return None
        if self.completed_at is not None:
            return self.completed_at - self.started_at
        return (now or time.time()) - self.started_at


@contextmanager
def file_lock(path: Path):
    """跨进程文件锁，避免 cron + 手动同时跑撞车。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    f = open(lock_path, "w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        f.close()


class AgentRegistry:
    """记录 worker_id → cloud agent_id 的映射。"""

    def __init__(self, path: str | Path):
        self.path = expand(path)

    def load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        with open(self.path) as f:
            return json.load(f)

    def save(self, data: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp.replace(self.path)

    def get(self, worker_id: str) -> dict | None:
        return self.load().get(worker_id)

    def set(self, worker_id: str, info: dict) -> None:
        with file_lock(self.path):
            data = self.load()
            data[worker_id] = info
            self.save(data)

    def update(self, worker_id: str, **fields: Any) -> None:
        with file_lock(self.path):
            data = self.load()
            entry = data.get(worker_id, {})
            entry.update(fields)
            data[worker_id] = entry
            self.save(data)


class JsonlLog:
    """append-only JSONL，监督事件 + escalation 用。"""

    def __init__(self, path: str | Path):
        self.path = expand(path)

    def append(self, entry: dict) -> None:
        entry = {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **entry}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self.path):
            with open(self.path, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def tail(self, n: int = 20) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path) as f:
            lines = f.readlines()[-n:]
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return out
