# cursor_manager Meta Paper — Outline (working draft)

**Status**: dogfood seed (2026-05-03). The worker may propose changes
to this outline via `[BLOCKED-DECISION]` commit before substantive
section drafting. **Do not silently rewrite the outline** — escalate first.

---

## Working title

> **Turning Tokens into Research: An Adversarial Multi-Agent Framework for Submission-Grade Paper Writing under Unbounded Token Budgets**

Alternative subtitle (worker may propose `[BLOCKED-DECISION]` to switch):

- "When Tokens Are Cheap, Discipline Is Expensive"
- "Hard Rules over Hard Compute: Discipline-First Multi-Agent Paper Writing"

## One-sentence thesis

Given effectively unbounded inference token budgets (modern API tiers + local models), the bottleneck for autoresearch shifts from **scale** to **discipline**: claim drift, citation hallucination, reward hacking on LLM-judges, and silent failures of long-running loops. We propose **cursor\_manager**, an adversarial multi-agent framework whose four discipline mechanisms — hard-rule enforcement, BLOCKED-DECISION protocol, cross-model adversarial review, and Sentinel observability — yield submission-grade output under exactly the conditions where existing autoresearch systems collapse.

## Core claims (numbered, each must be defended in §3-§5)

- **C1**: Token budget is no longer the binding constraint for autoresearch; discipline is. Existing systems (PaperOrchestra, Sibyl, AI Scientist v2) optimize for benchmark scoreboards, not real-conference submission, and consequently lack the discipline mechanisms required for the latter.
- **C2**: A simple **manager-worker adversarial loop** (1 + 1 LLM, optionally with a third reviewer-sim) with **persistent state** (git worktree, JSONL audit, session-id resume) outperforms multi-agent debate (Sibyl 6-agent) on the submission-grade dimension while costing 10x fewer tokens.
- **C3**: **Cross-model adversarial review** (manager and worker on different model families) materially reduces reward hacking on LLM-judges. We provide an ablation where same-model self-review fails on a deliberately injected hard-rule violation in $X$\% of cases vs. cross-model in $Y$\%.
- **C4**: A four-rule **discipline contract** (hard-rule, BLOCKED-DECISION, must-cite verification via Semantic Scholar, sentinel watchdog) suffices to bring multi-agent paper writing from benchmark grade to submission grade. Each rule's individual contribution is ablated.
- **C5** (conditional): On two real NeurIPS 2026 submissions (CA / Physics ICL; LLM Geometry), cursor\_manager produced N\_A and N\_B accepted commits respectively, averted M\_A and M\_B hard-rule violations, surfaced K\_A and K\_B BLOCKED-DECISIONs that turned out to be material, and closed L\_A and L\_B citation gaps via lit-review sub-agent. (Numbers from `state/audit/*.jsonl` — **must** be queried, not invented.)

## Section outline (8 page NeurIPS template)

| § | Title | Pages | Key points |
|---|---|---|---|
| Abstract | — | 1 paragraph | C1 + C2 hook + C5 numbers |
| 1 | Introduction | 1.5 | The "unbounded tokens, no discipline" problem; preview of 4 discipline mechanisms; preview of dogfood case study |
| 2 | Related Work | 1.0 | PaperOrchestra (lit review + plot agent), Sibyl (multi-agent debate, dual-loop), AI Scientist v2 (peer-review + tree search), Karpathy AutoResearch (program.md spec), Agent Laboratory (3-stage). Position: all five optimize for benchmark; we optimize for submission. |
| 3 | Architecture | 2.0 | Manager-worker adversarial loop; mgr CLI atomic operations; git worktree isolation; sub-agent contract design (4 modules ship-able in parallel). Figure: system diagram. Algorithm 1: tick-loop pseudocode. |
| 4 | Discipline Mechanisms | 1.0 | (a) Hard rules + claim-protected zones; (b) BLOCKED-DECISION protocol with escalation queue; (c) Cross-model adversarial review (reviewer\_sim); (d) Sentinel watchdog with Lark notification + dedupe. Each as a 1-paragraph subsection with the failure mode it addresses. |
| 5 | Empirical Case Study (Dogfood) | 2.0 | Three case studies: (i) writing this paper; (ii) CA / Physics ICL paper; (iii) LLM Geometry paper. Table 1: per-paper aggregates from audit log. Table 2: cross-model adversarial ablation. Table 3: lit-review citation-gap closure. |
| 6 | Discussion and Limitations | 0.5 | What we don't do (no end-to-end idea-to-paper, no plot agent, no GPU scheduler); when our framework is wrong choice; cost analysis. |
| 7 | Conclusion | 0.25 | Discipline > scale; open-source pointer. |
| References | — | (extra) | $\geq$ 5 must-cites: PaperOrchestra (2604.05018), Sibyl, AI Scientist v2 (2504.08066), Karpathy AutoResearch, Agent Laboratory (2501.04227). Plus any lit-review sub-agent finds. |

## Must-cite list (HR-5: lit-review sub-agent verifies all exist on Semantic Scholar)

1. PaperOrchestra: arxiv 2604.05018 (2026)
2. Sibyl Research System: github.com/Sibyl-Research-Team/sibyl-research-system
3. AI Scientist v2: arxiv 2504.08066 (2025)
4. Karpathy AutoResearch: github.com/karpathy/AutoResearch
5. Agent Laboratory: arxiv 2501.04227 (2025)
6. (recommended) The AI Scientist v1: arxiv 2408.06292 (2024)
7. (recommended) AI-Researcher: arxiv 2505.18705 (2025)
8. (lit-review may add) FML-Bench: ICLR 2026 under-review benchmark
9. (lit-review may add) PaperReconstruction Evaluation: arxiv 2604.01128 (2026)

## Numbers that **must** be queried at write time (no hallucination, HR-6)

When drafting §5 (Case Study), the worker must read these state files and not invent numbers:

- `state/log.jsonl` — total events, total manager_start_run count, etc.
- `state/escalations.jsonl` — count, latest reasons, dedupe pattern
- `state/manager_audits/*.jsonl` — per-worker tick history
- `state/workers/*/history.jsonl` — per-worker run history with exit codes + tokens (codex meta.json)
- `state/reviewer_sim/*/*.md` — per-review concern counts and overall scores
- `state/lit_review/*/*.json` — per-run citation verification outcomes

For each number reported in §5, the worker must include in the commit message a one-line provenance: e.g., `paper(meta): §5.1 add 142 manager_start_run from state/log.jsonl rev abc123`.

## Hard "do NOT do" items

- ❌ Do NOT fabricate numbers in §5. If audit log is empty or sparse, add a placeholder `\cite{NUMBERS-PENDING-AUDIT-FETCH}` and `[BLOCKED-DECISION]` so the human can decide whether to wait, simulate, or pivot.
- ❌ Do NOT change the working title without `[BLOCKED-DECISION]`. Title is a claim.
- ❌ Do NOT extend beyond 8 pages (NeurIPS 2026 main + workshop both cap; ICLR 2027 caps at 9 with extra page for ethics — defer venue choice as `[BLOCKED-DECISION]`).
- ❌ Do NOT touch other workers' state or any file outside `tools/cursor_manager/paper_meta/`.
- ❌ Do NOT use emoji anywhere in the paper text.
- ❌ Do NOT omit Limitations subsections in §6 — venue checklists require it.

## Decision queue (raise as `[BLOCKED-DECISION]` commits when reached)

1. **Final title**: 3 candidate variants in §"Working title" — pick at v1.
2. **Target venue**: NeurIPS 2026 workshop / ICLR 2027 / ACL 2027 demo / multi-venue strategy. Affects page count, anonymization, and dual-submission policy. **Decided**: per chat 2026-05-03, deferred until v1 draft.
3. **Authorship + acknowledgement list**: anonymized for review; worker leaves placeholder.
4. **Open-source license + repo URL**: required by §6 for the "open-source pointer" claim. Worker should `[BLOCKED-DECISION]` and let human decide MIT / Apache / BSD / restricted.
5. **Whether to include codex profile vs. profile cost comparison numbers** (e.g., gpt-5.5 worker vs. claude-opus reviewer-sim): depends on whether ByteDance internal pricing is shareable. Worker `[BLOCKED-DECISION]` if asked to write the dollar table.
6. **Reproducibility checklist** (NeurIPS requires): worker should fill in conservatively and `[BLOCKED-DECISION]` for any uncertain item.

## Reproducibility scaffolding (mirror paper A's pattern)

When v1 draft stable, generate these companions (lower priority, after v1):

- `paper_meta/CHECKLIST_CN.md` — 中文决策看板
- `paper_meta/COVER_LETTER_DRAFT.md` — for venue-specific submission
- `paper_meta/REPRODUCIBILITY_PLAN.md` — code release scope, audit log redaction policy
- `paper_meta/RESPONSE_PLAYBOOK.md` — for rebuttal / reviewer Q&A

## Provenance of this outline

Drafted by main integration agent on 2026-05-03 after research summarized in `docs/autoresearch_landscape_2026_05.md` and the user's directive to dogfood the system on a meta paper with thesis "tokens to research productivity". Open to challenge by worker via `[BLOCKED-DECISION]`.
