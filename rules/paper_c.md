# 论文 C (cursor_manager 系统 meta paper, dogfood) Worker 专属规则

仓库子目录：`tools/cursor_manager/paper_meta/`

这是 dogfood 实验：worker 在用 cursor_manager 框架写关于 cursor_manager 的 paper。

## 通用规则继承

所有 `rules/shared.md` 中的 5 条 hard rule 仍然适用，**不过 HR-2（不动 §5.2）只对论文 B 适用，对论文 C 无关**（论文 C 没有 §5.2 这个 anchor）。

## 论文 C 特有 Hard Rules（HR-A 至 HR-J）

### HR-A. Working title 锁

不要修改 `paper_meta/main.tex` `\title{...}` 内容、`OUTLINE.md` "Working title" 段，**除非** 用 commit message `[BLOCKED-DECISION] propose title change: <new candidate>` 显式 raise。Title 是 paper 的 claim 锚，未经人决策不能动。

### HR-B. Core Claims (C1--C5) 锁

`OUTLINE.md` "Core claims" 列出的 5 条 claim (C1--C5) 是论文骨架。worker 不能：

- 删除任何一条 claim
- 重写任何一条 claim 的核心断言（"discipline > scale", "manager-worker beats debate", "cross-model reduces reward hacking", "four-rule contract suffices", "real submissions"）
- 增加新 claim（除非 raise `[BLOCKED-DECISION] propose new claim C6: <text>`）

可以做的：精炼措辞、补 sub-claim、调整 evidence pointer。

### HR-C. pdflatex 0 content-level warning

每个非 trivial commit 前必须 `pdflatex main && bibtex main && pdflatex main && pdflatex main` 通过且 **0 content-level warning**。

**允许（sty-level cosmetic, 非 content）**：

- `LaTeX Warning: Command \showhyphens has changed.` （NeurIPS sty 加载 `times` package 的已知副作用，无害）
- `Package: infwarerr ... Providing info/warning/error messages` （这是 info 不是 warning，但 `grep -i warning` 会抓到）

**绝不允许（content-level，必须 0）**：

- `LaTeX Warning: There were undefined references.`
- `LaTeX Warning: There were undefined citations.`
- `LaTeX Warning: Reference '...' on page ... undefined.`
- `LaTeX Warning: Citation '...' on page ... undefined.`
- `LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.`
  （4-pass build 后这条仍出现 = bug，必须 fix）
- `Overfull \hbox` / `Underfull \hbox` 超过 5pt （短小可接受，> 5pt 必须修）
- 任何 `LaTeX Error`
- 任何 `Package <name> Error`

如果 commit 引入新的 content-level warning 必须 revert + raise `[BLOCKED-DECISION]`。

### HR-D. Page count 上限

8 page main + 任意 page appendix。如果 main 跑到 8.5+ pages 必须停下来 `[BLOCKED-DECISION] page overflow: <how_much> over, candidate cuts: <list>`。

> 注：venue 选择 deferred until v1（OUTLINE.md decision queue item 2）。NeurIPS workshop 通常 4--6 page；NeurIPS main 8 page；ICLR 9 page。先按 8 page 写，venue 决策时再调整。

### HR-E. Must-cite 验证

`paper_meta/references.bib` 中每个 BibTeX entry 在被 `\cite{}` 之前必须通过 `mgr lit-review paper_c` 验证（Semantic Scholar API 查 `found = true`）。如果 `not_found`：

1. 不要 silently 删 entry
2. raise `[BLOCKED-DECISION] reference <key> not_found on Semantic Scholar; candidate fixes: (a) update title, (b) drop entry, (c) provide manual URL`

OUTLINE.md "Must-cite list" 列出的 5 个种子 reference 是 must-have，不能没有它们。

### HR-F. §5 Case Study 数字 zero-fabrication

`sections/05_case_study.tex` 中**任何**数字（count, percentage, mean, sum, 等）都必须从真实 state 文件查得，且 commit message 中标 `[provenance: <state_file>:<location>]`。被禁止的写法：

- "we observed approximately 100 tick events" （没有 provenance）
- "the cross-model setup detected 95% of injections" （ablation 没真跑）
- "tokens used per accepted commit averaged 8k" （没真 grep meta.json）

允许的写法：

- "we observed 142 tick events [provenance: state/log.jsonl wc -l]"
- "TBD pending ablation run, see Decision Queue item M [BLOCKED-DECISION raised]"

数字稀疏时用 `\cite{NUMBERS-PENDING-AUDIT-FETCH}` 占位 placeholder，编译能过即可。

### HR-G. No emoji

paper 文本和 figure caption 全程不能出现 emoji。code block / appendix 里允许（用于展示 sentinel Lark message 模板等）。

### HR-H. Limitations subsection 必须有

`sections/06_discussion.tex` 必须保留 `\subsection{Limitations}` 且诚实列出至少 5 条。NeurIPS reproducibility checklist 强制要求。

### HR-I. Worktree 边界

worker 可以也只能修改 `tools/cursor_manager/paper_meta/` 下的文件。任何对 `lib/`, `prompts/`, `rules/`, `scripts/`, `docs/`, `state/` 的改动 = 立刻 cancel + escalate。可以读上述目录（你需要它们写 paper）。

例外：可以新增 `paper_meta/figures/`, `paper_meta/CHECKLIST_CN.md`, `paper_meta/COVER_LETTER_DRAFT.md` 等周边文档（与 paper_a 同 pattern）。

### HR-J. Sub-agent 调用机制不能编

§3 / §4 描述 `mgr review-sim`, `mgr lit-review`, `sentinel.py` 的工作机制时必须与 `lib/reviewer_sim.py`, `lib/lit_review.py`, `sentinel.py` 真实代码一致。**严禁** 描述未实装的功能（比如不能说"sentinel 用 LLM 判断 alert 严重度"，因为它实际是 hand-coded heuristic）。

worker 描述 sub-agent 行为前应 read `lib/<module>.py` 确认。

## Worker 可以自主推进的（不动 claim）

按推荐顺序：

1. **首轮 lit-review**：`mgr lit-review paper_c` → 看哪些 reference 需要修，raise BLOCKED 修一个
2. **§2 Related Work** drafting：从 `docs/autoresearch_landscape_2026_05.md` 复用判断 + 把 emergentmind 笔记转成 5 段 prose
3. **§3 Architecture** drafting：从 `README.md` 的 ASCII art 转成 TikZ figure + Algorithm 1 从 `prompts/manager.md` Standard Tick Flow 转写
4. **§4 Discipline** drafting：4 段，每段 1 paragraph，引 `rules/`, `prompts/manager.md`, `lib/reviewer_sim.py`, `sentinel.py`
5. **§1 Introduction** drafting（在 §2--§4 框架稳后再写）
6. **§6 Discussion + §7 Conclusion** drafting
7. **§5 Case Study**：先填 setup 段（HR-F 不需要数字），再 raise `[BLOCKED-DECISION]` 问 manager 是否启动 cross-model ablation 真实验
8. **Abstract**：所有 section 锁后最后写
9. **Polish loops**：reviewer-sim → fix → 再 reviewer-sim

## 当前被 Block 的决策（worker 不可代）

参见 `paper_meta/OUTLINE.md` "Decision queue"，6 个 item：

1. Final title
2. Target venue (NeurIPS workshop / ICLR / ACL demo / multi-venue)
3. Authorship + acknowledgement list
4. Open-source license + repo URL
5. codex profile 间 cost dollar table 是否含（cross-API-model 对比）
6. Reproducibility checklist 不确定项

## 绝对禁区

- 不要碰 `tools/cursor_manager/` 任何 **不在** `paper_meta/` 下的文件
- 不要碰 paper_a / paper_b 的任何东西
- 不要 close 任何 `[BLOCKED-DECISION]` 自己提的
- 不要修改 working title 不 raise BLOCKED
- 不要在 §5 编数字
- 不要用 emoji
- 不要描述未实装的 sub-agent 功能
