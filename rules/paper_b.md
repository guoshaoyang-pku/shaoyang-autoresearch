# 论文 B (LLM 几何, f4f72a8f) Worker 专属规则

仓库子目录：`scaling law toy/paper_neurips2026/`

## 当前被 Block 的核心决策（worker 不可代）

**A/B/C claim-softening level**（牵动 8-9 处 loci）：
- A 保守：保留 §5.2 + 加 hedging
- **B 中度（task 推荐）**：§5.2 降级 Appendix + 删 §6.6 line 90 + §7 line 10 改 "consistent with"
- C 激进：删 §5.2 整节

**额外 blocked**：
- Abstract 末句措辞（保留 falsified / 换 P1/P2 / 删除）
- 是否需要中间里程碑标签
- §1 line 43 "phase jump" 老措辞

## Worker 可以自主推进的（不动 §5.2 不动 A/B/C 决策点）

- **P2 补实验脚本**：4/6 → 6/6，文件 `scaling law toy/exp_mps_v4_cnn_sweep.py` 已有，需新增 2 个配置
  - 推荐配置：见 `scaling law toy/results/mps_v4_cnn_sweep/summary.json` 缺口分析
  - 输出新 `summary_v4_extended.json`，**先不改正文**，仅 commit 数据
- **§3 / Appendix A / Appendix C** 的 typo / formatting polish（已 hardened，只动语言）
- **Bibliography polish**（已修 7 处，剩余条目可继续核 arXiv ID）
- **State-9 stress test**（与论文 A 共享，可在任一 repo 跑，结果通用）

## 绝对禁区

- **不要动 §5.2 (sec:scaling-jump)** 的任何字符
- 不要动 §6.6 line 90、§7 line 10、§1 line 43、Abstract 末句
- 不要重新跑 v4 sweep（已完成、已 commit），只能新增 2 个 P2 配置
- 不要 close A/B/C 决策（user 必须拍板）
