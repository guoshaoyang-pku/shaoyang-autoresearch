"""NeurIPS-style reviewer simulator (codex-only; cross-API-model critique).

Integration invokes ``ReviewerSim.review()`` with the codex CLI path and a
codex profile (the profile selects the underlying API model -- e.g. one
profile maps to claude-opus, another to gpt-5.5 -- so cross-API-model
adversarial review is achieved by giving the worker and the reviewer-sim
*different* codex profiles). Output is written as Markdown via
``ReviewerSimReport.to_markdown()`` under ``state/reviewer_sim/``
(wiring lives in mgr).

See ``docs/sub_agents_contract.md`` § MODULE A.

Usage::

    from pathlib import Path
    from lib.reviewer_sim import ReviewerSim, StubReviewerSim, ReviewerSimReport

    sim = ReviewerSim(
        cli_path="codex",
        profile="reviewer_high",   # different from worker's profile
        prompt_path=Path("prompts/reviewer_sim_neurips.md"),
    )
    report = sim.review(
        worker_label="paper_a",
        target_diff="...",
        target_commits=[{"hash": "abc", "subject": "..."}],
    )
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_pkg_root = Path(__file__).resolve().parent.parent
if __package__ is None:
    sys.path.insert(0, str(_pkg_root))

try:
    from .state import expand
except ImportError:
    from lib.state import expand


@dataclass
class ReviewerSimReport:
    overall_score: int  # 1-10 NeurIPS scale (1=trivial reject, 10=top accept)
    confidence: int  # 1-5 NeurIPS scale
    summary: str  # 2-3 sentences
    strengths: list[str]
    concerns: list[dict[str, Any]]  # severity, text, evidence_locator
    requested_changes: list[str]
    raw_response: str

    def to_markdown(self) -> str:
        """Format report for ``state/reviewer_sim/<worker>/<run_id>.md``."""
        gen = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        lines = [
            "# NeurIPS Reviewer Sim",
            "",
            f"**Overall**: {self.overall_score}/10  **Confidence**: {self.confidence}/5",
            f"**Generated**: {gen}",
            "",
            "## Summary",
            self.summary,
            "",
            "## Strengths",
        ]
        for s in self.strengths:
            lines.append(f"- {s}")
        lines.extend(["", "## Concerns"])
        for c in self.concerns:
            sev = (c.get("severity") or "minor").lower()
            text = c.get("text") or ""
            loc = c.get("evidence_locator") or ""
            lines.append(f"- **[{sev}]** {text} — evidence: {loc}")
        lines.extend(["", "## Requested changes"])
        for r in self.requested_changes:
            lines.append(f"- {r}")
        lines.append("")
        return "\n".join(lines)

    @classmethod
    def parse(cls, raw: str) -> ReviewerSimReport:
        """Parse model output; tolerate ```json``` fences and leading prose (same idea as ``Verdict.parse``)."""
        text = raw.strip()
        json_str: str | None = None

        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            json_str = m.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                json_str = text[start : end + 1]

        if not json_str:
            return cls(
                overall_score=0,
                confidence=1,
                summary=f"parse failed: no JSON object found in model output ({text[:200]!r}…)",
                strengths=[],
                concerns=[],
                requested_changes=[],
                raw_response=raw,
            )

        try:
            d = json.loads(json_str)
        except json.JSONDecodeError as e:
            return cls(
                overall_score=0,
                confidence=1,
                summary=f"parse failed: JSON decode error: {e}",
                strengths=[],
                concerns=[],
                requested_changes=[],
                raw_response=raw,
            )

        try:
            score = int(d.get("overall_score", 0))
            conf = int(d.get("confidence", 1))
            summary = str(d.get("summary", "")).strip()
            strengths = [str(x) for x in (d.get("strengths") or [])]
            req = [str(x) for x in (d.get("requested_changes") or [])]
            concerns_raw = d.get("concerns") or []
            concerns: list[dict[str, Any]] = []
            for item in concerns_raw:
                if not isinstance(item, dict):
                    continue
                sev = str(item.get("severity", "minor")).lower()
                if sev not in ("major", "minor"):
                    sev = "minor"
                concerns.append(
                    {
                        "severity": sev,
                        "text": str(item.get("text", "")),
                        "evidence_locator": str(item.get("evidence_locator", "")),
                    }
                )
        except (TypeError, ValueError) as e:
            return cls(
                overall_score=0,
                confidence=1,
                summary=f"parse failed: invalid field types: {e}",
                strengths=[],
                concerns=[],
                requested_changes=[],
                raw_response=raw,
            )

        return cls(
            overall_score=score,
            confidence=conf,
            summary=summary,
            strengths=strengths,
            concerns=concerns,
            requested_changes=req,
            raw_response=raw,
        )


class ReviewerSim:
    """NeurIPS reviewer persona, invoked on demand by manager LLM."""

    def __init__(
        self,
        cli_path: str = "codex",
        profile: str = "reviewer_high",
        prompt_path: str | Path = Path("prompts/reviewer_sim_neurips.md"),
        timeout_seconds: int = 600,
    ):
        self.cli_path = cli_path
        self.profile = profile
        self.timeout = timeout_seconds
        self.prompt_template = expand(prompt_path).read_text(encoding="utf-8")

    def review(
        self,
        worker_label: str,
        target_diff: str,
        target_commits: list[dict],
        worker_run_output: str = "",
        extra_context: dict | None = None,
    ) -> ReviewerSimReport:
        full_prompt = self._build_prompt(
            worker_label,
            target_diff,
            target_commits,
            worker_run_output,
            extra_context,
        )
        return self._run_codex(full_prompt)

    def _build_codex_bash_command(self, prompt: str) -> str:
        """Single bash command line: codex exec ... PROMPT < /dev/null (for subprocess -c).

        Critical: stdin must be ``< /dev/null`` -- without it codex hangs
        waiting for additional input. Documented in
        ``docs/codex_backend_recipe.md``.
        """
        exe = shlex.quote(self.cli_path)
        prof = shlex.quote(self.profile)
        pq = shlex.quote(prompt)
        return f"{exe} exec --skip-git-repo-check --color never --profile {prof} {pq} < /dev/null"

    def _run_codex(self, full_prompt: str) -> ReviewerSimReport:
        cmd = self._build_codex_bash_command(full_prompt)
        try:
            proc = subprocess.run(
                ["/bin/bash", "-c", cmd],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env={**os.environ},
            )
        except subprocess.TimeoutExpired:
            return ReviewerSimReport(
                overall_score=0,
                confidence=1,
                summary=f"reviewer-sim failed: codex subprocess timeout ({self.timeout}s)",
                strengths=[],
                concerns=[],
                requested_changes=[],
                raw_response="",
            )
        except FileNotFoundError:
            return ReviewerSimReport(
                overall_score=0,
                confidence=1,
                summary="reviewer-sim failed: /bin/bash not found",
                strengths=[],
                concerns=[],
                requested_changes=[],
                raw_response="",
            )

        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            return ReviewerSimReport(
                overall_score=0,
                confidence=1,
                summary=f"reviewer-sim failed: codex exit {proc.returncode}: {(proc.stderr or proc.stdout)[:400]!r}",
                strengths=[],
                concerns=[],
                requested_changes=[],
                raw_response=out,
            )
        return ReviewerSimReport.parse(out)

    def _build_prompt(
        self,
        worker_label: str,
        target_diff: str,
        target_commits: list[dict],
        worker_run_output: str,
        extra_context: dict | None,
    ) -> str:
        commits_json = json.dumps(target_commits, ensure_ascii=False, indent=2)
        extra_json = json.dumps(extra_context or {}, ensure_ascii=False, indent=2)
        return (
            self.prompt_template.replace("{{worker_label}}", worker_label)
            .replace("{{target_diff}}", target_diff)
            .replace("{{target_commits}}", commits_json)
            .replace("{{worker_run_output}}", worker_run_output or "(none)")
            .replace("{{extra_context}}", extra_json)
        )


class StubReviewerSim:
    """Heuristic fallback for offline testing (no LLM call)."""

    def review(self, *args: Any, **kwargs: Any) -> ReviewerSimReport:
        return ReviewerSimReport(
            overall_score=5,
            confidence=3,
            summary=(
                "[stub] Deterministic NeurIPS-sim placeholder: one minor concern, "
                "no model invocation."
            ),
            strengths=["[stub] Diff present; offline path exercised."],
            concerns=[
                {
                    "severity": "minor",
                    "text": "[stub] Replace stub with real ReviewerSim for substantive review.",
                    "evidence_locator": "stub:offline",
                }
            ],
            requested_changes=["[stub] Run full reviewer-sim with configured CLI when online."],
            raw_response="",
        )


def _self_test() -> int:
    # 1) parse roundtrip
    sample = {
        "overall_score": 7,
        "confidence": 4,
        "summary": "Solid diff with adequate baselines.",
        "strengths": ["Clear writing"],
        "concerns": [
            {
                "severity": "minor",
                "text": "Single-seed table.",
                "evidence_locator": "experiments.tex:40",
            }
        ],
        "requested_changes": ["Add error bars"],
    }
    raw_json = json.dumps(sample, ensure_ascii=False)
    r1 = ReviewerSimReport.parse(raw_json)
    if r1.overall_score != 7 or r1.confidence != 4 or len(r1.strengths) != 1:
        print("FAIL: roundtrip parse mismatch", file=sys.stderr)
        return 1

    fenced = "Here is the verdict.\n```json\n" + raw_json + "\n```\n"
    r2 = ReviewerSimReport.parse(fenced)
    if r2.overall_score != 7:
        print("FAIL: fenced parse mismatch", file=sys.stderr)
        return 1

    bad = ReviewerSimReport.parse("no json here at all")
    if bad.overall_score != 0 or "parse failed" not in bad.summary:
        print("FAIL: parse failure should yield score 0", file=sys.stderr)
        return 1

    stub = StubReviewerSim().review()
    if stub.overall_score != 5 or len(stub.concerns) != 1:
        print("FAIL: StubReviewerSim not deterministic as expected", file=sys.stderr)
        return 1
    if stub.concerns[0].get("severity") != "minor":
        print("FAIL: stub concern severity", file=sys.stderr)
        return 1

    prompt_path = _pkg_root / "prompts" / "reviewer_sim_neurips.md"
    body = expand(prompt_path).read_text(encoding="utf-8")
    if not body.strip():
        print("FAIL: empty persona prompt", file=sys.stderr)
        return 1

    sim = ReviewerSim(
        cli_path="codex",
        profile="reviewer_high",
        prompt_path=prompt_path,
    )
    inner = sim._build_codex_bash_command("PROMPT")
    if "< /dev/null" not in inner:
        print("FAIL: codex bash command missing stdin redirect", file=sys.stderr)
        return 1
    if "--profile reviewer_high" not in inner:
        print("FAIL: codex profile not propagated", file=sys.stderr)
        return 1

    md = r1.to_markdown()
    if "7/10" not in md or "## Concerns" not in md:
        print("FAIL: to_markdown missing expected sections", file=sys.stderr)
        return 1

    print("OK: all checks passed")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="NeurIPS reviewer simulator")
    p.add_argument("--self-test", action="store_true", help="run offline checks and exit")
    args = p.parse_args()
    if args.self_test:
        raise SystemExit(_self_test())
    p.print_help()


if __name__ == "__main__":
    main()
