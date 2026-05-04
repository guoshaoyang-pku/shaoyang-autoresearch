"""Git 探针：从本地 worktree fetch remote，收集 worker push 的新 commits + diff。"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .state import expand


@dataclass
class GitProbe:
    repo_path: Path  # 本地用户 repo（用作 fetch 入口）
    branch: str
    subdir: str | None = None  # 限定 diff 范围

    @classmethod
    def from_config(cls, repo_path: str, branch: str, subdir: str | None = None) -> "GitProbe":
        return cls(repo_path=expand(repo_path), branch=branch, subdir=subdir)

    def _git(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout

    def fetch(self) -> None:
        self._git("fetch", "origin", self.branch, check=False)

    def remote_head(self) -> str:
        out = self._git("rev-parse", f"origin/{self.branch}")
        return out.strip()

    def commits_since(self, last_hash: str | None) -> list[dict]:
        """返回 [{hash, author, subject, body}], 按时间正序。"""
        if not last_hash:
            range_spec = f"origin/{self.branch}~5..origin/{self.branch}"  # 最多看 5 个
        else:
            range_spec = f"{last_hash}..origin/{self.branch}"
        try:
            raw = self._git("log", "--reverse", "--pretty=format:%H%x1f%an%x1f%s%x1f%b%x1e", range_spec)
        except RuntimeError:
            return []
        items = []
        for chunk in raw.split("\x1e"):
            chunk = chunk.strip()
            if not chunk:
                continue
            parts = chunk.split("\x1f")
            if len(parts) < 4:
                parts += [""] * (4 - len(parts))
            items.append({
                "hash": parts[0],
                "author": parts[1],
                "subject": parts[2],
                "body": parts[3].strip(),
            })
        return items

    def diff_since(self, last_hash: str | None, max_chars: int = 6000) -> str:
        if not last_hash:
            base = f"origin/{self.branch}~5"
        else:
            base = last_hash
        args = ["diff", "--stat", base, f"origin/{self.branch}"]
        if self.subdir:
            args += ["--", self.subdir]
        stat = self._git(*args, check=False)
        args = ["diff", base, f"origin/{self.branch}"]
        if self.subdir:
            args += ["--", self.subdir]
        full = self._git(*args, check=False)
        if len(full) > max_chars:
            full = full[:max_chars] + f"\n\n... [truncated {len(full) - max_chars} chars]"
        return f"=== diff stat ===\n{stat}\n=== diff (truncated) ===\n{full}"

    def is_blocked_decision_commit(self, commits: list[dict]) -> list[dict]:
        return [c for c in commits if c["subject"].startswith("[BLOCKED-DECISION]")]
