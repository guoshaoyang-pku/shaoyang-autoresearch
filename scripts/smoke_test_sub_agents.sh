#!/usr/bin/env bash
# Smoke test for autoresearch sub-agents (v2, 2026-05+).
#
# Runs each module's self-test and verifies mgr CLI picks them up.
# Hermetic: no network calls (lit_review.py --self-test default skips network).
#
# Exit 0 if all pass; non-zero if any fail.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT}"

PASS=0
FAIL=0
RESULTS=()

run_check() {
    local name="$1"; shift
    local cmd_str="$*"
    echo "----- ${name} -----"
    if "$@" 2>&1 | tail -3; then
        # also check exit code from the actual command
        if "$@" >/dev/null 2>&1; then
            PASS=$((PASS + 1))
            RESULTS+=("PASS: ${name}")
            echo "[ok] ${name}"
        else
            FAIL=$((FAIL + 1))
            RESULTS+=("FAIL: ${name}  (cmd: ${cmd_str})")
            echo "[FAIL] ${name}"
        fi
    else
        FAIL=$((FAIL + 1))
        RESULTS+=("FAIL: ${name}  (cmd: ${cmd_str})")
        echo "[FAIL] ${name}"
    fi
    echo
}

echo "=========================================="
echo "  cursor_manager autoresearch sub-agents"
echo "  smoke test (cwd: ${ROOT})"
echo "=========================================="
echo

run_check "lib.reviewer_sim --self-test"          python -m lib.reviewer_sim --self-test
run_check "lib.lit_review --self-test"            python -m lib.lit_review --self-test
run_check "lib.codex_worker --self-test"          python -m lib.codex_worker --self-test
run_check "sentinel.py --self-test"               python sentinel.py --self-test
run_check "scripts/_invoke_manager.py --self-test" python scripts/_invoke_manager.py --self-test

echo "----- bash syntax: tick.sh / kickoff.sh -----"
for sh in tick.sh kickoff.sh; do
    if bash -n "${ROOT}/${sh}"; then
        echo "[ok] bash -n ${sh}"
        PASS=$((PASS + 1))
        RESULTS+=("PASS: bash -n ${sh}")
    else
        echo "[FAIL] bash -n ${sh}"
        FAIL=$((FAIL + 1))
        RESULTS+=("FAIL: bash -n ${sh}")
    fi
done
echo

echo "----- mgr CLI subcommand wiring -----"
for sub in review-sim lit-review sentinel-tick backend-test; do
    if python mgr ${sub} --help >/dev/null 2>&1; then
        echo "[ok] mgr ${sub} --help"
        PASS=$((PASS + 1))
        RESULTS+=("PASS: mgr ${sub} --help")
    else
        echo "[FAIL] mgr ${sub} --help"
        FAIL=$((FAIL + 1))
        RESULTS+=("FAIL: mgr ${sub} --help")
    fi
done
echo

echo "----- _invoke_manager.py argparse wiring -----"
for sub in kickoff tick; do
    if python scripts/_invoke_manager.py ${sub} --help >/dev/null 2>&1; then
        echo "[ok] _invoke_manager.py ${sub} --help"
        PASS=$((PASS + 1))
        RESULTS+=("PASS: _invoke_manager.py ${sub} --help")
    else
        echo "[FAIL] _invoke_manager.py ${sub} --help"
        FAIL=$((FAIL + 1))
        RESULTS+=("FAIL: _invoke_manager.py ${sub} --help")
    fi
done
echo

echo "=========================================="
echo "  Summary"
echo "=========================================="
for r in "${RESULTS[@]}"; do echo "  ${r}"; done
echo
echo "  PASSED: ${PASS}"
echo "  FAILED: ${FAIL}"
if [[ ${FAIL} -eq 0 ]]; then
    echo "smoke_test: ALL PASS"
    exit 0
else
    echo "smoke_test: FAIL (${FAIL} of $((PASS + FAIL)))"
    exit 1
fi
