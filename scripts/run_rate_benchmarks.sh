#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# FlexStack Fixed-Rate Benchmark Orchestrator
#
# Measures CPU and memory at realistic, fixed message rates instead of at
# saturation (--rate, see rust/src/pacing.rs and Pacer in python/benchmark.py).
#
# Cells, for every implementation and every rate R:
#   tx              unsecured and secured: own CAM generation at R msg/s
#   security-verify ECDSA-P256 verification at R msg/s (in-memory), i.e. the
#                   crypto load of R incoming secured CAMs per second
#
# Default rates: 10 (one station's own CAMs at 10 Hz), 100 and 1000 msg/s
# (10 and 100 neighbours at 10 Hz). For full-stack reception at a fixed rate,
# run the remote sender with a rate and label the receiver runs:
#   sender  : sudo ./send_packets_for_rx_benchmarks.sh eth0 7200 on 1000
#   receiver: sudo ./run_rx_benchmarks.sh rpi5 10 60 eth0 1000
#
# Usage:
#   sudo ./run_rate_benchmarks.sh [platform] [runs] [duration] [rate ...]
#
# Examples:
#   sudo ./run_rate_benchmarks.sh rpi5 10 60
#   sudo ./run_rate_benchmarks.sh laptop 10 60 10 100 1000 2000
#
# A cell whose achieved throughput stays below its target rate means the
# implementation cannot sustain that rate; analyze_results.py flags it.
#
# Prerequisites: as for run_benchmarks.sh (prepare_system.sh first: the
# 'performance' governor matters here, otherwise the CPU clocks down between
# paced messages and every operation becomes slower).

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
PLATFORM="${1:-laptop}"
RUNS="${2:-10}"
DURATION="${3:-60}"
shift $(( $# < 3 ? $# : 3 ))
RATES=("$@")
if [ "${#RATES[@]}" -eq 0 ]; then
  RATES=(10 100 1000)
fi
COOLDOWN=10
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT="../results/results_rate_${PLATFORM}_${TIMESTAMP}.csv"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

RUST_BIN="$PROJECT_DIR/rust/target/release/flexstack-bench"
PYTHON_BENCH="$PROJECT_DIR/python/benchmark.py"
CPYTHON="${CPYTHON:-$PROJECT_DIR/venv/bin/python3}"
PYPY="${PYPY:-$PROJECT_DIR/pypy/bin/pypy3}"
BENCH_CORES="${BENCH_CORES:-2,3}"
BENCH_INTERFACE="${BENCH_INTERFACE:-lo}"
IMPLS="${IMPLS:-rust cpython pypy}"

echo "============================================================"
echo "FlexStack Fixed-Rate Benchmark Orchestrator"
echo "============================================================"
echo "  Platform   : $PLATFORM"
echo "  Runs/cell  : $RUNS"
echo "  Duration   : ${DURATION}s"
echo "  Rates      : ${RATES[*]} msg/s"
echo "  Impls      : $IMPLS"
echo "  Output     : $OUTPUT"
echo "  Cores      : $BENCH_CORES"
echo "============================================================"

if [ ! -f "$RUST_BIN" ]; then
  echo "ERROR: Rust benchmark binary not found at $RUST_BIN"
  exit 1
fi
if [ ! -f "$PROJECT_DIR/certs/root_ca.cert" ]; then
  echo "WARNING: Certificates not found. Secured cells will fail."
fi
FIRST_CORE="${BENCH_CORES%%[,-]*}"
GOV=$(cat "/sys/devices/system/cpu/cpu${FIRST_CORE}/cpufreq/scaling_governor" 2>/dev/null || echo "unknown")
if [ "$GOV" != "performance" ]; then
  echo "WARNING: governor on cpu${FIRST_CORE} is '$GOV', not 'performance'."
  echo "         Paced runs will measure a down-clocked CPU. Run prepare_system.sh first."
fi
echo

# ── Environment record + per-run thermal/throttling sidecar ─────────────────
# shellcheck source=lib_monitor.sh
source "$SCRIPT_DIR/lib_monitor.sh"
ENV_FILE="${OUTPUT%.csv}_env.txt"
THERMAL_CSV="${OUTPUT%.csv}_thermal.csv"
CARGO_LOCK="$PROJECT_DIR/rust/Cargo.lock"
record_environment "$ENV_FILE" "$PLATFORM" "$BENCH_CORES"
monitor_init "$THERMAL_CSV" "$BENCH_CORES"

# ── Helper: run a single cell at a fixed rate ───────────────────────────────
run_cell() {
  local IMPL="$1" SECURITY="$2" BENCH="$3" RATE="$4"
  local WARMUP=5
  if [ "$IMPL" = "pypy" ]; then
    WARMUP=15
  fi

  for RUN in $(seq 1 "$RUNS"); do
    echo ""
    echo "──────────────────────────────────────────────────────────"
    echo "[$(date '+%H:%M:%S')] $IMPL | $SECURITY | $BENCH | ${RATE} msg/s | run $RUN/$RUNS"
    echo "──────────────────────────────────────────────────────────"

    monitor_run_start
    case "$IMPL" in
      rust)
        chrt -r 50 taskset -c "$BENCH_CORES" \
          "$RUST_BIN" \
          --mode "$BENCH" --security "$SECURITY" --rate "$RATE" \
          --duration "$DURATION" --warmup "$WARMUP" \
          --output "$OUTPUT" --run-id "$RUN" \
          --platform "$PLATFORM" \
          --interface "$BENCH_INTERFACE" \
          --certs-dir "$PROJECT_DIR/certs" \
          2>&1 || echo "  [WARN] Rust benchmark exited with error"
        ;;
      cpython|pypy)
        local PY="$CPYTHON"
        if [ "$IMPL" = "pypy" ]; then
          PY="$PYPY"
        fi
        chrt -r 50 taskset -c "$BENCH_CORES" \
          "$PY" "$PYTHON_BENCH" \
          --mode "$BENCH" --security "$SECURITY" --rate "$RATE" \
          --duration "$DURATION" --warmup "$WARMUP" \
          --output "$OUTPUT" --run-id "$RUN" \
          --platform "$PLATFORM" \
          --interface "$BENCH_INTERFACE" \
          2>&1 || echo "  [WARN] $IMPL benchmark exited with error"
        ;;
    esac
    monitor_run_end "$IMPL" "$SECURITY" "$BENCH" "$RUN" "$RATE"

    if [ "$RUN" -lt "$RUNS" ]; then
      echo "  Cooling down (${COOLDOWN}s)..."
      sleep "$COOLDOWN"
    fi
  done
}

# ── Main matrix ─────────────────────────────────────────────────────────────
TOTAL_START=$(date +%s)

for RATE in "${RATES[@]}"; do
  echo "================================================================"
  echo "  Fixed rate: ${RATE} msg/s"
  echo "================================================================"
  for IMPL in $IMPLS; do
    run_cell "$IMPL" "off" "tx" "$RATE"
    run_cell "$IMPL" "on" "tx" "$RATE"
    run_cell "$IMPL" "on" "security-verify" "$RATE"
  done
done

TOTAL_ELAPSED=$(( $(date +%s) - TOTAL_START ))
echo
echo "============================================================"
echo "Fixed-rate benchmarks complete!"
echo "  Total time : $((TOTAL_ELAPSED / 3600))h $(((TOTAL_ELAPSED % 3600) / 60))m"
echo "  Results    : $OUTPUT"
echo "  Environment: $ENV_FILE"
echo "  Thermal    : $THERMAL_CSV"
echo "============================================================"
echo
echo "Next step: cd ../analysis && python3 analyze_results.py --input $OUTPUT"
