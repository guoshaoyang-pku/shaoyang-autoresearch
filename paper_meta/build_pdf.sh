#!/usr/bin/env bash
# Build main.pdf with bounded pdflatex runs (macOS-safe: no GNU timeout).
# Usage: from paper_meta/: bash build_pdf.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

run_pdflatex() {
  python3 - <<'PY'
import subprocess, sys
try:
    r = subprocess.run(
        [
            "pdflatex",
            "-interaction=nonstopmode",
            "-file-line-error",
            "-no-shell-escape",
            "main.tex",
        ],
        cwd=".",
        timeout=60,
    )
    sys.exit(r.returncode)
except subprocess.TimeoutExpired:
    print("pdflatex: TIMEOUT 60s", file=sys.stderr)
    sys.exit(124)
PY
}

for attempt in 1 2 3; do
  echo "=== pdflatex pass $attempt ==="
  run_pdflatex || true
done

bibtex main || true

for attempt in 1 2 3; do
  echo "=== pdflatex post-bib pass $attempt ==="
  run_pdflatex || true
done

echo "Done. Check main.log for warnings."
