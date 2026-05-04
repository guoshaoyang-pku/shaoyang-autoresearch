"""
Codex CLI backend for mgr workers (the only worker backend; cursor-agent removed).

Persists session id in ``state/workers/<id>/codex_session.json`` and mirrors
``last_run/`` + ``history.jsonl`` layout (the same layout the audit log
reader expects).

**Stdin trap**: codex must run with stdin from ``/dev/null`` (see
``docs/codex_backend_recipe.md``); the wrapper script appends ``< /dev/null``.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .state import WorkerRunInfo, expand, workers_root


def _default_workers_base() -> Path:
    return workers_root()


def _proc_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def parse_codex_output(raw: str) -> dict[str, Any]:
    """
    Parse codex stdout (see ``docs/codex_backend_recipe.md``).

    Returns keys: session_id, model, provider, user_echo, assistant_message,
    tokens_used (missing → None or "").
    """
    out: dict[str, Any] = {
        "session_id": None,
        "model": None,
        "provider": None,
        "user_echo": "",
        "assistant_message": "",
        "tokens_used": None,
    }
    if not raw:
        return out

    try:
        m_sid = re.search(r"session id:\s*([0-9a-f-]+)", raw, re.IGNORECASE)
        if m_sid:
            out["session_id"] = m_sid.group(1).strip()

        m_model = re.search(r"^model:\s*(.+)$", raw, re.MULTILINE)
        if m_model:
            out["model"] = m_model.group(1).strip()

        m_prov = re.search(r"^provider:\s*(.+)$", raw, re.MULTILINE)
        if m_prov:
            out["provider"] = m_prov.group(1).strip()

        if "\nuser\n" in raw:
            after_user = raw.split("\nuser\n", 1)[1]
            if "\ncodex\n" in after_user:
                out["user_echo"] = after_user.split("\ncodex\n", 1)[0].strip()

        if "\ncodex\n" in raw:
            last_tail = raw.rsplit("\ncodex\n", 1)[-1]
            if "\ntokens used\n" in last_tail:
                body, _, tail = last_tail.partition("\ntokens used\n")
                out["assistant_message"] = body.strip()
                num_line = tail.strip().splitlines()[0] if tail.strip() else ""
                digits = re.sub(r"[,\s]", "", num_line)
                if digits.isdigit():
                    out["tokens_used"] = int(digits)
            else:
                out["assistant_message"] = last_tail.strip()
    except Exception:
        pass

    return out


def _read_codex_session_path(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _write_codex_session(
    path: Path,
    session_id: str,
    *,
    first_run_id: str | None = None,
    captured_at: float | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = _read_codex_session_path(path)
    data = {
        "session_id": session_id,
        "captured_at": captured_at if captured_at is not None else time.time(),
        "first_run_id": (
            first_run_id
            if first_run_id is not None
            else prev.get("first_run_id", "")
        ),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


class CodexWorker:
    """Single-worker local process manager using ``codex exec`` / ``codex exec resume``."""

    def __init__(
        self,
        worker_id: str,
        cli_path: str = "codex",
        profile: str = "high",
        skip_git_repo_check: bool = True,
        color: str = "never",
        sandbox_mode: str = "danger-full-access",
        state_workers_root: Path | None = None,
    ):
        self.worker_id = worker_id
        self.cli_path = cli_path
        self.profile = profile
        self.skip_git_repo_check = skip_git_repo_check
        self.color = color
        self.sandbox_mode = sandbox_mode
        base = state_workers_root if state_workers_root is not None else _default_workers_base()
        self.root = Path(base) / worker_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.last_run_dir = self.root / "last_run"
        self.last_run_dir.mkdir(parents=True, exist_ok=True)
        self.history_path = self.root / "history.jsonl"
        self._codex_session_path = self.root / "codex_session.json"

    @property
    def session_id(self) -> str | None:
        data = _read_codex_session_path(self._codex_session_path)
        sid = data.get("session_id")
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
        return None

    @session_id.setter
    def session_id(self, value: str) -> None:
        sid = (value or "").strip()
        if not sid:
            if self._codex_session_path.exists():
                self._codex_session_path.unlink()
            return
        prev = _read_codex_session_path(self._codex_session_path)
        frid = prev.get("first_run_id", "") if isinstance(prev.get("first_run_id"), str) else ""
        _write_codex_session(
            self._codex_session_path,
            sid,
            first_run_id=frid or "",
            captured_at=time.time(),
        )

    @property
    def worktree_path(self) -> str | None:
        p = self.root / "worktree_path"
        if p.exists():
            return p.read_text().strip()
        return None

    @worktree_path.setter
    def worktree_path(self, value: str) -> None:
        (self.root / "worktree_path").write_text(value)

    @property
    def branch(self) -> str | None:
        p = self.root / "branch"
        if p.exists():
            return p.read_text().strip()
        return None

    @branch.setter
    def branch(self, value: str) -> None:
        (self.root / "branch").write_text(value)

    def get_run(self) -> WorkerRunInfo | None:
        meta_path = self.last_run_dir / "meta.json"
        if not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text())

        pid = meta.get("pid")
        info = WorkerRunInfo(
            id=meta.get("run_id", "unknown"),
            status=meta.get("status", "UNKNOWN"),
            started_at=meta.get("started_at"),
            completed_at=meta.get("completed_at"),
            pid=pid,
            exit_code=meta.get("exit_code"),
            output_path=str(self.last_run_dir / "output.log"),
            prompt_preview=meta.get("prompt_preview", ""),
        )

        if info.status == "RUNNING" and pid:
            if not _proc_alive(pid):
                exit_code = None
                ec_path = self.last_run_dir / "exit_code"
                if ec_path.exists():
                    try:
                        exit_code = int(ec_path.read_text().strip())
                    except Exception:
                        pass
                info.status = "FINISHED" if exit_code == 0 else "ERROR"
                info.exit_code = exit_code
                info.completed_at = time.time()
                meta.update(
                    {
                        "status": info.status,
                        "exit_code": exit_code,
                        "completed_at": info.completed_at,
                    }
                )

                extracted = self.extract_session_id()
                if extracted and not self.session_id:
                    _write_codex_session(
                        self._codex_session_path,
                        extracted,
                        first_run_id=meta.get("run_id", ""),
                        captured_at=time.time(),
                    )
                    meta["captured_session_id"] = extracted
                meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

                with open(self.history_path, "a") as f:
                    f.write(
                        json.dumps(
                            {
                                "event": "finished",
                                "ts": info.completed_at,
                                "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                "run_id": info.id,
                                "exit_code": exit_code,
                                "session_id": extracted or self.session_id,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        return info

    def start(
        self,
        prompt: str,
        timeout_seconds: int = 1800,
        extra_env: dict | None = None,
    ) -> WorkerRunInfo:
        from shutil import which

        if not which(self.cli_path):
            raise RuntimeError(
                "codex CLI not found on PATH; see docs/codex_backend_recipe.md for installation"
            )

        if not self.worktree_path:
            raise RuntimeError(
                f"worker {self.worker_id} 未初始化 worktree_path（先跑 bootstrap）"
            )

        wt = str(expand(self.worktree_path))

        cur = self.get_run()
        if cur and cur.is_active:
            raise RuntimeError(
                f"worker {self.worker_id} 已有 active run (pid={cur.pid})，先 cancel"
            )

        run_id = uuid.uuid4().hex[:12]
        output_log = self.last_run_dir / "output.log"
        prompt_file = self.last_run_dir / "prompt.txt"
        meta_path = self.last_run_dir / "meta.json"
        pid_path = self.last_run_dir / "pid"
        ec_path = self.last_run_dir / "exit_code"

        for p in (output_log, ec_path):
            if p.exists():
                p.unlink()
        prompt_file.write_text(prompt)

        cmd: list[str] = [self.cli_path, "exec"]
        if self.session_id:
            cmd.extend(["resume", self.session_id])
        else:
            if self.skip_git_repo_check:
                cmd.append("--skip-git-repo-check")
        cmd.extend(["--color", self.color])
        if not self.session_id:
            cmd.extend(["--profile", self.profile])
        cmd.extend(["-C", wt, prompt])

        env = {**os.environ, **(extra_env or {})}

        wrapper = self._build_wrapper_script(cmd, ec_path)
        proc = subprocess.Popen(
            ["/bin/bash", "-c", wrapper],
            cwd=wt,
            stdout=open(output_log, "w"),
            stderr=subprocess.STDOUT,
            env=env,
            preexec_fn=os.setsid,
        )

        started = time.time()
        meta = {
            "run_id": run_id,
            "status": "RUNNING",
            "started_at": started,
            "completed_at": None,
            "pid": proc.pid,
            "exit_code": None,
            "prompt_preview": prompt[:300],
            "cli_path": self.cli_path,
            "profile": self.profile,
            "sandbox_mode": self.sandbox_mode,
            "worktree_path": wt,
            "timeout_seconds": timeout_seconds,
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        pid_path.write_text(str(proc.pid))

        with open(self.history_path, "a") as f:
            f.write(
                json.dumps(
                    {
                        "event": "started",
                        "ts": started,
                        "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "run_id": run_id,
                        "pid": proc.pid,
                        "prompt_preview": prompt[:200],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

        return WorkerRunInfo(
            id=run_id,
            status="RUNNING",
            started_at=started,
            pid=proc.pid,
            output_path=str(output_log),
            prompt_preview=prompt[:300],
        )

    def _build_wrapper_script(self, cmd: list[str], ec_path: Path) -> str:
        import shlex

        joined = " ".join(shlex.quote(c) for c in cmd)
        return f"{joined} < /dev/null; echo $? > {shlex.quote(str(ec_path))}"

    def cancel(self) -> bool:
        cur = self.get_run()
        if not cur or not cur.is_active or not cur.pid:
            return False
        try:
            os.killpg(os.getpgid(cur.pid), signal.SIGTERM)
            time.sleep(2)
            if _proc_alive(cur.pid):
                os.killpg(os.getpgid(cur.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass

        meta_path = self.last_run_dir / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            meta.update(
                {
                    "status": "CANCELLED",
                    "completed_at": time.time(),
                }
            )
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

        with open(self.history_path, "a") as f:
            f.write(
                json.dumps(
                    {
                        "event": "cancelled",
                        "ts": time.time(),
                        "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "pid": cur.pid,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        return True

    def read_raw_output(self) -> str:
        p = self.last_run_dir / "output.log"
        if not p.exists():
            return ""
        return p.read_text(errors="replace")

    def read_output(self, max_chars: int = 8000) -> str:
        raw = self.read_raw_output()
        parsed = parse_codex_output(raw)
        if not raw.strip():
            return "(无输出文件)"
        result = parsed.get("assistant_message") or ""
        usage = parsed.get("tokens_used")
        session = parsed.get("session_id") or ""
        model = parsed.get("model") or ""
        provider = parsed.get("provider") or ""
        user_echo = parsed.get("user_echo") or ""
        text = (
            f"=== meta ===\n"
            f"session_id: {session}\n"
            f"model: {model}\n"
            f"provider: {provider}\n"
            f"tokens_used: {usage}\n"
            f"\n=== user echo ===\n{user_echo}\n"
            f"\n=== worker output ===\n{result}\n"
        )
        if len(text) > max_chars:
            return (
                text[-max_chars:]
                + f"\n\n[truncated, total {len(text)} chars; showing last {max_chars}]"
            )
        return text

    def extract_session_id(self) -> str | None:
        p = self.last_run_dir / "output.log"
        if not p.exists():
            return None
        text = p.read_text(errors="replace")
        m = re.search(r"session id:\s*([0-9a-f-]+)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None

    def to_dict(self) -> dict:
        cur = self.get_run()
        return {
            "worker_id": self.worker_id,
            "session_id": self.session_id,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "profile": self.profile,
            "sandbox_mode": self.sandbox_mode,
            "current_run": asdict(cur) if cur else None,
        }


def _self_test() -> int:
    import shutil
    import tempfile

    def fail(msg: str) -> int:
        print(f"FAIL: {msg}")
        return 1

    # Instantiate without requiring codex on PATH
    try:
        CodexWorker("smoke_init", cli_path="/nonexistent/codex_bin_xxx")
    except Exception as e:
        return fail(f"constructor raised: {e}")

    with tempfile.TemporaryDirectory() as td:
        workers_base = Path(td) / "workers"
        cw = CodexWorker("test_worker", state_workers_root=workers_base)
        if cw.session_id is not None:
            return fail("session_id should be None initially")
        cw.session_id = "abc-def"
        if cw.session_id != "abc-def":
            return fail("session_id setter/getter roundtrip")
        if not cw._codex_session_path.exists():
            return fail("codex_session.json not written")

    synthetic = (
        "OpenAI Codex v0.128.0 (research preview)\n"
        "--------\n"
        "workdir: /tmp/test\n"
        "model: gpt-5.5-2026-04-24\n"
        "provider: bytedance\n"
        "approval: never\n"
        "sandbox: danger-full-access\n"
        "reasoning effort: xhigh\n"
        "reasoning summaries: none\n"
        "session id: 019de44d-785e-7a81-8b68-33fc726e824e\n"
        "--------\n"
        "user\n"
        "ping\n"
        "codex\n"
        "pong\n"
        "tokens used\n"
        "8864\n"
    )
    pr = parse_codex_output(synthetic)
    if pr.get("session_id") != "019de44d-785e-7a81-8b68-33fc726e824e":
        return fail(f"parse session_id: {pr.get('session_id')}")
    if pr.get("model") != "gpt-5.5-2026-04-24":
        return fail(f"parse model: {pr.get('model')}")
    if "pong" not in (pr.get("assistant_message") or ""):
        return fail(f"parse assistant_message: {pr.get('assistant_message')!r}")
    if pr.get("tokens_used") != 8864:
        return fail(f"parse tokens_used: {pr.get('tokens_used')}")

    with tempfile.TemporaryDirectory() as td_wrap:
        cw2 = CodexWorker(
            "_wrap", state_workers_root=Path(td_wrap) / "workers"
        )
    ec = Path("/tmp/codex_ec_test_dummy")
    ws = cw2._build_wrapper_script(["codex", "exec", "hi"], ec)
    if "< /dev/null" not in ws:
        return fail(f"wrapper missing stdin redirect: {ws!r}")

    if not shutil.which("codex"):
        with tempfile.TemporaryDirectory() as td2:
            wb = Path(td2) / "workers"
            w = CodexWorker(
                "no_codex",
                cli_path="codex",
                state_workers_root=wb,
            )
            w.worktree_path = str(Path(td2) / "wt")
            (Path(td2) / "wt").mkdir()
            try:
                w.start("ping")
            except RuntimeError as e:
                if "codex CLI not found" not in str(e):
                    return fail(f"wrong RuntimeError: {e}")
            else:
                return fail("start() should raise when codex missing")
    else:
        print("OK: skipping codex-missing RuntimeError (codex on PATH)")

    print("OK: all checks passed")
    return 0


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    print("Usage: python -m lib.codex_worker --self-test", file=sys.stderr)
    sys.exit(2)
