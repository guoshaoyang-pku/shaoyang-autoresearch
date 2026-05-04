# cursor_manager — Adversarial Multi-Agent Framework for Submission-Grade Paper Writing

> **Paper (NeurIPS 2026 submission, dogfood)**: see [`paper_meta/main.pdf`](paper_meta/main.pdf) for the rendered system paper.
> Source: [`paper_meta/`](paper_meta/) (LaTeX) | [`paper_meta/OUTLINE.md`](paper_meta/OUTLINE.md) (working outline) | [`paper_meta/references.bib`](paper_meta/references.bib) (lit-review-verified bibliography).
> **License**: [MIT](LICENSE)

A long-running LLM **manager** with a paranoid-reviewer persona supervises one or more **worker** LLMs writing actual conference papers, mediated by a single Python CLI (`mgr`) with thirteen atomic operations and four discipline sub-agents (reviewer-sim, lit-review, sentinel, codex backend). Cron-kicked every 5 minutes; persistent codex `session id` resume. **Codex-only**: manager, worker, and reviewer-sim all use the codex CLI; **cross-API-model adversarial** review comes from *different* codex profiles (e.g. Claude-Opus vs GPT-5.5). **Optional local proxy** (`proxy/codex_proxy.py`) translates Codex Responses API calls to your org's Chat Completions endpoint. The Cursor IDE is for humans only — no `cursor-agent` in the loop.

## Secrets & local proxy

- **`keys.json`** (gitignored): copy from [`keys.example.json`](keys.example.json). Fill `codex_proxy.*` for the shim, and optionally `semantic_scholar_api_key` (also overridable in `config.toml`).
- **`proxy/`**: [`codex_proxy.py`](proxy/codex_proxy.py) listens on `localhost:4002` by default; [`start_proxy.sh`](proxy/start_proxy.sh) launches it. Configure codex with `base_url = "http://127.0.0.1:4002"` — see [`proxy/codex_config.example.toml`](proxy/codex_config.example.toml).
- **Never commit** real API keys; use env vars `CODEX_PROXY_UPSTREAM_URL` and `CODEX_PROXY_API_KEY` if you prefer not to use `keys.json`.

## 30-second quick-start

```bash
git clone https://github.com/guoshaoyang-pku/shaoyang-autoresearch.git
cd shaoyang-autoresearch
cp keys.example.json keys.json              # fill upstream API key + optional Semantic Scholar key
cp config.example.toml config.toml          # edit local_repo_path + codex profiles
./proxy/start_proxy.sh                      # local Responses→ChatCompletions shim (see proxy/README.md)
./bootstrap.sh                              # create worker worktrees + branches
./kickoff.sh                                # first manager session (records session-id)
bash scripts/install_launchd.sh             # macOS: use cron/systemd on Linux
tail -f state/log.jsonl                     # watch the manager wake every 5 minutes
```

### `config.toml`: `[reviewer]` is the manager LLM (not `[manager]`)

- **Manager codex process** (`tick.sh` / `kickoff.sh` → `_invoke_manager.py`) reads **`[reviewer]`** for the in-loop manager: `backend`, `cli_path`, `profile`, `timeout_seconds`, `prompt_path`. That is the paranoid-reviewer persona’s LLM settings.
- **`[manager]` has no `backend` field** and does **not** choose the manager’s model. It only holds **orchestration / side-effect knobs**: `poll_interval_seconds`, `max_run_seconds`, `mode`, `log_path`, `escalations_path`, `notify_macos`, etc.
- **Why the name `[reviewer]`?** Historical: the manager’s persona is literally a skeptical reviewer; the TOML section kept that name. When docs say “manager profile”, they mean **`[reviewer].profile`** in `config.toml`, mapped to `~/.codex/config.toml` `[profiles.*]`.

To run the full self-test suite (13 hermetic checks, no network, no LLM required):

```bash
bash scripts/smoke_test_sub_agents.sh       # 13/13 PASS expected
```

To cite (bibtex):

```bibtex
@article{cursormanager2026,
  title  = {Turning Tokens into Research: An Adversarial Multi-Agent Framework
            for Submission-Grade Paper Writing under Unbounded Token Budgets},
  author = {(anonymized for review)},
  year   = {2026},
  note   = {NeurIPS 2026 submission. System and audit logs released at this repository.},
}
```

---

## 默认配置 + GPU 远程部署

默认配置只启用 CA 论文 worker，避免在当前阶段启动过多分支或让文件散落到多个 worktree。给 `GPU maintainers` 使用时，先复制 `config.example.toml` 为 `config.toml`，把 `[worker].local_repo_path` 改成 GPU 机器上的 shaoyang-autoresearch checkout 路径。**前置条件唯一是 codex CLI**（`codex --version` 能跑，`~/.codex/config.toml` 已配好对应 profile）。Cursor 在远端不可用也不需要。

## 核心理念

- **Manager 是 LLM**（codex `--profile manager_high` → claude-opus-4-7-thinking-high），不是 if/else — **在 `config.toml` 里对应 `[reviewer]` 段，不是 `[manager]`**
- **Manager 是怀疑论者**：默认假设 worker 找捷径、改 claim、跳验证
- **Manager 跨 tick 持久化记忆**：`codex exec resume <session-id>`；cron 每 5 分钟 kick 一次它
- **Worker 也是 codex** 的另一个 profile（`worker_high` → gpt-5.5-2026-04-24-xhigh），跑在 git worktree 里隔离不污染主分支
- **Worker 跨 fork 也持久化记忆**：自动捕获 `session id` 写到 `state/workers/<id>/codex_session.json`
- **Cross-API-model adversarial 由 codex profile 控制**：manager / worker / reviewer-sim 各自的 `[*].profile` 必须不同，否则同族模型容易互相放过 claim 缺陷
- **完全本地**：worker 和 manager 都跑本机 codex 子进程；commit 留 worktree 不 push remote

## 架构图（架构 Y, codex-only）

```
launchd / cron（每 5 分钟，永不停）
    │
    ▼ kicks
┌──────────────────────────────────────────────────────────────────┐
│ tick.sh                                                          │
│   ↓ reads state/manager_chats.json (worker → codex session_id)   │
│   ↓ delegates to                                                 │
│ scripts/_invoke_manager.py tick                                  │
│   ↓ reads config.toml [reviewer] (codex-only, hard-checked)      │
│   ↓ runs                                                         │
│   └─ codex exec resume <session_id> --color never \              │
│        -C <workspace> "tick now" < /dev/null                     │
│                              │                                   │
│             ┌────────────────▼──────────────────────┐            │
│             │ Manager LLM (codex --profile manager)  │            │
│             │ Persona: paranoid NeurIPS reviewer     │            │
│             │ Tools: mgr CLI                         │            │
│             │   - status / commits / diff / output   │            │
│             │   - rules / start / cancel / escalate  │            │
│             │   - review-sim / lit-review (v2 sub-   │            │
│             │     agents, on demand)                 │            │
│             │ Output: 最后一行 JSON audit            │            │
│             └────────────────┬──────────────────────┘            │
│                              │ fork subprocess                   │
│                              ▼                                   │
│             ┌─────────────────────────────────────┐              │
│             │ Worker LLM (codex --profile worker) │              │
│             │ cwd = ~/.cursor/worktrees/...       │              │
│             │ branch = paper/...-worker-<id>      │              │
│             │ commit 留 worktree，不 push         │              │
│             └─────────────────────────────────────┘              │
└──────────────────────────────────────────────────────────────────┘
```

上图里 “reads `[reviewer]`” 即 **manager LLM** 的 codex 配置；不要到 `[manager]` 段里去找 `backend` / `profile`。

## 目录

```

├── README.md                    # 本文件
├── LICENSE                      # MIT
├── keys.example.json            # secret template (copy → keys.json)
├── config.example.toml          # 配置模板（codex-only）
│
├── proxy/
│   ├── codex_proxy.py           # Responses API → Chat Completions upstream
│   ├── start_proxy.sh           # launch proxy + health check
│   └── codex_config.example.toml
│
├── mgr                          # ★ Manager LLM 唯一工具集（CLI）
├── tick.sh                      # ★ launchd 入口（每 5min 跑一次）
├── kickoff.sh                   # ★ 第一次启动（创建 codex sessions）
├── bootstrap.sh                 # 创建 worker worktree + branch
│
├── lib/
│   ├── codex_worker.py          # ★ 本机 codex 子进程管理（in-loop 唯一 worker 后端）
│   ├── secrets.py               # optional keys.json loader
│   ├── reviewer_sim.py          # ★ NeurIPS reviewer-sim sub-agent（codex-only）
│   ├── lit_review.py            # ★ Semantic Scholar lit-review sub-agent
│   ├── lark_notify.py           # ★ Lark notification helper for sentinel
│   └── state.py                 # JSON/JSONL 持久化 + 文件锁 + WorkerRunInfo
│
├── sentinel.py                  # ★ Watchdog 守护进程（mgr sentinel-tick）
│
├── prompts/
│   ├── manager.md               # Manager Persona + tick 流程 + 输出协议
│   ├── worker_paper_a.md        # Worker A 初始 prompt
│   ├── worker_paper_b.md        # Worker B 初始 prompt
│   ├── worker_paper_c.md        # Worker C dogfood 初始 prompt
│   ├── reviewer_sim_neurips.md  # ★ NeurIPS reviewer-sim persona
│   └── reviewer.md              # （legacy，保留作历史参考）
│
├── rules/
│   ├── shared.md                # 5 条 absolute hard rules
│   ├── paper_a.md               # 论文 A 专属 + blocked 决策
│   ├── paper_b.md               # 论文 B 专属 + §5.2 死线
│   └── paper_c.md               # dogfood 论文专属 hard rules
│
├── scripts/
│   ├── install_launchd.sh       # 装 macOS launchd 自动调度
│   ├── _invoke_manager.py       # ★ tick.sh / kickoff.sh 的 codex dispatcher
│   └── smoke_test_sub_agents.sh # 13/13 hermetic checks
│
├── docs/
│   ├── codex_backend_recipe.md  # codex CLI 安装 + profile 配置 + 已知坑
│   ├── sub_agents_contract.md   # 4 个 sub-agent 模块的 API spec
│   └── autoresearch_landscape_2026_05.md  # 调研对比 / 借鉴 / 设计取舍
│
└── state/                       # gitignore，运行时
    ├── agents.json              # registry: last_processed_run_id, etc.
    ├── manager_chats.json       # worker_id → {backend: codex, session_id, profile}
    ├── tick.log
    ├── manager_audits/          # 每个 worker 一个 .jsonl
    ├── workers/                 # ★ 每个 worker 一个目录
    │   └── paper_a/
    │       ├── codex_session.json   # codex session id（持久化）
    │       ├── worktree_path
    │       ├── branch
    │       ├── history.jsonl
    │       └── last_run/
    │           ├── pid
    │           ├── meta.json
    │           ├── output.log
    │           ├── prompt.txt
    │           └── exit_code
    ├── log.jsonl                # mgr 命令的事件流
    └── escalations.jsonl        # 待人决策的事件
```

## 前置条件

| 依赖 | 检查 | 说明 |
|---|---|---|
| Python ≥ 3.11 | `python3 --version` | stdlib `tomllib`，零依赖 |
| `codex` CLI | `codex --version` | 全部 in-loop LLM 都走它（参见 `docs/codex_backend_recipe.md`） |
| `~/.codex/config.toml` | 配好至少 1 个 profile | 推荐 manager / worker / reviewer-sim 各 1 个 profile，对应不同底层 API 模型 |
| Git repo + base branch | shaoyang-autoresearch repo + `paper/neurips2026-draft` 分支 | bootstrap.sh 从这分叉出 worker branch |
| macOS（可选） | osascript / launchd | 本机自动 tick；Linux GPU 机可用 cron/systemd 手动替代 |

**不需要**：cursor-agent CLI（已彻底从 in-loop 中移除）、Cursor API Key、GitHub repo（worker 跑本机）、外网（除了 codex 自己走的 API 代理）

## 完整上手流程

```bash
# 1. 配置（已在仓库根目录）
cp config.example.toml config.toml
# 编辑 config.toml:
#   [worker]   local_repo_path = "/path/to/shaoyang-autoresearch"
#   [worker]   worktree_base = "paper/neurips2026-draft"
#   # manager LLM = [reviewer] 段（不是 [manager]）:
#   [reviewer] profile = "manager_high"
#   [worker]   profile = "worker_high"          # ≠ manager_high 才有跨 API 模型对抗
#   [reviewer_sim] profile = "reviewer_high"    # ≠ worker profile

# 2. Bootstrap：创建 worker worktree + branch
./bootstrap.sh
# → ~/.cursor/worktrees/<repo>/<wid>/ 创建好
# → state/workers/<wid>/{worktree_path, branch} 写入

# 3. Kickoff：创建 codex sessions（注入 manager persona + hard rules）
./kickoff.sh
# → state/manager_chats.json 写入 {worker_id: {backend: "codex", session_id, profile}}

# 4. 手动 tick 一次测试
./tick.sh
# → state/manager_audits/<wid>.jsonl 应有一行 audit JSON

# 5. macOS 可装 launchd 每 5min 自动 tick
./scripts/install_launchd.sh

# 6. 监控
tail -f state/tick.log
tail -f state/manager_audits/paper_a.jsonl
./mgr audit paper_a
./mgr escalations
```

Linux GPU 机建议先不用常驻调度，手动执行：

```bash
./tick.sh paper_a
```

确认 manager 行为稳定后，再用 cron/systemd 每 5-10 分钟调用一次。

## codex CLI 在远端的部署

`codex` 是平台相关的预编译二进制（Linux x64 或 Linux arm64 等）。把发行版拷到远端机器、解压、加进 `PATH`，再写 `~/.codex/config.toml`（profile + provider 指向你的 API 代理）即可。具体流程见 `docs/codex_backend_recipe.md`。

**关于 cursor-agent**：本仓库已不再支持把 `cursor-agent` 作为 in-loop LLM 后端。原因是远程 GPU 机器跑不了 Cursor，且即使能跑，跨平台 Keychain token 也无法迁移。Cursor IDE 仍然是人类操作员（你）的入口，但所有自动化路径都走 codex。

## 已验证（live 模式）

```
✓ bootstrap：worktree + branch 创建成功
  ~/.cursor/worktrees/shaoyang-autoresearch/paper_a  [paper/neurips2026-draft-worker-paper_a]

✓ mgr start：fork codex 子进程成功
  exit_code 0, status: RUNNING → FINISHED

✓ session_id 自动捕获到 codex_session.json
  session id: <uuid> 从 stdout body 解析，写入 state/workers/<worker>/codex_session.json

✓ 第二次 fork 用 codex exec resume 续上记忆
  codex tokens used 行可以观察到上下文确实复用
```

## Worker 工作模型

每次 `mgr start` 时：

1. fork 一个 `codex exec resume <session-id> --color never -C <worktree> "<prompt>" < /dev/null`
   - 首次（无 session-id）改用 `codex exec --skip-git-repo-check --color never --profile <profile> -C <worktree> "<prompt>" < /dev/null`
2. wrapper 进程把 stdout 写到 `last_run/output.log`
3. codex 退出后，wrapper 写 `last_run/exit_code`
4. 下次 `mgr status` 调用 `get_run()` 检测 PID 已死 → 解析 output.log → 写入：
   - `meta.json.status = FINISHED`
   - `meta.json.captured_session_id = ...`
   - `codex_session.json`（首次捕获）
5. 如果 worker 还没跑完就 `mgr cancel` → SIGTERM 整个 process group

> **Codex stdin 陷阱**：codex 不重定向 stdin 时会一直挂着等输入。`< /dev/null` 是必须的；wrapper script 自动加。详见 `docs/codex_backend_recipe.md`。

## Manager 是怎么思考的（一次 tick）

```
被 kick: "tick now (2026-05-01T20:30:00+0800)"
↓
[读自己的 codex 历史，回忆上次决策]
↓
mgr status paper_a
→ {worktree_dirty: false, current_run: {status: FINISHED, ...}, last_processed_run_id: <旧>, ...}
↓
[current_run.id != last_processed_run_id → 是新 run，要 review]
↓
mgr commits paper_a -n 5
→ [{hash, subject, body}, ...]
↓
[没看到 [BLOCKED-DECISION]，继续 diff]
↓
mgr diff paper_a
→ ... 30 行 diff，看到改了 sections/05_scaling_connection.tex 等 ...
↓
mgr rules paper_a → 复习 hard rules
↓
[逐条对照]
↓
mgr output paper_a → 看 worker 的 DONE/NEXT 行
↓
mgr start paper_a -p "继续推进 ..."
↓
mgr mark-processed paper_a --run-id <id> --verdict continue --summary "..."
↓
[输出最后一行 JSON]
{"tick_at":"...","worker":"paper_a","action":"continue","summary":"...","run_id":"..."}
```

## 设计取舍：为什么 codex-only

| 维度 | cursor-agent (in-loop) | codex (in-loop) ✅ |
|---|---|---|
| Linux GPU 远端 | ❌ 跨平台 token 不可迁移；只有 macOS arm64 + Linux x64 二进制 | ✅ 静态二进制，scp 即可 |
| Profile 选模型 | 只能选 `--model <slug>`，slug 集合固定 | ✅ `--profile <key>` → `~/.codex/config.toml` 任意 provider/model |
| 跨 API 模型对抗 | 双 backend 才能跨族（cursor-agent ↔ codex） | ✅ 两个 codex profile 即可（manager profile ≠ worker profile） |
| Stdin/headless | `-p` mode；偶尔挂 | `< /dev/null` 必须；挂的根因明确 |
| 成本 | 较贵 | 通过自家 API 代理 → 任意 provider |
| 远程跑 manager | ❌ Cursor 不能在远端 | ✅ 同一个 codex 调度逻辑 |

**结论**：远程 GPU 机器只能跑 codex；为了 in-loop 的 manager / worker 双方都能在远端跑，且 cross-API-model 对抗仍然能成立，最简单的设计就是 in-loop 全 codex、不同 profile 之间对抗。本仓库已按此方向把 `cursor-agent` 全部从 lib/ scripts/ docs/ 中移除。

## 已知限制

- **电脑必须开机**（不能休眠 / 不能关）—— launchd / cron 才能 5 分钟一次 kick；如果跑在 GPU 机器，开 24/7 即可
- **Worker 并发上限**：受本机 CPU/RAM 限制，建议同时 ≤ 2 个 worker
- **manager 跨 tick 持久化端到端未在线上跑过完整一周**：codex `exec resume <session-id>` 已 smoke-tested（<your-gpu-host>, 2026-05-02）；`scripts/_invoke_manager.py` 13/13 hermetic checks pass，但完整 manager → worker → manager 闭环的真实环境运行还在累积数据
- **codex `exec resume` 仅 v0.128.0+**：老 codex 不支持，会在第一个 tick 失败并写 escalation
- **没有 SSE stream**：用 `mgr output` 看 worker 的 stdout 末尾代替

## 调试 cheatsheet

```bash
# 看 manager 最近 tick audit
./mgr audit paper_a

# 看 mgr 命令事件流
./mgr log -n 30 --worker paper_a

# 看 escalation
./mgr escalations

# 看 tick.sh log
tail -f state/tick.log

# 看 worker 当前/最近 run 的输出
./mgr output paper_a

# 手动 tick 一次
./tick.sh paper_a

# 看 worker worktree git 状态
cd ~/.cursor/worktrees/shaoyang-autoresearch/paper_a && git log --oneline -10

# 强制重建 worker worktree（保留 codex_session.json）
./bootstrap.sh --force paper_a

# 强制重建 manager codex session（chat 太长清掉重来）
./kickoff.sh --reset paper_a

# 手动给 worker 发指令（绕过 manager，调试用）
./mgr start paper_a -p "你的 prompt"

# 清掉 worker session_id（强制下次 fork 新 session）
rm state/workers/paper_a/codex_session.json

# 把 worker 的 commits merge 回主分支
cd /path/to/shaoyang-autoresearch
git checkout paper/neurips2026-draft
git merge --no-ff paper/neurips2026-draft-worker-paper_a
```

## Autoresearch sub-agents (v2, 2026-05+)

在 `manager + worker` 双 agent 骨架基础上加了 4 个 sub-agent，按需调用，**不替换主链**。设计文档：

- `docs/autoresearch_landscape_2026_05.md` —— 调研对比 PaperOrchestra / Sibyl(FARS) / AI Scientist v2 / Karpathy AutoResearch / Agent Lab，论证为什么是这 4 个
- `docs/sub_agents_contract.md` —— 4 个模块的 API spec、文件路径约定、self-test 要求

| Sub-agent | 来源参考 | 命令 | 输出 |
|---|---|---|---|
| **Reviewer Simulator** | PaperOrchestra Content Refinement + Sibyl 6-agent debate + AI Scientist real peer review | `mgr review-sim <wid>` | `state/reviewer_sim/<wid>/<run_id>.md`（NeurIPS score + concerns） |
| **Lit Review** | PaperOrchestra Lit Review Agent + Semantic Scholar API | `mgr lit-review <wid>` | `state/lit_review/<wid>/<run_id>.{json,md}`（citation 验证 + must-cite 推荐） |
| **Sentinel watchdog** | Sibyl Sentinel + Lark IM | `mgr sentinel-tick` 或 cron 直调 `python sentinel.py` | 触发时给 Lark 发 markdown 警报；`state/sentinel/last_tick.json` 记 dedupe |
| **Codex backend** | docs/codex_backend_recipe.md | 唯一 in-loop 后端（不可关、不可换） | `state/workers/<wid>/codex_session.json` 持久化 session id |

每个 sub-agent **必须**通过 self-test 才能集成：

```bash
bash scripts/smoke_test_sub_agents.sh
# 期望末尾输出 "smoke_test: ALL PASS"
```

**Cross-API-model adversarial 推荐配置**（同族模型 self-review 容易互相放过 claim 缺陷，参考 Sibyl 的 Claude × Codex 思路；codex-only 把这套结构落到不同 codex profile 上）。三层 LLM 用三个 profile，对应不同底层 API 模型：

```toml
[reviewer]                   # manager LLM（每 5min 被 tick 一次）
backend = "codex"
profile = "manager_high"     # ~/.codex/config.toml 里映射到 claude-opus-4-7-thinking-high
timeout_seconds = 300

[worker]                     # worker LLM（manager fork 出来执行任务）
backend = "codex"
profile = "worker_high"      # 映射到 gpt-5.5-2026-04-24-xhigh

[reviewer_sim]               # reviewer-sim LLM（NeurIPS reviewer persona, on demand）
backend = "codex"
profile = "reviewer_high"    # 同 manager 走 claude-opus；关键是 ≠ worker_high
```

重点是：**worker profile ≠ reviewer-sim profile**（避免 claim-bias 互相放过）。Manager 选哪族模型都行，但 reviewer-sim 跟 worker 不同族能放大对抗信号。

## 不打算做的事

- 不做 worker-worker 通信（git commit 即通信）
- 不做 GUI（CLI + log + macOS 通知 + Lark 通知 够用）
- 不自动 merge worker commits（人决策何时合并）
- 不做 cost tracking GUI（meta.json 里有 usage，自己 tail 即可）
- 不做 self-evolving prompt（Sibyl 有，但单 paper 缺 reward signal，ROI 不值）
- 不做 fully-autonomous "zero human intervention"（NeurIPS submission 不能这样）
- 不再做 cursor-agent 后端（远程 GPU 跑不了，跨平台 token 不可迁移；in-loop 全 codex）
