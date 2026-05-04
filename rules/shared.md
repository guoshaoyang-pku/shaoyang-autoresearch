# Hard Rules（Worker 必须遵守，违反即 cancel + 重启）

来源：`~/cursor-handoff/LIULAB_PAPERS_HANDOFF.md` §0

1. **不要改任何 claim-level 措辞**，除非用户在 worker prompt 里明确授权。
2. **不要动 §5.2 (sec:scaling-jump)** 的内容（仅论文 B；论文 A 无此节）。
3. **每轮改完必须 `pdflatex+bibtex+pdflatex` 验证 0 warning**，不通过就 revert。
4. **所有数字 claim 必须 `grep` 回 main.tex 验证**，不能凭记忆写。
5. **遇到决策分歧（发表策略 / 实验方向 / claim 措辞），不要自己拍板**——commit message 带 `[BLOCKED-DECISION]` 前缀，描述清楚 trade-off，Manager 会升级给人。

# 行为约束

- **每个 task 一个 commit**，commit message 用 `paper(neurips2026): <action>` 格式。
- **不要 force push、不要 rebase、不要删 branch**。
- **不要修改 git config、不要碰 `.git/hooks/`**。
- **遇到不确定的事**，宁可写 `[BLOCKED-DECISION]` commit 也不要硬猜。
- **每次 run 结束前必须 `git status` 干净**（要么 commit、要么 stash、要么 revert，不留脏树）。
