"""
Manager LLM invocation helper for tick.sh / kickoff.sh (codex-only).

cursor-agent is *not* a supported backend. Cursor (the IDE) is for human
operators; the in-loop LLMs (manager, worker, reviewer-sim) all run via the
codex CLI. The codex backend has subtle traps -- stdin must redirect to
``/dev/null``, the session id appears in stdout body not in JSON, etc. --
documented in ``docs/codex_backend_recipe.md``.

Usage:
    # First-turn session creation. Returns the new session-id.
    python scripts/_invoke_manager.py kickoff <worker_id> \\
        --workspace <root> --prompt-file <path> --output-raw <path>

    # Resume an existing session and send one short prompt.
    python scripts/_invoke_manager.py tick <worker_id> \\
        --workspace <root> --resume-id <id> --prompt <text> \\
        --output-raw <path>

Output (always single-line JSON to stdout -- bash callers parse with python):
    {"ok": true,
     "backend": "codex",
     "session_id": "<uuid>" | null,
     "exit_code": 0,
     "raw_path": "<path>",
     "duration_seconds": 12.3}

On failure ``ok`` is ``false``, ``error`` is set, process exit code is
non-zero (mirrors the underlying CLI when possible).

Self-test:
    python scripts/_invoke_manager.py --self-test
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path


# -------------------------------------------------------------------- config


def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise SystemExit(
            f"找不到 {config_path}（先 cp config.example.toml config.toml）"
        )
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def _resolve_reviewer_cfg(cfg: dict) -> dict:
    """Apply defaults / sanity checks to the [reviewer] section.

    codex-only: any other backend value is rejected (including the legacy
    ``cursor-agent`` value -- see commit log for the removal).
    """

    rv = dict(cfg.get("reviewer", {}) or {})
    backend = (rv.get("backend") or "codex").strip().lower()
    if backend != "codex":
        raise SystemExit(
            f"[reviewer].backend 不支持: {backend!r}（仅 codex；cursor-agent 已彻底移除）"
        )
    rv["backend"] = backend
    rv.setdefault("cli_path", "codex")
    rv.setdefault("profile", "high")
    rv.setdefault("timeout_seconds", 300)
    return rv


# ------------------------------------------------------------------ helpers


def _emit(obj: dict, exit_code: int) -> None:
    print(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()
    sys.exit(exit_code)


def _extract_codex_session_id(raw: str) -> str:
    m = re.search(r"session id:\s*([0-9a-f-]+)", raw, re.IGNORECASE)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------- codex invocation


def _run_codex(
    *,
    cli_path: str,
    profile: str,
    workspace: str,
    prompt: str,
    timeout_seconds: int,
    output_raw: Path,
    resume_id: str = "",
    skip_git_repo_check: bool = True,
) -> tuple[int, float]:
    cmd: list[str] = [cli_path, "exec"]
    if resume_id:
        cmd.extend(["resume", resume_id])
    else:
        if skip_git_repo_check:
            cmd.append("--skip-git-repo-check")
    cmd.extend(["--color", "never"])
    if not resume_id:
        cmd.extend(["--profile", profile])
    cmd.extend(["-C", workspace, prompt])

    started = time.time()
    output_raw.parent.mkdir(parents=True, exist_ok=True)
    with open(output_raw, "w", encoding="utf-8") as f:
        try:
            proc = subprocess.run(
                cmd,
                stdout=f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,  # CRITICAL: see codex_backend_recipe.md
                text=True,
                timeout=timeout_seconds,
            )
            return proc.returncode, time.time() - started
        except subprocess.TimeoutExpired:
            f.write(f"\n[_invoke_manager] codex timed out after {timeout_seconds}s\n")
            return 124, time.time() - started
        except FileNotFoundError as e:
            f.write(f"\n[_invoke_manager] codex CLI not found: {e}\n")
            return 127, time.time() - started


# -------------------------------------------------------- subcommand: kickoff


def cmd_kickoff(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    config_path = Path(args.config) if args.config else workspace / "config.toml"
    cfg = _load_config(config_path)
    rv = _resolve_reviewer_cfg(cfg)

    prompt_file = Path(args.prompt_file)
    if not prompt_file.exists():
        _emit(
            {
                "ok": False,
                "backend": "codex",
                "error": f"prompt file 不存在: {prompt_file}",
            },
            exit_code=2,
        )
    prompt = prompt_file.read_text(encoding="utf-8")
    output_raw = Path(args.output_raw)

    rc, dur = _run_codex(
        cli_path=rv["cli_path"],
        profile=rv["profile"],
        workspace=str(workspace),
        prompt=prompt,
        timeout_seconds=int(rv["timeout_seconds"]),
        output_raw=output_raw,
        resume_id="",
    )
    if rc != 0:
        _emit(
            {
                "ok": False,
                "backend": "codex",
                "exit_code": rc,
                "error": f"codex exec exit {rc}",
                "raw_path": str(output_raw),
                "duration_seconds": round(dur, 2),
            },
            exit_code=rc or 1,
        )
    raw = output_raw.read_text(encoding="utf-8", errors="replace")
    sid = _extract_codex_session_id(raw)
    if not sid:
        _emit(
            {
                "ok": False,
                "backend": "codex",
                "exit_code": rc,
                "error": "codex stdout 没找到 'session id: <uuid>' 行（升级 codex CLI?）",
                "raw_path": str(output_raw),
                "duration_seconds": round(dur, 2),
            },
            exit_code=3,
        )
    _emit(
        {
            "ok": True,
            "backend": "codex",
            "session_id": sid,
            "exit_code": rc,
            "raw_path": str(output_raw),
            "duration_seconds": round(dur, 2),
        },
        exit_code=0,
    )


# -------------------------------------------------------- subcommand: tick


def cmd_tick(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    config_path = Path(args.config) if args.config else workspace / "config.toml"
    cfg = _load_config(config_path)
    rv = _resolve_reviewer_cfg(cfg)

    output_raw = Path(args.output_raw)

    rc, dur = _run_codex(
        cli_path=rv["cli_path"],
        profile=rv["profile"],
        workspace=str(workspace),
        prompt=args.prompt,
        timeout_seconds=int(rv["timeout_seconds"]),
        output_raw=output_raw,
        resume_id=args.resume_id,
    )
    ok = rc == 0
    _emit(
        {
            "ok": ok,
            "backend": "codex",
            "session_id": args.resume_id,
            "exit_code": rc,
            "raw_path": str(output_raw),
            "duration_seconds": round(dur, 2),
            **({} if ok else {"error": f"codex tick exit {rc}"}),
        },
        exit_code=0 if ok else (rc or 1),
    )


# ------------------------------------------------------------------- self-test


def _self_test() -> int:
    """Hermetic checks: parsers + config resolution. Does NOT shell out."""
    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            failures.append(msg)

    codex_raw = (
        "OpenAI Codex v0.128.0 (research preview)\n"
        "--------\n"
        "model: gpt-5.5-2026-04-24\n"
        "session id: 019de44d-785e-7a81-8b68-33fc726e824e\n"
        "--------\n"
    )
    check(
        _extract_codex_session_id(codex_raw)
        == "019de44d-785e-7a81-8b68-33fc726e824e",
        "codex session id parse",
    )
    check(
        _extract_codex_session_id("nothing here") == "",
        "codex empty when nothing matches",
    )

    rv_b = _resolve_reviewer_cfg({"reviewer": {"backend": "codex"}})
    check(rv_b["backend"] == "codex", "codex backend resolved")
    check(rv_b["cli_path"] == "codex", "codex default cli_path")
    check(rv_b["profile"] == "high", "codex default profile = high")
    check(rv_b["timeout_seconds"] == 300, "codex default timeout = 300")

    rv_default = _resolve_reviewer_cfg({})
    check(rv_default["backend"] == "codex", "default backend is codex")

    for bad in ("cursor-agent", "ollama-local", "anthropic-api"):
        try:
            _resolve_reviewer_cfg({"reviewer": {"backend": bad}})
        except SystemExit:
            pass
        else:
            failures.append(f"unsupported backend {bad!r} should raise SystemExit")

    if failures:
        for msg in failures:
            print(f"FAIL: {msg}", file=sys.stderr)
        print(f"FAILED: {len(failures)}", file=sys.stderr)
        return 1
    print("OK: all checks passed")
    return 0


# --------------------------------------------------------------------- main


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(_self_test())

    p = argparse.ArgumentParser(prog="_invoke_manager.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    pk = sub.add_parser("kickoff", help="第一次启动 manager（创建 session）")
    pk.add_argument("worker_id")
    pk.add_argument("--workspace", required=True)
    pk.add_argument("--prompt-file", required=True)
    pk.add_argument("--output-raw", required=True)
    pk.add_argument("--config", default="")
    pk.set_defaults(func=cmd_kickoff)

    pt = sub.add_parser("tick", help="resume manager session 跑一次 tick")
    pt.add_argument("worker_id")
    pt.add_argument("--workspace", required=True)
    pt.add_argument("--resume-id", required=True)
    pt.add_argument("--prompt", required=True)
    pt.add_argument("--output-raw", required=True)
    pt.add_argument("--config", default="")
    pt.set_defaults(func=cmd_tick)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
