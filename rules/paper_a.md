# 论文 A (PICL/CA, 57911aa7) Worker 专属规则

仓库子目录：`ca_project/paper_neurips2026/`

## 当前被 Block 的 6 个决策（worker 不可代）

1. **页数压缩 phase 2**（K/J/F/G/G' 选哪个）
   - 已应用：A + D + I（累计 -25 行）
   - 仍溢 ~17 行
   - K = 零 claim 变动（推荐 default）；F/G = touch claim
2. **Abstract "widens with scale"** keep / soften
3. **Abstract "benchmark" vs "framework"** 改名与否
4. **Fig 5 EF 精度**（近似 vs 精确提取）
5. **代码释出策略**（R1/R2/R3 范围 + 许可 + 托管）
6. **Cover letter 受众**（area-chair / rebuttal / internal）

## Worker 可以自主推进的（不动 claim）

- **选项 K**：把 "Role of inductive bias" 段落搬到 Appendix D
  - 文件：`sections/05_scaling_connection.tex`（或 §6 末尾，需确认）
  - 搬到：`sections/06_ablations.tex` 或新 `appD` 子节
  - 验证：pdflatex+bibtex 0 warning，页数 < 21
- **Pointer 压缩**：把 "we discuss in §X" 类长句改 `\cref{...}`
- **State-9 stress test 实验脚本**：写在 `experiments/state9_stress.py`，多 seed run
- **任何 typo / formatting / bib polish**（不改 claim 即可）

## 绝对禁区

- 不要碰 §1 (Intro) 的"benchmark/framework"用词
- 不要碰 Abstract 任何词
- 不要碰 Fig 5 caption 的 EF 数字
- 不要 close 任何 [BLOCKED-DECISION] issue
