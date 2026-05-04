#!/usr/bin/env python3
"""
Sentinel watchdog: runs as a cron tick, scans manager audit logs + escalations,
detects patterns of stuck/looping/silent failures, sends Lark notification.

Usage:
    python sentinel.py                   # one tick, real run
    python sentinel.py --dry-run         # don't send Lark, just print what would
    python sentinel.py --self-test       # offline test (hermetic temp dir)

See docs/sub_agents_contract.md MODULE C.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest.mock
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from lib.lark_notify import LarkNotifier, LarkRecipient  # noqa: E402
from lib.state import JsonlLog, file_lock  # noqa: E402

# --- Thresholds (defaults; integration line will move to config) ---
SAME_CAUSE_WINDOW_SEC = 60 * 60
SAME_CAUSE_MIN_COUNT = 3
EXIT_CODE_STREAK_RUNS = 5
SILENCE_HOURS_THRESHOLD = 12
TICK_ESCALATE_WINDOW_SEC = 30 * 60
TICK_ESCALATE_MIN_COUNT = 5
MANAGER_FAIL_STREAK = 3
DEDUPE_HOURS = 4

LOG_TAIL_N = 200
ESCALATIONS_TAIL_N = 50
AUDIT_TAIL_N = 80
HISTORY_TAIL_N = 32


@dataclass
class SentinelAlert:
    """One fired heuristic."""

    heuristic: str
    worker_id: str
    severity: str
    trigger_summary: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def alert_key(self) -> str:
        return f"{self.heuristic}:{self.worker_id}"


def _fmt_hhmm(iso: str, ts: float | None) -> str:
    if iso and len(iso) >= 16:
        try:
            # "2026-05-03T19:45:12+0800" -> take T..T+5
            m = re.search(r"T(\d{2}:\d{2})", iso)
            if m:
                return m.group(1)
        except Exception:
            pass
    if ts is not None:
        return time.strftime("%H:%M", time.localtime(ts))
    return "??:??"


def format_lark_message(alert: SentinelAlert) -> str:
    """Markdown body per sub_agents_contract.md §3.5."""
    worker = alert.worker_id
    sev = alert.severity
    lines = [
        f"🚨 **cursor_manager sentinel alert** [{sev}]",
        "",
        f"- **worker**: {worker}",
        f"- **trigger**: {alert.trigger_summary}",
    ]
    reasons = alert.extra.get("reason_lines")
    if reasons:
        lines.append("- **last reasons**:")
        for i, r in enumerate(reasons, 1):
            lines.append(f"    {i}. {r}")
    detail = alert.extra.get("detail_lines")
    if detail:
        lines.append("- **detail**:")
        for d in detail:
            lines.append(f"    - {d}")
    action = alert.extra.get(
        "suggested_action",
        f"ssh into <your-gpu-host> and check `mgr audit {worker} -n 20`",
    )
    lines.extend(["", f"- **suggested action**: {action}", ""])
    footer_ts = time.strftime("%Y-%m-%dT%H:%M%z")
    lines.append(f"(Sent by cursor_manager/sentinel.py @ {footer_ts})")
    return "\n".join(lines)


def _parse_iso_to_ts(iso: str) -> float | None:
    if not iso:
        return None
    try:
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        return datetime.fromisoformat(iso).timestamp()
    except Exception:
        return None


def _manager_event_failure(ev: dict) -> bool:
    e = str(ev.get("event") or "")
    if not e.startswith("manager_"):
        return False
    if ev.get("exit_code") is not None and ev.get("exit_code") != 0:
        return True
    if ev.get("returncode") is not None and ev.get("returncode") != 0:
        return True
    if ev.get("ok") is False:
        return True
    if ev.get("failed") is True:
        return True
    if ev.get("error"):
        return True
    return False


def heuristic_same_cause_streak(escalations: list[dict], now: float) -> list[SentinelAlert]:
    out: list[SentinelAlert] = []
    window_start = now - SAME_CAUSE_WINDOW_SEC
    recent = [e for e in escalations if float(e.get("ts", 0)) >= window_start]
    by_worker_reason: dict[tuple[str, str], list[dict]] = {}
    for e in recent:
        wid = str(e.get("worker_id") or "")
        reason = str(e.get("reason") or e.get("event") or e.get("summary") or "").strip()
        if not wid or not reason:
            continue
        by_worker_reason.setdefault((wid, reason), []).append(e)
    for (wid, reason), items in by_worker_reason.items():
        if len(items) < SAME_CAUSE_MIN_COUNT:
            continue
        items.sort(key=lambda x: float(x.get("ts", 0)))
        tail = items[-SAME_CAUSE_MIN_COUNT :]
        reason_lines = []
        for e in tail:
            iso = str(e.get("iso") or "")
            ts = float(e.get("ts") or 0)
            hm = _fmt_hhmm(iso, ts)
            reason_lines.append(f"[{hm}] {reason}")
        out.append(
            SentinelAlert(
                heuristic="same_cause_streak",
                worker_id=wid,
                severity="high",
                trigger_summary="same escalation reason >= 3 in 60 min",
                extra={"reason_lines": reason_lines},
            )
        )
    return out


def heuristic_exit_code_streak(state_root: Path, now: float) -> list[SentinelAlert]:
    out: list[SentinelAlert] = []
    workers_dir = state_root / "workers"
    if not workers_dir.is_dir():
        return out
    for hist in workers_dir.glob("*/history.jsonl"):
        worker_id = hist.parent.name
        rows = JsonlLog(hist).tail(HISTORY_TAIL_N)
        finished = [r for r in rows if r.get("exit_code") is not None]
        if len(finished) < EXIT_CODE_STREAK_RUNS:
            continue
        last = finished[-EXIT_CODE_STREAK_RUNS :]
        if all(int(r.get("exit_code") or 1) != 0 for r in last):
            codes = [str(r.get("exit_code")) for r in last]
            out.append(
                SentinelAlert(
                    heuristic="exit_code_streak",
                    worker_id=worker_id,
                    severity="high",
                    trigger_summary=f"last {EXIT_CODE_STREAK_RUNS} runs all non-zero exit",
                    extra={
                        "detail_lines": [f"exit_codes (oldest→newest of last {EXIT_CODE_STREAK_RUNS}): {', '.join(codes)}"],
                    },
                )
            )
    return out


def _load_enabled_workers(config_path: Path) -> set[str] | None:
    if not config_path.exists():
        return None
    try:
        with open(config_path, "rb") as f:
            cfg = tomllib.load(f)
    except Exception:
        return None
    enabled: set[str] = set()
    for w in cfg.get("workers") or []:
        if w.get("enabled") is True:
            enabled.add(str(w["id"]))
    return enabled


def heuristic_silence_hours(state_root: Path, enabled_workers: set[str] | None) -> list[SentinelAlert]:
    if not enabled_workers:
        return []
    out: list[SentinelAlert] = []
    workers_dir = state_root / "workers"
    deadline = time.time() - SILENCE_HOURS_THRESHOLD * 3600
    for wid in enabled_workers:
        wt_file = workers_dir / wid / "worktree_path"
        if not wt_file.exists():
            continue
        wt = wt_file.read_text().strip()
        p = Path(wt)
        if not p.is_dir():
            continue
        try:
            proc = subprocess.run(
                ["git", "log", "-1", "--format=%cI", "HEAD"],
                cwd=str(p),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                continue
            iso = proc.stdout.strip()
            if not iso:
                continue
            ts = _parse_iso_to_ts(iso)
            if ts is None:
                continue
            if ts <= deadline:
                hours = round((time.time() - ts) / 3600, 1)
                out.append(
                    SentinelAlert(
                        heuristic="silence_hours",
                        worker_id=wid,
                        severity="medium",
                        trigger_summary=f"no commit on worker branch for >= {SILENCE_HOURS_THRESHOLD}h",
                        extra={
                            "detail_lines": [
                                f"last commit: {iso} (~{hours}h ago)",
                            ],
                            "suggested_action": f"check worker branch activity: `mgr commits {wid} -n 5`",
                        },
                    )
                )
        except (OSError, subprocess.TimeoutExpired):
            continue
    return out


def _audit_entry_ts(entry: dict, fallback: float | None = None) -> float:
    if "ts" in entry and entry["ts"] is not None:
        try:
            return float(entry["ts"])
        except (TypeError, ValueError):
            pass
    iso = entry.get("tick_at") or entry.get("iso") or ""
    ts = _parse_iso_to_ts(str(iso))
    if ts is not None:
        return ts
    return float(fallback or time.time())


def heuristic_tick_failure_streak(state_root: Path, now: float) -> list[SentinelAlert]:
    out: list[SentinelAlert] = []
    audits_dir = state_root / "manager_audits"
    if not audits_dir.is_dir():
        return out
    window = now - TICK_ESCALATE_WINDOW_SEC
    for path in audits_dir.glob("*.jsonl"):
        worker_id = path.stem
        lines = JsonlLog(path).tail(AUDIT_TAIL_N)
        esc = [
            e
            for e in lines
            if str(e.get("action") or "").lower() == "escalate" and _audit_entry_ts(e, now) >= window
        ]
        if len(esc) >= TICK_ESCALATE_MIN_COUNT:
            out.append(
                SentinelAlert(
                    heuristic="tick_failure_streak",
                    worker_id=worker_id,
                    severity="high",
                    trigger_summary=f'>= {TICK_ESCALATE_MIN_COUNT} manager ticks with action="escalate" in 30 min',
                    extra={
                        "detail_lines": [
                            f"escalate audits in window: {len(esc)}",
                        ],
                    },
                )
            )
    return out


def heuristic_manager_failure_streak(log_events: list[dict]) -> list[SentinelAlert]:
    mgr = [e for e in log_events if str(e.get("event") or "").startswith("manager_")]
    if not mgr:
        return []
    consecutive = 0
    worker_from_last: str = "global"
    for e in reversed(mgr):
        if _manager_event_failure(e):
            consecutive += 1
            if e.get("worker_id"):
                worker_from_last = str(e["worker_id"])
        else:
            break
    if consecutive < MANAGER_FAIL_STREAK:
        return []
    return [
        SentinelAlert(
            heuristic="manager_failure_streak",
            worker_id=worker_from_last,
            severity="critical",
            trigger_summary=f">= {MANAGER_FAIL_STREAK} consecutive manager log events indicating failure",
            extra={
                "detail_lines": [
                    f"consecutive failing manager_* events (newest-first): {consecutive}",
                ],
                "suggested_action": "check `mgr log -n 50` and tick.sh / manager chat health",
            },
        )
    ]


def load_dedupe(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        raw = data.get("alerts") or data.get("sent_at") or {}
        return {str(k): float(v) for k, v in raw.items()}
    except Exception:
        return {}


def save_dedupe(path: Path, alerts_ts: dict[str, float], updated_at: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"alerts": alerts_ts, "updated_at": updated_at}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(path)


def save_dedupe_locked(path: Path, alerts_ts: dict[str, float], updated_at: float) -> None:
    with file_lock(path):
        save_dedupe(path, alerts_ts, updated_at)


def filter_deduped(
    alerts: list[SentinelAlert],
    dedupe: dict[str, float],
    now: float,
) -> tuple[list[SentinelAlert], dict[str, float]]:
    dedupe_hours_sec = DEDUPE_HOURS * 3600
    fresh: list[SentinelAlert] = []
    new_map = dict(dedupe)
    for a in alerts:
        key = a.alert_key
        last = new_map.get(key)
        if last is not None and (now - last) < dedupe_hours_sec:
            continue
        fresh.append(a)
        new_map[key] = now
    return fresh, new_map


def load_recipient(path: Path) -> LarkRecipient | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return LarkRecipient(str(data["kind"]), str(data["value"]))
    except Exception:
        print(f"sentinel: invalid recipient file {path}", file=sys.stderr)
        return None


def collect_alerts(
    state_root: Path,
    config_path: Path,
    now: float | None = None,
) -> list[SentinelAlert]:
    now = now or time.time()
    esc_log = JsonlLog(state_root / "escalations.jsonl")
    main_log = JsonlLog(state_root / "log.jsonl")
    escalations = esc_log.tail(ESCALATIONS_TAIL_N)
    log_events = main_log.tail(LOG_TAIL_N)
    enabled = _load_enabled_workers(config_path)

    alerts: list[SentinelAlert] = []
    alerts.extend(heuristic_same_cause_streak(escalations, now))
    alerts.extend(heuristic_exit_code_streak(state_root, now))
    alerts.extend(heuristic_silence_hours(state_root, enabled))
    alerts.extend(heuristic_tick_failure_streak(state_root, now))
    alerts.extend(heuristic_manager_failure_streak(log_events))
    return alerts


def tick(
    *,
    state_root: Path,
    recipient_path: Path,
    dedupe_path: Path,
    notifier: LarkNotifier,
    dry_run: bool = False,
    now: float | None = None,
) -> int:
    now = now or time.time()
    recipient = load_recipient(recipient_path)
    if recipient is None:
        print(
            "no recipient configured; create state/sentinel/recipient.json",
            file=sys.stderr,
        )
        return 0

    dedupe = load_dedupe(dedupe_path)
    alerts = collect_alerts(state_root, state_root.parent / "config.toml", now=now)
    to_send, new_dedupe = filter_deduped(alerts, dedupe, now)

    for a in to_send:
        msg = format_lark_message(a)
        notifier.send_markdown(recipient, msg)

    if not dry_run:
        save_dedupe_locked(dedupe_path, new_dedupe, now)
    return 0


def run_self_test() -> int:
    failures: list[str] = []

    def fail(msg: str) -> None:
        failures.append(msg)
        print(f"FAIL: {msg}", file=sys.stderr)

    # 1) Empty state → no alerts
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "state").mkdir(parents=True)
        sr = root / "state"
        cfg = root / "config.toml"
        cfg.write_text(
            "[manager]\nlog_path = \"state/log.jsonl\"\nescalations_path = \"state/escalations.jsonl\"\n\n"
            "[[workers]]\nid = \"paper_a\"\nenabled = false\n"
        )
        alerts = collect_alerts(sr, cfg, now=1000000.0)
        if alerts:
            fail(f"empty state raised {alerts!r}")
        else:
            print("OK: parsed empty audit/log/escalations (no false positives)")

    # 2) same_cause_streak + alert_key
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sr = root / "state"
        sr.mkdir(parents=True)
        esc = sr / "escalations.jsonl"
        base_ts = 2000000.0
        with esc.open("w", encoding="utf-8") as f:
            for i in range(3):
                line = json.dumps(
                    {
                        "ts": base_ts + i * 60,
                        "iso": f"2026-05-03T12:{i:02d}:00+0800",
                        "worker_id": "paper_a",
                        "reason": "stuck on proof",
                    },
                    ensure_ascii=False,
                )
                f.write(line + "\n")
        cfg = root / "config.toml"
        cfg.write_text("[[workers]]\nid = \"paper_a\"\nenabled = false\n")
        alerts = collect_alerts(sr, cfg, now=base_ts + 120)
        sc = [a for a in alerts if a.heuristic == "same_cause_streak"]
        if not sc or sc[0].alert_key != "same_cause_streak:paper_a":
            fail(f"same_cause_streak alert_key wrong: {alerts!r}")
        else:
            print("OK: parsed synthetic same_cause_streak (alert raised)")

    # 3) Roundtrip dedupe file
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "last_tick.json"
        original = {"a:1": 1.5, "b:2": 2.5}
        save_dedupe(p, original, 99.0)
        loaded = load_dedupe(p)
        if loaded != original:
            fail(f"dedupe roundtrip {loaded!r} != {original!r}")
        else:
            print("OK: dedupe state file roundtrip")

    # 4) LarkNotifier dry-run: no subprocess
    with unittest.mock.patch("subprocess.run") as run_mock:
        n = LarkNotifier(cli_path="lark-cli", dry_run=True)
        ok = n.send_text(LarkRecipient("user_id", "ou_dummy"), "hello")
        run_mock.assert_not_called()
        if not ok:
            fail("dry_run send_text should return True")
        else:
            print("OK: LarkNotifier dry-run (would send to user_id=ou_dummy)")

    # 5) Dedupe suppression (1h ago within 4h window)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sr = root / "state"
        sr.mkdir(parents=True)
        esc = sr / "escalations.jsonl"
        base_ts = 3000000.0
        with esc.open("w", encoding="utf-8") as f:
            for i in range(3):
                f.write(
                    json.dumps(
                        {
                            "ts": base_ts + i * 60,
                            "worker_id": "paper_a",
                            "reason": "loop",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        cfg = root / "config.toml"
        cfg.write_text("[[workers]]\nid = \"paper_a\"\nenabled = false\n")
        alerts = collect_alerts(sr, cfg, now=base_ts + 120)
        dedupe = {"same_cause_streak:paper_a": base_ts - 3600}
        fresh, _ = filter_deduped(alerts, dedupe, now=base_ts + 120)
        if fresh:
            fail(f"dedupe should suppress same_cause, got {fresh!r}")
        else:
            print("OK: dedupe suppresses repeat within window")

    if failures:
        print(f"FAIL: {'; '.join(failures)}", file=sys.stderr)
        return 1
    print("OK: all checks passed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="cursor_manager sentinel watchdog")
    ap.add_argument("--dry-run", action="store_true", help="Do not send Lark; notifier dry-run")
    ap.add_argument("--self-test", action="store_true", help="Hermetic self-test")
    args = ap.parse_args()

    if args.self_test:
        return run_self_test()

    state_root = ROOT / "state"
    recipient_path = state_root / "sentinel" / "recipient.json"
    dedupe_path = state_root / "sentinel" / "last_tick.json"

    notifier = LarkNotifier(dry_run=args.dry_run)
    return tick(
        state_root=state_root,
        recipient_path=recipient_path,
        dedupe_path=dedupe_path,
        notifier=notifier,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
