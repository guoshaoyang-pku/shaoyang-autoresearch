# Sub-Agents Contract (autoresearch v2)

**Status**: spec for 2026-05 ship cycle
**Branch**: `feature/autoresearch-sub-agents`
**Companion**: `autoresearch_landscape_2026_05.md`（why these 4 modules）, `codex_backend_recipe.md`（codex CLI invocation details）

This file is a **contract** between 4 parallel implementation streams + the main integration line. Each subagent reads only its own module section + the "shared conventions" section. No subagent should depend on another subagent's runtime artifacts.

---

## 0. Shared conventions (read first)

### 0.1 Filesystem layout

```
tools/cursor_manager/
├── lib/
│   ├── state.py           # JsonlLog, AgentRegistry, file_lock, expand, WorkerRunInfo, workers_root
│   ├── codex_worker.py    # codex backend (sole in-loop LLM driver)
│   ├── git_probe.py       # existing helper
│   │
│   ├── reviewer_sim.py    # MODULE A (codex-only)
│   ├── lit_review.py      # MODULE B
│   ├── lark_notify.py     # MODULE C (helper)
│   └── ...                # (lib/local_worker.py, lib/reviewer.py, lib/cursor_api.py
│                          #  have been removed; they were the cursor-agent backend)
├── prompts/
│   ├── reviewer.md        # existing (manager-side reviewer)
│   ├── reviewer_sim_neurips.md  # MODULE A (new persona)
│   └── ...
├── docs/
│   └── sub_agents_contract.md   # this file
├── sentinel.py            # MODULE C (new top-level)
├── state/
│   ├── reviewer_sim/<worker>/<run_id>.md     # MODULE A output
│   ├── lit_review/<worker>/<run_id>.json     # MODULE B output
│   ├── sentinel/last_tick.json               # MODULE C state
│   └── workers/<worker>/codex_session.json   # MODULE D state (parallel to chat_id)
└── mgr                    # CLI (main integration line will add subcommands; subagents do NOT modify)
```

### 0.2 Hard "do not touch" rules for all subagents

- ❌ **Do NOT modify `mgr` CLI**. Each module exports a Python callable. Main integration line wires them into mgr argparse subcommands.
- ❌ **Do NOT modify `tick.sh`, `kickoff.sh`, `bootstrap.sh`, `config.example.toml`**. Same reason.
- ❌ **Do NOT modify existing `lib/*.py` files** (`state.py`, `codex_worker.py`, `git_probe.py`). Only ADD new ones.
- ❌ **Do NOT delete existing prompts** (`prompts/reviewer.md`, `prompts/manager.md`, `prompts/worker_paper_a.md`, `prompts/worker_paper_b.md`).
- ❌ **Do NOT push to remote**. Main integration line handles commit/push.
- ✅ **DO** add type hints + docstrings + an `if __name__ == "__main__":` block in each new `lib/<module>.py` that exercises the module standalone (so it can be smoke-tested without mgr).
- ✅ **DO** follow the existing code style (Python 3.11+, dataclasses for value objects, JSONL append-only for logs, `from .state import expand` for path expansion).
- ✅ **DO** add a `Stub<Module>` class fallback (mirror `StubReviewerSim` in `lib/reviewer_sim.py`) for offline/dry-run testing without external services.

### 0.3 Common state primitives

Use `from lib.state import JsonlLog, AgentRegistry, expand, file_lock`. Do not invent new persistence layers.

### 0.4 Commit policy (subagents)

Each subagent should:

1. Make 1-3 logical commits on `feature/autoresearch-sub-agents`. Style: `tools(cursor_manager): <module> <action>`.
2. Body explains WHY (not just what changed). Reference this contract doc as `docs/sub_agents_contract.md`.
3. Do NOT push. Main integration line will resolve conflicts (none expected, since modules touch disjoint files) and push once.

### 0.5 What "done" means

- Module file(s) created with stub fallback
- Standalone `python lib/<module>.py --self-test` (or `python sentinel.py --self-test`) prints `OK` without requiring the external service
- Brief usage block in module docstring telling the integration line how to import + call

---

## 1. MODULE A — Reviewer Simulator (NeurIPS reviewer persona)

### 1.1 Why

The manager already plays a paranoid-discipline reviewer over hard rules. **Module A adds a second, persona-specialized reviewer** invoked on demand: a NeurIPS reviewer simulator that critiques the worker's commit-diff for technical soundness, claim grounding, and missing experiments. The two reviewers are complementary, not redundant — manager judges hard-rule pass/fail, reviewer-sim judges NeurIPS-style acceptability.

Cross-API-model rule (codex-only loop): worker and reviewer-sim must use **different codex profiles** that map to different underlying API models — e.g. worker = `worker_high` → gpt-5.5-2026-04-24-xhigh, reviewer-sim = `reviewer_high` → claude-opus-4-7-thinking-high. Same-family review is too lenient. The integration line sets this from `config.toml`; the module just accepts `cli_path` + `profile` + `prompt_path` and runs codex.

### 1.2 Files to create

| Path | Purpose |
|---|---|
| `tools/cursor_manager/lib/reviewer_sim.py` | `ReviewerSim` class + `StubReviewerSim` |
| `tools/cursor_manager/prompts/reviewer_sim_neurips.md` | NeurIPS reviewer persona prompt |

### 1.3 API spec

```python
# lib/reviewer_sim.py

from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class ReviewerSimReport:
    overall_score: int  # 1-10 NeurIPS scale (1=trivial reject, 10=top accept)
    confidence: int     # 1-5 NeurIPS scale
    summary: str        # 2-3 sentences
    strengths: list[str]
    concerns: list[dict]  # [{"severity": "major|minor", "text": "...", "evidence_locator": "tex/main.tex:120 or commit abc"}]
    requested_changes: list[str]
    raw_response: str

    def to_markdown(self) -> str: ...
    @classmethod
    def parse(cls, raw: str) -> "ReviewerSimReport": ...


class ReviewerSim:
    """NeurIPS reviewer persona, invoked on demand by manager LLM."""

    def __init__(
        self,
        cli_path: str = "codex",
        profile: str = "reviewer_high",  # ~/.codex/config.toml [profiles.<profile>]
        prompt_path: str | Path = Path("prompts/reviewer_sim_neurips.md"),
        timeout_seconds: int = 600,
    ): ...

    def review(
        self,
        worker_label: str,
        target_diff: str,        # `git diff <base> HEAD` output
        target_commits: list[dict],  # commits-since-base summary
        worker_run_output: str = "",  # optional, last run stdout
        extra_context: dict | None = None,  # e.g. {"hard_rules": "...", "section_focus": "abstract"}
    ) -> ReviewerSimReport: ...


class StubReviewerSim:
    """Heuristic fallback for offline testing (no LLM call)."""

    def review(self, *args, **kwargs) -> ReviewerSimReport:
        # Return a deterministic dummy report (overall_score=5, 1 minor concern)
        ...
```

### 1.4 Output

`state/reviewer_sim/<worker_id>/<run_id>.md` — structured Markdown using `ReviewerSimReport.to_markdown()`. Schema:

```markdown
# NeurIPS Reviewer Sim — <worker_id> <run_id>

**Overall**: 5/10  **Confidence**: 3/5
**Generated**: 2026-05-03T19:45:12+0800

## Summary
<2-3 sentences>

## Strengths
- ...

## Concerns
- **[major]** <text> — evidence: tex/main.tex:120
- **[minor]** ...

## Requested changes
- ...
```

### 1.5 Persona prompt (for `prompts/reviewer_sim_neurips.md`)

Write a prompt that:

- Identifies the LLM as a senior NeurIPS reviewer (5+ years reviewing)
- Top concerns: claim-evidence grounding, missing baselines, statistical insufficiency (single-seed claims), incremental novelty, citation gaps for must-cite
- **Strict output**: must end with a JSON block with the exact `ReviewerSimReport` field schema (the parse method should tolerate ```json``` code fence wrap)
- Inputs received: `target_diff`, `target_commits`, `worker_run_output`, optional `extra_context`
- Behavioral rules: focus only on the diff; do not re-review the whole paper; assume the rest is fine unless the diff actively breaks it; severity "major" = would lower a NeurIPS score, "minor" = nice-to-fix

### 1.6 Self-test

```bash
cd tools/cursor_manager
python -m lib.reviewer_sim --self-test
# Should print:
# OK: ReviewerSimReport.parse roundtrip
# OK: StubReviewerSim returns deterministic report
# OK: NeurIPS persona prompt loads (1234 chars)
```

---

## 2. MODULE B — Lit Review (Semantic Scholar API)

### 2.1 Why

We need to (a) verify all references in the paper's `.bib` exist on Semantic Scholar (catch hallucinated citations) and (b) given a list of "topic keywords + must-cite candidates", check what mainstream papers we're missing. PaperOrchestra's headline contribution.

### 2.2 Files to create

| Path | Purpose |
|---|---|
| `tools/cursor_manager/lib/lit_review.py` | `LitReview` class + `StubLitReview` + `SemanticScholarClient` |

### 2.3 API spec

```python
# lib/lit_review.py

from dataclasses import dataclass
from pathlib import Path

@dataclass
class CitationCheckEntry:
    bib_key: str          # "smith2024foo"
    title: str | None
    found: bool
    semantic_scholar_id: str | None
    matched_title: str | None  # title from SS (compare with .bib title)
    year: int | None
    issue: str | None     # "not_found" | "year_mismatch" | "title_mismatch" | None


@dataclass
class MustCiteSuggestion:
    title: str
    authors: list[str]
    year: int
    venue: str
    semantic_scholar_id: str
    citation_count: int
    relevance_reason: str  # "matches keyword 'inductive bias'" or "co-cited with [bib_key]"
    bib_entry: str         # ready-to-paste @inproceedings{...}


@dataclass
class LitReviewReport:
    bib_path: str
    n_entries_total: int
    n_verified: int
    n_unverified: int
    citation_checks: list[CitationCheckEntry]
    must_cite_suggestions: list[MustCiteSuggestion]
    keywords_searched: list[str]
    generated_at: float

    def to_dict(self) -> dict: ...
    def to_markdown_summary(self) -> str: ...


class SemanticScholarClient:
    """Thin wrapper around https://api.semanticscholar.org/graph/v1/."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, api_key: str | None = None, rate_limit_rps: float = 1.0):
        # Free tier without key: ~1 RPS shared. With key: 100 RPS.
        ...

    def search_by_title(self, title: str, *, fields: list[str] | None = None) -> dict | None: ...
    def search_by_keyword(self, keyword: str, limit: int = 10, *, fields: list[str] | None = None) -> list[dict]: ...
    def get_paper(self, paper_id: str, *, fields: list[str] | None = None) -> dict | None: ...
    # paper_id can be S2 ID, DOI:..., ARXIV:..., URL:...


class LitReview:
    def __init__(self, client: SemanticScholarClient | None = None):
        self.client = client or SemanticScholarClient()

    def check_bib(self, bib_path: str | Path) -> list[CitationCheckEntry]:
        """Parse .bib, look up each entry by title, return verification list."""
        ...

    def suggest_must_cites(
        self,
        keywords: list[str],
        existing_bib_keys: set[str],
        *,
        max_suggestions: int = 20,
        min_citations: int = 30,
    ) -> list[MustCiteSuggestion]:
        """For each keyword, search top-K papers, dedupe against existing bib, suggest must-cites."""
        ...

    def run_full(
        self,
        bib_path: str | Path,
        keywords: list[str] | None = None,
    ) -> LitReviewReport: ...


class StubLitReview:
    """Offline fallback. Returns dummy report; useful for CI / no network."""
    def run_full(self, bib_path, keywords=None) -> LitReviewReport: ...
```

### 2.4 Output

`state/lit_review/<worker_id>/<run_id>.json` — `LitReviewReport.to_dict()` serialized. Also write `<run_id>.md` summary for human review.

### 2.5 .bib parser

You may use the standard library only OR add `bibtexparser` as a `try: import` with fallback. Prefer pure stdlib: a regex like `r'@\w+\s*\{\s*([^,]+),\s*(.*?)\n\}'` with multiline mode is enough for our paper's well-formed .bib. Skip @comment / @string entries.

### 2.6 Self-test

```bash
cd tools/cursor_manager
python -m lib.lit_review --self-test
# Should print (without network):
# OK: parsed dummy bib (3 entries)
# OK: StubLitReview returns deterministic report
# OK: SemanticScholarClient instantiates
# (Optional with --network flag): performs 1 real API call to verify a known paper exists
```

### 2.7 Rate limit & error handling

- Default rate limit: 1 RPS (Semantic Scholar free tier).
- Retry: on HTTP 429, sleep 5s and retry up to 3 times.
- On HTTP 5xx: fail soft, log warning to stderr, set `found=False, issue="api_error"`.
- Timeout per request: 10s.
- `requests` library: prefer stdlib `urllib.request` to keep dependency-free.

---

## 3. MODULE C — Sentinel watchdog + Lark notification

### 3.1 Why

Cursor-agent loop ran 24h on GPU with `exit code 1` and nobody noticed. Sentinel watches manager audit + escalations; on suspicious patterns (continuous same-cause failure, no progress for K hours) it sends a Lark message.

### 3.2 Files to create

| Path | Purpose |
|---|---|
| `tools/cursor_manager/sentinel.py` | Top-level entry: `python sentinel.py [--self-test] [--dry-run]` |
| `tools/cursor_manager/lib/lark_notify.py` | `LarkNotifier` wrapper around `lark-cli im +messages-send` |

### 3.3 API spec

```python
# lib/lark_notify.py

from dataclasses import dataclass

@dataclass
class LarkRecipient:
    kind: str   # "user_id" | "chat_id" | "open_id" | "email"
    value: str  # the actual ID/email


class LarkNotifier:
    """Wrapper around `lark-cli im +messages-send`. Falls back to no-op + stderr warning if lark-cli missing."""

    def __init__(
        self,
        cli_path: str = "lark-cli",
        identity: str = "user",   # "user" | "bot"
        dry_run: bool = False,
    ): ...

    def send_text(self, recipient: LarkRecipient, text: str) -> bool: ...
    def send_markdown(self, recipient: LarkRecipient, markdown: str) -> bool: ...
    def is_available(self) -> bool:
        """Return True if `lark-cli` is on PATH and responds to --version."""
        ...
```

```python
# sentinel.py

#!/usr/bin/env python3
"""
Sentinel watchdog: runs as a cron tick, scans manager audit logs + escalations,
detects patterns of stuck/looping/silent failures, sends Lark notification.

Usage:
    python sentinel.py                   # one tick, real run
    python sentinel.py --dry-run         # don't send Lark, just print what would
    python sentinel.py --self-test       # offline test (no FS scan, no Lark call)
"""

# Logic:
# 1. Read state/log.jsonl tail (last 200 events)
# 2. Read state/escalations.jsonl tail (last 50)
# 3. Read state/manager_audits/*.jsonl tail (per worker)
# 4. Compute heuristics:
#    - same_cause_streak: same escalation reason >= 3 in last hour
#    - exit_code_streak: worker's last 5 runs all exit_code != 0
#    - silence_hours: no commit on worker's branch for >= K hours (config: silence_hours_threshold)
#    - tick_failure_streak: >= 5 ticks with action="escalate" in last 30 min
# 5. Read state/sentinel/last_tick.json: which alerts already sent in last X hours (dedupe)
# 6. If new alert(s) trigger -> compose Markdown report + send via LarkNotifier
# 7. Update state/sentinel/last_tick.json
```

### 3.4 Heuristic thresholds (defaults; integration line will move them to config)

| Heuristic | Threshold | Lark severity |
|---|---|---|
| Same escalation reason >= 3 within last 60 min | 3 | high |
| Worker exit_code != 0 for last 5 consecutive runs | 5 | high |
| No new commit on worker branch for >= 12 hours (and worker is enabled) | 12h | medium |
| Tick action="escalate" >= 5 within last 30 min | 5 | high |
| Manager itself returns non-zero >= 3 ticks consecutive | 3 | critical |

Dedupe: same alert key (heuristic + worker_id) within `dedupe_hours = 4` is suppressed.

### 3.5 Lark message template

```markdown
🚨 **cursor_manager sentinel alert** [<severity>]

- **worker**: paper_a
- **trigger**: same escalation reason >= 3 in 60 min
- **last reasons**:
    1. [HH:MM] <reason 1>
    2. [HH:MM] <reason 2>
    3. [HH:MM] <reason 3>
- **suggested action**: ssh into gpu_develop and check `mgr audit paper_a -n 20`

(Sent by cursor_manager/sentinel.py @ 2026-05-03T19:45+0800)
```

### 3.6 Self-test

```bash
cd tools/cursor_manager
python sentinel.py --self-test
# Should print:
# OK: parsed empty audit/log/escalations (no false positives)
# OK: parsed synthetic same_cause_streak (alert raised)
# OK: dedupe state file roundtrip
# OK: LarkNotifier dry-run (would send to user_id=<dummy>)
```

### 3.7 Recipient configuration

Sentinel reads `state/sentinel/recipient.json` for the alert target (kind + value). If the file doesn't exist, sentinel logs a warning to stderr and exits 0. Integration line will document creating this file with the user's Lark user_id (resolvable via `lark-cli contact +open-id-by-name "Guo Shaoyang"`).

---

## 4. MODULE D — Codex Backend (sole in-loop worker driver)

### 4.1 Why

Codex is the only LLM CLI we can run on remote GPU hosts (cross-platform tokens make cursor-agent infeasible there). Verified working invocation documented in `docs/codex_backend_recipe.md`. Module D is the Python plumbing that wraps `codex exec` / `codex exec resume` into a `Worker`-like object. After the cursor-agent backend was removed, `CodexWorker` is the *only* worker class in the loop.

### 4.2 Files to create / modify

| Path | Purpose |
|---|---|
| `tools/cursor_manager/lib/codex_worker.py` | `CodexWorker` class (the only worker backend) |

The legacy `lib/local_worker.py` (cursor-agent worker) has been deleted; `mgr` constructs `CodexWorker` directly and rejects any other value of `[worker].backend` at config load time.

### 4.3 API spec

```python
# lib/codex_worker.py

from .state import WorkerRunInfo, workers_root  # dataclass + path helper

class CodexWorker:
    """The sole worker backend; invokes `codex exec` / `codex exec resume`."""

    def __init__(
        self,
        worker_id: str,
        cli_path: str = "codex",
        profile: str = "high",          # codex --profile <profile>
        skip_git_repo_check: bool = True,
        color: str = "never",
        sandbox_mode: str = "danger-full-access",  # required for write tasks
    ): ...

    # Same accessor properties as LocalWorker:
    @property
    def session_id(self) -> str | None:
        """Codex session id, stored in state/workers/<id>/codex_session.json."""
        ...
    @session_id.setter
    def session_id(self, value: str) -> None: ...

    @property
    def worktree_path(self) -> str | None: ...
    @property
    def branch(self) -> str | None: ...

    def get_run(self) -> WorkerRunInfo | None: ...

    def start(
        self,
        prompt: str,
        timeout_seconds: int = 1800,
        extra_env: dict | None = None,
    ) -> WorkerRunInfo:
        """
        Build command:
          codex exec --skip-git-repo-check --color never --profile high \
              -C <worktree_path> "<prompt>" < /dev/null
        On first call (no session_id), parse `session id: <uuid>` from stdout.
        On subsequent: codex exec resume <session-id> --color never -C ... "..." < /dev/null
        """
        ...

    def cancel(self) -> bool: ...
    def read_raw_output(self) -> str: ...
    def read_output(self, max_chars: int = 8000) -> str: ...
    def extract_session_id(self) -> str | None:
        """Regex `session id: ([0-9a-f-]+)` from output.log."""
        ...
    def to_dict(self) -> dict: ...


# Helper: parse codex stdout structure described in docs/codex_backend_recipe.md
def parse_codex_output(raw: str) -> dict:
    """
    Returns: {
      "session_id": str | None,
      "model": str | None,
      "provider": str | None,
      "user_echo": str,       # the prompt as codex echoed it
      "assistant_message": str,  # the actual response
      "tokens_used": int | None,
    }
    """
    ...
```

### 4.4 State

`state/workers/<id>/` layout:
- `codex_session.json`: `{"session_id": "...", "captured_at": <ts>, "first_run_id": "..."}`
- `last_run/` (pid, output.log, prompt.txt, meta.json, exit_code, run_id)
- `history.jsonl`

### 4.5 The stdin trap

Per `docs/codex_backend_recipe.md`: `codex exec` hangs without `< /dev/null`. The wrapper script MUST redirect stdin from /dev/null. `CodexWorker._build_wrapper_script` already does this, and `scripts/_invoke_manager.py` mirrors the same redirect for the manager's tick / kickoff calls.

### 4.6 Self-test

```bash
cd tools/cursor_manager
python -m lib.codex_worker --self-test
# Should print:
# OK: CodexWorker instantiates without codex CLI on PATH
# OK: parse_codex_output handles synthetic output (extracts session_id)
# OK: wrapper script generation includes < /dev/null
# (Optional with --network: performs a trivial `codex exec` smoke test, requires codex CLI + proxy)
```

### 4.7 Local proxy / config out of scope

The codex CLI's `~/.codex/config.toml` and ByteDance proxy setup are already done on the GPU machine and documented in `docs/codex_backend_recipe.md`. Module D doesn't touch those. If `codex` is not on PATH, `CodexWorker.start()` should raise `RuntimeError("codex CLI not found on PATH; see docs/codex_backend_recipe.md for installation")`.

---

## 5. Integration line (main agent, NOT a subagent)

After all 4 modules report done + smoke-test passes, the main integration line:

1. Adds 4 new mgr subcommands:
   - `mgr review-sim <worker> [--against HEAD] [--persona neurips]` → invokes `ReviewerSim.review()`, writes Markdown to `state/reviewer_sim/<worker>/<run_id>.md`, prints path
   - `mgr lit-review <worker> [--bib path/to/refs.bib] [--keywords k1,k2,k3]` → invokes `LitReview.run_full()`, writes JSON + Markdown
   - `mgr sentinel-tick [--dry-run]` → invokes `sentinel.tick()` once
   - `mgr backend-test <worker>` → smoke-tests the codex CLI (the only supported backend)
2. Adds `[reviewer_sim]`, `[lit_review]`, `[sentinel]` sections to `config.example.toml`
3. Updates `prompts/manager.md` to mention when to use the new subcommands
4. Updates `README.md` with the new sub-agent overview
5. Adds `tools/cursor_manager/scripts/smoke_test_sub_agents.sh` that runs all 4 self-tests + a tiny end-to-end check
6. Commits + pushes to `feature/autoresearch-sub-agents`

---

## 6. Subagent kickoff checklist (each module agent reads this)

Before starting:

- [ ] Read this contract doc end-to-end
- [ ] Read `docs/autoresearch_landscape_2026_05.md` for context (only the section relevant to your module)
- [ ] Read `lib/state.py` to understand JsonlLog / AgentRegistry primitives
- [ ] Read `lib/reviewer.py` to understand the existing Reviewer + Verdict pattern (Module A mirrors this; others may borrow the StubXxx pattern)
- [ ] Confirm you're on branch `feature/autoresearch-sub-agents`

While working:

- [ ] Make small commits with `tools(cursor_manager): <module> <verb>` style
- [ ] Each commit body explains WHY
- [ ] Do NOT push
- [ ] Add module docstring + standalone `__main__` block

When done:

- [ ] Self-test runs and prints OK
- [ ] Module file imports cleanly (`python -c "from lib.<module> import <Class>"` or sentinel `python sentinel.py --self-test`)
- [ ] Report back to integration line: which files added, smoke-test command, any external dependencies added (should be NONE besides stdlib)
