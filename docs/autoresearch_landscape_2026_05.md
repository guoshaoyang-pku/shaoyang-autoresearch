# Autoresearch Landscape & Strategy（2026-05）

**Audience**: 自己 + 同事 reviewer（@俞善斌 已知会）
**Status**: 调研完成稿，欢迎 challenge
**Driving question**: PaperOrchestra（Google Cloud AI Research, arxiv 2604.05018, Apr 2026）是否显著好于现有方案？是否更适合写 NeurIPS 论文？我们 `tools/cursor_manager/` 这套要不要换？

---

## 0. TL;DR（30 秒看完）

**结论**: **不需要全盘换**，但有 3 个具体 component 值得借（其中 2 个用 codex 做几乎零成本）。

- PaperOrchestra 的优势集中在 **从零起步 + lit review + plot 自动生成**——这正是我们当前阶段不缺的。我们手里已经是 v1 draft + 决策清单，是 "从 90 到 100"，不是 "从 0 到 1"。
- PaperOrchestra 的核心创新（5-agent decoupled pipeline）确实 SOTA（lit review +50~68%, overall paper +14~38% over AI-Scientist-v2 in human SxS），**但它的评测是 PaperWritingBench (CVPR'25/ICLR'25 reverse-engineered) 不是真投稿**——上限是 ScholarPeer 模拟接收率 84%/81%（vs 人类 86%/94%）。**没有任何系统在 NeurIPS main track 真投稿过且通过**（最接近的是 AI Scientist v2 的 ICLR 2025 workshop，3 投 1 中）。
- 我们目前 manager-worker adversarial loop 的设计（claim discipline + LaTeX 0 warning + git worktree 隔离 + BLOCKED-DECISION escalation）**正是这些系统全都没有的部分**。原因：他们目标是 benchmark/workshop，我们目标是真 submission。
- **Sibyl Research System (前身 FARS)** 是更近的参考：dual-loop + cross-model review (Claude × Codex) + self-healing sentinel + 19-stage pipeline。它的 cross-model adversarial review 跟你"想用 codex 作 adversary"的方向**完全一致**。

**今晚之内可以做的事**（已完成 2026-05）：把我们 cursor_manager 的 in-loop 全部切到 codex CLI，跨 API 模型对抗通过不同 codex profile 实现（manager profile ≠ worker profile ≠ reviewer-sim profile），比 Sibyl 还简洁。**注**：cursor-agent 已彻底从 in-loop 中移除，原因是远程 GPU 跑不了 Cursor、跨平台 token 不可迁移；以下文本中残留的 "cursor-agent" 提及仅作历史记录，对应实现已替换成 "codex profile"。

---

## 1. 我比对了哪些系统

按发布时间倒序。表格里"开源"列 = GitHub 公开可拉。

| 系统 | 时间 | 团队 | 开源 | Stars | 核心架构 | 阶段 |
|---|---|---|---|---|---|---|
| **PaperOrchestra** | 2026-04 | Google Cloud AI Research | ⚠️ 论文未给官方 repo；社区有 [Ar9av/PaperOrchestra](https://github.com/Ar9av/PaperOrchestra)（非官方） | n/a | 5 agent 流水线（Outline → Plot → LitReview → Section Write → Refine） | 从 raw materials 一键到 LaTeX |
| **Sibyl Research System** (前身 FARS) | 2026-03 | Sibyl-Research-Team（匿名 + Anonymous-4427） | ✅ [Sibyl-Research-Team/sibyl-research-system](https://github.com/Sibyl-Research-Team/sibyl-research-system) | 228 | 20+ agent / 19 stage state machine + dual-loop + Claude Code native | 端到端 idea→paper |
| **AI Scientist v2** | 2025-04 | Sakana AI Lab | ✅ [SakanaAI/AI-Scientist-v2](https://github.com/SakanaAI/AI-Scientist-v2) | 5,977 | Progressive agentic tree-search + experiment manager + VLM 视觉反馈 | 端到端，**实测过 ICLR'25 workshop peer review** |
| **Karpathy AutoResearch** | 2025 | Karpathy | ✅ [karpathy/AutoResearch](https://github.com/karpathy/AutoResearch) | 78,564 | Agent 修 `program.md` 而不是 .py，5min 实验 + val_bpb 评估 | 单 GPU ML research，"vibe research" |
| **Agent Laboratory** | 2025 | EMNLP'25 findings | ✅ ([agentlaboratory.github.io](https://agentlaboratory.github.io/)) | n/a | 三阶段：lit review → experimentation → report writing | 端到端，比 baseline 省 84% cost |
| **我们 `tools/cursor_manager`** | 2026-05 | 自研 | (内部) | 0 | 1 manager + 1 worker (adversarial pair) + git worktree + JSONL audit | 真 NeurIPS submission，已跑通 commit 21c951a |

注：FARS 这个名字现在 = Sibyl，原 FARS 仓库已 rename。"FARS"在 2025-2026 还有 [analemma.ai 自己的 blog](https://analemma.ai/blog/introducing-fars/) 介绍另一个商业版本，但我没找到独立开源代码。

---

## 2. 各系统的关键洞察（写给你 + 同事）

### 2.1 PaperOrchestra (Google, Apr 2026)

**5 agent 流水线**（按执行顺序）:

1. **Outline Agent**: raw idea + experiment log → structured outline + plotting roadmap + lit search blueprint
2. **Plotting Agent**: 从 empirical log 生成 statistical plot + 概念图，**用 VLM critic 闭环 critique 迭代**
3. **Literature Review Agent**: hybrid search-and-verify，**Semantic Scholar API 验证 paper 真实存在**，构建 BibTeX pool，drafts Intro + Related Work
4. **Section Writing Agent**: 写 method/experiments/conclusion，遵循 conference template + anonymization
5. **Content Refinement Agent**: simulated peer-review feedback，闭环 in-place revision

**SOTA 数字**（vs AI Scientist v2 + Single Agent baseline，人 SxS 评估）:
- Lit review quality: +50~68% win rate margin
- Overall manuscript: +14~38% win rate margin
- ScholarPeer 模拟接收率: 84% (CVPR), 81% (ICLR), 接近人类 86%/94%
- Citation P0/P1 recall 接近人类（mean 45.7~47.9 vs 人类 ~59）

**真正的创新**:
- **Decoupled** writing 与 experiment pipeline → 不需要绑定特定实验框架
- **Lit review verification chain**: 不只是 LLM 生成 reference，而是 Semantic Scholar API 真验证存在 + 时间 cutoff filter
- **Plot 闭环**: VLM critic 看渲染结果决定是否重画

**它没解决的（坑给我们）**:
- **Citation grounding 不验证 claim 支持**: 只验证 paper 存在，没 check "这篇引用是否支持你这句话"
- **数字保真度无审计**: Section Writing Agent 从 log 提取数字进 table，没自动审计提取正确性 / 单位 / 聚合逻辑
- **对 LLM-judge 过拟合**: refinement loop 用 LLM-as-judge，可能 reward-hack
- **Variance / 多 seed 没跑**: 不知道结果稳不稳
- **没在真 NeurIPS / 真 submission 测过**: PaperWritingBench 是 reverse-engineered benchmark，不是真投稿
- **没 Reviewer-in-the-loop**: Content Refinement 是 simulated peer review，不是真人

**对我们的启发**:
- Lit Review Agent + Semantic Scholar API：**high-ROI, 短期可加**
- Plot 闭环 + VLM critic：中期可加（需 VLM 接入）
- 5-agent decoupled 流水线：长期借鉴的架构思路，但单 paper 不值得全部上

### 2.2 Sibyl Research System / 前 FARS (2026-03)

**最像我们 + codex adversary 想法的系统**。228 stars，活跃开发，2 个 contributor。

**架构关键词**:
- **Claude Code native**: 整个 build on top of Claude Code 的 plugin / agent team / MCP 体系（类似我们用 codex CLI 当底座）
- **20+ agents, 19-stage state machine**: lit search → idea debate → experiment plan → GPU 并行执行 → analysis → outline → section writing → cross review → quality gate
- **6-agent debate** for idea, result analysis, writing：多 agent 投票/辩论决定方向，不让单 agent 拍板
- **Dual-loop**:
  - Inner loop: research iteration (refine hypothesis, re-plan experiments, rewrite paper, pivot)
  - Outer loop: **system self-evolution** —— 从每次 iteration 提取 lesson，分类成 8 类，time-decay 加权，注入回 agent prompts。"the system that runs your research is itself getting better at running research"
- **Multi-model cross-review**: Claude Opus/Sonnet × GPT-5.4 (Codex) **独立 cross-review** ← 这就是你说的 codex adversary 模式！
- **Sentinel watchdog (tmux)**: 进程 crash / idle 自动重启 Claude Code，实现真"unattended autonomous research"
- **Self-healing daemon**: 后台监控 runtime error，自动跑 skill pipeline 修，加 regression test，commit
- **GPU scheduling**: topological sort + dynamic dispatch + experiment_state.json 作 source of truth + file locking
- **MCP servers**: 统一接口（ssh-mcp-server, arxiv-mcp-server）
- **WebUI**: 浏览器监控（live chat, project state, agents, GPUs, token cost, file tree, PDF preview）

**它解决了我们 cursor_manager 的几个真问题**:
- ✅ 进程持久化（Sentinel + tmux）→ 我们用 nohup loop 是简陋版本
- ✅ Cross-model adversarial review → 我们 manager + worker 是同一个模型，覆盖度有限
- ✅ Multi-agent debate → 我们单 manager review，covers 不到的死角无法 cross-check
- ✅ 跨项目 lesson learning → 我们没有

**它的代价（我们要警惕）**:
- ⚠️ `--dangerously-skip-permissions` 是 hard requirement → 对 NeurIPS submission 太危险（agent 可能改 claim 没人监管）
- ⚠️ Quality gate 自动决定继续/pivot/终止 → 没有明确的"hard rule"清单（abstract/intro 不能动）
- ⚠️ "Zero human intervention" → 跟我们 BLOCKED-DECISION 协议哲学相反

**对我们的启发**:
- Sentinel watchdog 思路立刻可借（tmux + auto restart）
- Cross-model review (Codex × Cursor-agent) 立刻可借
- 19-stage pipeline 太重，单论文 ROI 不值
- Self-evolving prompt 是长期方向，但需要先有"哪些 prompt 改进哪些 metric 改善"的 feedback signal——我们目前没有

### 2.3 AI Scientist v2 (Sakana, Apr 2025)

**唯一一个真通过 peer review 的系统**（ICLR 2025 workshop，3 投 1 中，与 ICLR leadership 合作 + UBC IRB approval）。

**v2 vs v1 关键改进**:
- 不再需要 human-authored code template（v1 必须）
- 跨 ML 领域泛化，不需要 domain-specific setup
- **Progressive agentic tree-search (BFTS)** for experiment exploration → experiment manager agent 决定探索方向
- VLM 增强 visual feedback for figure refinement

**对我们的启发**:
- BFTS 是 experiment design 阶段的 SOTA pattern（vs 我们目前 worker 一次只做一件事）
- "通过真 peer review" 这个 milestone 提醒：reviewer-side simulation 必须真实（PaperOrchestra 的 simulated peer review 还差一截）
- ICLR workshop 不是 main track。NeurIPS main track 比 workshop 严，没有任何系统证明能过

**它的局限**:
- v1/v2 都是 idea → paper 端到端，不能接现有 v1 draft
- 没 claim discipline 概念（agent 自己定 abstract）
- BFTS 适合代码实验探索，不适合论文写作 polish

### 2.4 Karpathy AutoResearch (2025)

**不是 paper writing 系统**，而是 ML research 系统（修 training code 跑短实验）。但被 Sibyl 列为重要 inspiration。

**核心创新**: 研究员写 `program.md`（Markdown）而不是直接编辑 `.py`，agent 在 Markdown 描述空间里自主探索 architecture / HP / optimization。

**对我们的启发**: 把 paper "spec" 写成 Markdown，让 worker 不直接编辑 .tex 而是修 `paper_spec.md`，再由模板系统生成 LaTeX——这是个有意思的设计 pattern，**但对我们当前已有 21 页 v1 draft 的场景不适用**。

### 2.5 Agent Laboratory (EMNLP'25)

三阶段（lit review → experimentation → report writing）+ 比 previous methods 省 84% cost。
o1-preview 驱动达到 SOTA ML code 性能。

**对我们的启发**: cost-conscious 设计 → 跟你"cursor 太贵换 codex"的方向一致。

---

## 3. 谁更适合写 NeurIPS 论文（按场景）

| 场景 | 最适合的系统 | 理由 |
|---|---|---|
| **从研究 idea 起步、没草稿** | PaperOrchestra | 5-agent decoupled pipeline + Lit Review + Plot 自动化最强 |
| **从 idea + 数据 起步、需自动跑实验** | Sibyl / AI Scientist v2 | 端到端 + GPU scheduling + experiment exploration |
| **已有 v1 draft、需 polish + claim discipline** | **我们 cursor_manager**（短期） | 唯一一个有 hard rule + claim discipline + BLOCKED-DECISION 协议的，因为别人都不为 submission 设计 |
| **需通过真 peer review** | AI Scientist v2 | 唯一有真实通过记录（workshop level） |
| **跨多个项目持续工作** | Sibyl | 唯一一个有 outer self-evolution loop |
| **只需 lit review** | PaperOrchestra Lit Review Agent（独立用） | Semantic Scholar API + 验证 + 时间 cutoff，最完整 |

**我们当前位置**:
- Paper A 已经有 v1 draft（21 页，main.tex 50KB，包含 7 sections + 8 方程 + Algorithm 1）
- 已有 CHECKLIST_CN, COVER_LETTER_DRAFT, REPRODUCIBILITY_PLAN, RESPONSE_PLAYBOOK 周边文档
- 已有明确 BLOCKED-DECISION 队列
- Manager-worker loop 已经实测产出 commit 21c951a（move inductive bias discussion，0 LaTeX warning）
- Worker branch 上有 25+ 历史 commits 体现真实 paper 工作流

**所以**: PaperOrchestra 不解决我们当前最紧的问题。我们当前最紧的问题是：
1. 让 manager-worker loop 在 codex backend 上稳定跑（你已在做）
2. 加自动 lit review（Semantic Scholar API）确保 reference 没漏 must-cite
3. 加 reviewer simulator（NeurIPS reviewer persona）让 worker 在写 rebuttal 之前自己先扛一遍 reviewer

这 3 件事正好是 PaperOrchestra / Sibyl 各贡献 1 个 pattern。

---

## 4. 推荐的混合架构（codex backend，2026-05 ship）

**底线**: 保留我们 manager-worker 的 adversarial 骨架 + claim discipline + BLOCKED-DECISION 协议，**绝不切换成 PaperOrchestra/Sibyl 的"全自动 zero human"模式**。在骨架基础上，借 3 个具体 component。

```
+------------------------------------------------------------+
|        Cron / Sentinel (every 10 min, tmux + auto-restart) |
|         |                                                   |
|         v                                                   |
|  +-------------------------+                                |
|  |  MANAGER LLM             |   profile = manager_high       |
|  |  (codex --profile        |   (claude-opus thinking-high)  |
|  |   manager_high)          |                                |
|  |  (paranoid reviewer)     |                                |
|  |  reads: rules/*.md       |                                |
|  |  reviews: mgr commits/diff/output                        |
|  +-----------+-------------+                                |
|              |                                              |
|     mgr start <task>                                        |
|              v                                              |
|  +-------------------------+   +-----------------------+    |
|  |  WORKER LLM             |   |  REVIEWER-SIM SUB     |    |
|  |  (codex --profile        |   |  AGENT                |    |
|  |   worker_high → gpt-5.5) |   |  (codex --profile     |    |
|  |  edits .tex / .py        |   |   reviewer_high →     |    |
|  |  enforces hard rules     |   |   claude-opus, NeurIPS|    |
|  +-------+-----+-----+-----+   |   reviewer persona)   |    |
|          |     |     |         |  cross-checks worker's|    |
|  +-------+-----+-----+-----+   |  diff before commit   |    |
|          |     |     |         +-----------+-----------+    |
|          |     |     +-----+               |                |
|          v     v           v               v                |
|   +-----------+ +----------------+ +---------------------+  |
|   | LIT REV   | | PLOT/FIG SUB   | | LATEX VERIFY SUB    |  |
|   | SUB AGENT | | AGENT (matplot | | AGENT (pdflatex *4  |  |
|   | (Sem Sch  | | + VLM critic   | | + 0 warning enforce |  |
|   | API verify| | optional v2)   | | + 4-pass check)     |  |
|   | + bib gen)| +----------------+ +---------------------+  |
|   +-----------+                                             |
+------------------------------------------------------------+

           git worktree paper/...-worker-paper_a
           (commits stay isolated, never auto-pushed)
```

### 4.1 立刻 ship 的 3 个 sub-agent

#### A. Lit Review Sub-Agent（borrow PaperOrchestra）

**作用**: 在 worker 准备 commit 前，对 diff 中新增的引用做 Semantic Scholar API 真实性验证 + 时间 cutoff filter；对论文未引用但 Semantic Scholar 给出高 relevance 的 must-cite 给出 warning。

**实现路径**: 一个独立的 codex profile + skill：
- `tools/cursor_manager/sub_agents/lit_review.py`: Semantic Scholar API client（已有公开 endpoint, 不需要 key for 基础查询）
- `tools/cursor_manager/skills/lit_review/SKILL.md`: codex skill 定义
- 集成点: 在 `mgr start` 提示 worker 任务时，如果任务涉及 .tex 引用变动，先调一次 lit_review sub-agent
- 不阻塞主流：sub-agent 输出写到 `state/lit_review/<run_id>.json`，manager review 时读

**ROI**: 高。Semantic Scholar API 免费，1 个晚上能 ship 完。直接堵 reviewer 最常喷的 "你没引 must-cite" 漏洞。

#### B. Reviewer Simulator Sub-Agent（borrow Sibyl 6-agent debate + AI Scientist 真 peer review 思路）

**作用**: worker 完成一段 commit 后，由 manager 调一个 NeurIPS reviewer persona 的 sub-agent 做 1-pass review，输出 score + concern list。**用不同 codex profile**（worker = `worker_high` → gpt-5.5；reviewer-sim = `reviewer_high` → claude-opus-4-7-thinking-high）。这就是 codex-only 路径下"跨 API 模型对抗"的具象化。

**实现路径**:
- `tools/cursor_manager/prompts/reviewer_sim_neurips.md`: NeurIPS reviewer persona（重点：technical soundness, novelty positioning, claim grounding, missing experiments）
- `mgr review-sim <worker> --against HEAD`: 单独命令，调 codex (--profile reviewer_high) + reviewer prompt + worker diff
- 输出: `state/reviewer_sim/<wid>/<run_id>.md`，结构化 score + concern list
- Manager 在 review 时，把 reviewer-sim 的 concern 当 evidence。如果 reviewer-sim 说 "这个 claim 没 evidence"，manager 应该 cancel_restart 或 escalate

**ROI**: 高。它实现了真正的 cross-model adversarial review，比我们当前同模型 manager-worker 多一层防线。

#### C. Sentinel Watchdog（borrow Sibyl）

**作用**: 监控 nohup loop / cron tick；如果连续 N 次 escalation 同因（比如 24h 都报"codex exec 退出 1"）就暂停循环 + 通过飞书 IM 通知人。

**实现路径**:
- `tools/cursor_manager/sentinel.py`: 读 audit.jsonl + escalations.jsonl，识别同因连续失败模式
- 触发后调 `lark-im` skill 发飞书消息（注：lark skill 已经在你 ~/.claude/skills/ 下）
- Cron 间隔执行，独立于 tick.sh

**ROI**: 中等。早期 cursor-agent 24h 持续失败没人发现，证明这个 sub-agent 必要。in-loop 切到 codex-only 后失败模式更可预测，但 watchdog 仍是基本卫生设施。

### 4.2 中长期借鉴

- **VLM critic for plot generation** (PaperOrchestra Plot Agent)：等我们有需要重画的 figure 时再做
- **Multi-agent debate for important claims** (Sibyl 6-agent debate)：当我们有重大 claim 争议时再开启（如 "widens with scale" 这种）
- **Self-evolving prompts** (Sibyl outer loop)：需要积累足够多 paper 的 lesson 才有信号，单论文不值
- **GPU scheduling for experiment** (Sibyl GPU scheduler)：当我们启动 P0 Hybrid ICL/IWL 实验时再考虑（占卡管理 + topological sort）

### 4.3 绝不照搬的（warning）

| 不要做 | 原因 |
|---|---|
| ❌ `--dangerously-skip-permissions` (Sibyl 必备) | NeurIPS submission 不能让 agent 无监督改 claim |
| ❌ "Zero human intervention" 哲学 | 跟我们 BLOCKED-DECISION 协议根本冲突 |
| ❌ 5-20 agent 流水线全部上 | 单论文协调成本 > 收益；agent 越多 bug 越多 |
| ❌ Self-evolving prompt | 缺 reward signal；可能 reward-hack |
| ❌ 完全替换我们 cursor_manager 骨架 | 已实测产出 commit 21c951a 的可行性，切换 = 自寻烦恼 |

---

## 5. 给 @俞善斌 的讨论问题

如果他要 review，我建议从这 5 个问题切入：

1. **NeurIPS submission ≠ paper benchmark**：现有所有系统（PaperOrchestra/Sibyl/AI Scientist v2）的评测都是 reverse-engineered benchmark 或 workshop。真 main track 的失败模式（claim 漂移、数字漂移、引用漂移）这些系统都没有针对设计。我们 cursor_manager 的 hard rule + BLOCKED-DECISION 是不是足够？还是太严？
2. **Cross-model adversarial review** 是不是真的更鲁棒？（直觉是 yes，但缺定量证据。Sibyl 用 Claude × Codex 但没 ablation 说"如果都用 Claude 会差多少"）
3. **Lit Review 的 Semantic Scholar 验证** 上限在哪？它只验证 paper 存在，不验证 claim 支持。要不要再加一个 claim-evidence linker（GROBID + retrieval）？
4. **Plot 自动生成是不是当前必要**？我们 paper A 的 figure 都是 generate_figures.py 半手工生成的，质量已经 OK。PaperOrchestra Plot Agent 只在 figure 真要重画时收益高，单论文场景 ROI 是不是太低？
5. **Sentinel watchdog + 飞书通知** 是不是优先级 P0？早期 cursor-agent 24h 持续失败没人发现的教训告诉我们这个事下次还会发生。

---

## 6. 落地排期（草案，等你 ack 再 ship）

| 阶段 | 周期 | Deliverable |
|---|---|---|
| **0. 已完成** | done | manager-worker loop + commit 21c951a + codex CLI 调通 + codex backend recipe |
| **1. codex 化主链** | 1-2 day（已完成）| worker / manager / reviewer-sim 全切 codex（不同 profile 之间对抗）；in-loop 中 cursor-agent 已彻底删除 |
| **2. Reviewer Simulator sub-agent** | 1 day | `mgr review-sim` 命令 + NeurIPS reviewer prompt + 输出结构化 concern list |
| **3. Lit Review sub-agent** | 1 day | Semantic Scholar API client + 集成 mgr start |
| **4. Sentinel watchdog + lark 通知** | 0.5 day | sentinel.py + lark-im skill 调用 |
| **5. (optional) Plot agent** | 1-2 day | 仅当 paper A 需要重画 figure 时启动 |
| **6. (long) Multi-agent debate for claim conflicts** | 视情况 | 仅当遇到 "widens with scale" 这种重大争议时启动 |

**总投入**: 3-4 个工作日 ship 出 1+2+3+4，构成"我们 cursor_manager v2 = 借用 3 个 PaperOrchestra/Sibyl pattern 的 NeurIPS-submission-grade 版本"。

---

## 7. 一句话答复你的原问题

> PaperOrchestra 是否最好？是否显著好于之前的？

- **学术 benchmark 上**: 是。它在 PaperWritingBench 上比 AI Scientist v2 +14~38%（overall paper），lit review +50~68%，是当前 SOTA。
- **真 NeurIPS submission 上**: **没有任何系统证明过自己**。PaperOrchestra 没在真投稿场景测过；唯一接近的 AI Scientist v2 通过的是 ICLR workshop（不是 main track）。
- **对我们当前阶段（paper A 已有 v1 draft + 决策清单）**: PaperOrchestra **不是最适合**。我们已经超过了它的最佳起点（unstructured raw materials），需要的是 polishing + claim 守纪律 + reviewer adversarial review，这些我们手里的 cursor_manager 已具备 partial 能力，再借 3 个组件就完整。
- **战略路径**: 不换骨架，借 3 件（Lit Review / Reviewer Sim / Sentinel）+ 走 codex 化主链。3-4 个工作日完成。

---

## 附录 A：参考链接

- PaperOrchestra: <https://arxiv.org/abs/2604.05018> · <https://yiwen-song.github.io/paper_orchestra/>
- Sibyl Research System (前 FARS): <https://github.com/Sibyl-Research-Team/sibyl-research-system>
- AI Scientist v2: <https://github.com/SakanaAI/AI-Scientist-v2> · <https://sakana.ai/ai-scientist-first-publication/>
- Karpathy AutoResearch: <https://github.com/karpathy/AutoResearch>
- Agent Laboratory: <https://agentlaboratory.github.io/> · ACL Anthology 2025 findings-emnlp.320
- PaperWritingBench (eval bench): 含在 PaperOrchestra 论文，200 papers (CVPR'25 100 + ICLR'25 100) reverse-engineered
- FML-Bench (ICLR'26 under-review eval bench): 8 fundamental ML research problems, 5 metrics
- Semantic Scholar API: <https://api.semanticscholar.org/> （免费，基础查询不需要 key）
- 我们的 codex backend recipe: `tools/cursor_manager/docs/codex_backend_recipe.md`

## 附录 B：调研覆盖度声明

调研于 2026-05-03 进行。已读：PaperOrchestra abstract + emergentmind 详细分析（含 limitations + knowledge gaps + practical applications + glossary）；Sibyl Research System README + recent commits + 19-stage pipeline 描述；AI Scientist v2 sakana 官方介绍 + GitHub README；Karpathy AutoResearch 描述；Agent Laboratory abstract。未读：PaperOrchestra 完整 PDF（只读 emergentmind summary）、AI Scientist v2 完整 paper PDF、Sibyl 实际代码（只读 README）。这些细节在落地 sub-agent 时再深读。
