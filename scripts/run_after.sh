#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Run more benchmark cells on a host once its current campaign has finished,
# with the protocol of ansible/run.yml: SCHED_RR priority 50 on the pinned
# cores, per-run time limit, cooldown, environment record, thermal sidecar
# and MANIFEST next to a new results CSV. Used to add the Vanetza cells (WP-D)
# behind a running campaign without touching it.
#
# Usage (as root, from the benchmark folder, e.g. under nohup):
#   scripts/run_after.sh --platform orin-nano --cores 2,3 \
#       --wait-pidfile results/bench_run.pid \
#       --cell "vanetza tx off 0 30" --cell "vanetza tx on 0 30" ...
# A cell is "<impl> <mode> <security> <rate> <runs>"; impl: vanetza | rust |
# rust-cv2x (Cohda MK6, C-V2X radio API) | cpython | pypy (PyPy gets
# --pypy-warmup, 15 s, as in run.yml).
# Options: --duration 60 --warmup 5 --pypy-warmup 15 --cooldown 10 --interface lo
#          --at 1 (authorization ticket of rust-cv2x: 1 sends, 2 receives)
set -uo pipefail

BENCH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM="" CORES="2,3" WAIT_PIDFILE="" DURATION=60 WARMUP=5 PYPY_WARMUP=15 COOLDOWN=10 IFACE=lo AT=1
CELLS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform) PLATFORM="$2"; shift 2 ;;
        --cores) CORES="$2"; shift 2 ;;
        --wait-pidfile) WAIT_PIDFILE="$2"; shift 2 ;;
        --duration) DURATION="$2"; shift 2 ;;
        --warmup) WARMUP="$2"; shift 2 ;;
        --pypy-warmup) PYPY_WARMUP="$2"; shift 2 ;;
        --cooldown) COOLDOWN="$2"; shift 2 ;;
        --interface) IFACE="$2"; shift 2 ;;
        --at) AT="$2"; shift 2 ;;
        --cell) CELLS+=("$2"); shift 2 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
done
[[ -n "$PLATFORM" && ${#CELLS[@]} -gt 0 ]] || { echo "need --platform and at least one --cell" >&2; exit 2; }

cd "$BENCH"
STAMP="$(date +%Y%m%dT%H%M%S)"
LOG="$BENCH/results/run_after_$STAMP.log"
exec > >(tee -a "$LOG") 2>&1

if [[ -n "$WAIT_PIDFILE" && -f "$WAIT_PIDFILE" ]]; then
    pid="$(cat "$WAIT_PIDFILE")"
    echo "[$(date '+%F %T')] waiting for the campaign (PID $pid) to finish"
    while kill -0 "$pid" 2>/dev/null; do sleep 30; done
    echo "[$(date '+%F %T')] campaign finished"
fi

RESULTS="$BENCH/results/results_${PLATFORM}_after_${STAMP}.csv"
source "$BENCH/scripts/lib_monitor.sh"
RUST_BIN_RECORDED="$BENCH/rust/target/release/flexstack-bench"
[[ -x "$RUST_BIN_RECORDED" ]] || RUST_BIN_RECORDED="$BENCH/rust/target/release/flexstack-bench-cv2x"  # MK6
RUST_BIN="$RUST_BIN_RECORDED" CARGO_LOCK="$BENCH/rust/Cargo.lock" \
    CPYTHON="$BENCH/venv/bin/python3" PYPY="$BENCH/pypy/bin/pypy3" \
    record_environment "${RESULTS%.csv}_env.txt" "$PLATFORM" "$CORES"
monitor_init "${RESULTS%.csv}_thermal.csv" "$CORES"
cp "$BENCH/MANIFEST.txt" "${RESULTS%.csv}_MANIFEST.txt" 2>/dev/null || true
[[ -f "$BENCH/vanetza/VANETZA_COMMIT" ]] && \
    echo "vanetza bundle: commit $(cat "$BENCH/vanetza/VANETZA_COMMIT"), sha256 $(sha256sum "$BENCH/vanetza/flexstack-bench-vanetza" | cut -d' ' -f1)" \
    >> "${RESULTS%.csv}_MANIFEST.txt"
echo "Results: $RESULTS"

for cell in "${CELLS[@]}"; do
    read -r impl mode security rate runs <<<"$cell"
    warm="$WARMUP"
    case "$impl" in
        vanetza) BIN=("$BENCH/vanetza/run.sh"); EXTRA=(--certs-dir "$BENCH/certs") ;;
        rust) BIN=("$BENCH/rust/target/release/flexstack-bench"); EXTRA=(--certs-dir "$BENCH/certs") ;;
        rust-cv2x) BIN=("$BENCH/rust/target/release/flexstack-bench-cv2x"); EXTRA=(--certs-dir "$BENCH/certs" --at "$AT") ;;
        cpython) BIN=("$BENCH/venv/bin/python3" "$BENCH/python/benchmark.py"); EXTRA=() ;;
        pypy) BIN=("$BENCH/pypy/bin/pypy3" "$BENCH/python/benchmark.py"); EXTRA=(); warm="$PYPY_WARMUP" ;;
        *) echo "unsupported impl $impl" >&2; continue ;;
    esac
    IFARG=(--interface "$IFACE"); [[ "$impl" == rust-cv2x ]] && IFARG=()  # the radio API needs no interface
    LIMIT=$((DURATION + warm + 120))
    echo "================================================================"
    echo "  $impl | $mode | security=$security | rate=$rate | runs=$runs"
    echo "================================================================"
    for RUN in $(seq 1 "$runs"); do
        echo "[$(date '+%H:%M:%S')] $impl | $mode | $security | run $RUN/$runs"
        monitor_run_start
        timeout -k 10 "$LIMIT" chrt -r 50 taskset -c "$CORES" "${BIN[@]}" \
            --mode "$mode" --security "$security" --rate "$rate" \
            --duration "$DURATION" --warmup "$warm" \
            --output "$RESULTS" --run-id "$RUN" --platform "$PLATFORM" \
            "${IFARG[@]}" "${EXTRA[@]}" || echo "  [WARN] exited with error"
        monitor_run_end "$impl" "$security" "$mode" "$RUN" "$rate"
        [[ "$RUN" -lt "$runs" ]] && sleep "$COOLDOWN"
    done
done
echo "[$(date '+%F %T')] all cells done: $RESULTS"
