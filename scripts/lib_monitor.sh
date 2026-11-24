#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# Shared monitoring helpers for the benchmark orchestrators (sourced, not run).
#
#   record_environment <env_file> <platform> <cores>
#       One-off description of the system and software under test: kernel,
#       CPU, governor, turbo/SMT state, swap, interpreter / package / binary
#       versions and sizes. Covers the reproducibility details asked for in
#       the paper's methodology section.
#
#   monitor_init <thermal_csv>
#   monitor_run_start / monitor_run_end <impl> <security> <benchmark> <run_id> [rate]
#       Per-run thermal and throttling sidecar CSV. Each row brackets one run
#       with SoC temperature, CPU frequency of the first pinned core and the
#       throttling state:
#         - Raspberry Pi: `vcgencmd get_throttled` bitmask. Bits 16-19 are
#           sticky "has occurred since boot" flags, so a change between start
#           and end means throttling or under-voltage happened during the run.
#         - x86: sum of core_throttle_count over the pinned cores (a counter;
#           end - start > 0 means thermal throttling during the run).
#       The analysis joins it to the results on (run_id, impl, security,
#       benchmark, target_rate) and flags affected runs; it never drops them.
#
# All probes are best-effort: a missing tool or file yields an empty field.

_first_core() {
  echo "${1%%[,-]*}"
}

_expand_cores() {
  # "2,3" or "2-3" -> "2 3"
  local spec="$1" out="" part a b i
  IFS=',' read -ra parts <<< "$spec"
  for part in "${parts[@]}"; do
    if [[ "$part" == *-* ]]; then
      a="${part%-*}"; b="${part#*-}"
      for ((i = a; i <= b; i++)); do out+="$i "; done
    else
      out+="$part "
    fi
  done
  echo "$out"
}

_soc_temp_c() {
  if command -v vcgencmd >/dev/null 2>&1; then
    vcgencmd measure_temp 2>/dev/null | sed -n "s/^temp=\([0-9.]*\).*/\1/p" || true
    return 0
  fi
  local max=0 t f
  for f in /sys/class/thermal/thermal_zone*/temp; do
    [ -r "$f" ] || continue
    t=$(cat "$f" 2>/dev/null) || continue
    [[ "$t" =~ ^[0-9]+$ ]] && [ "$t" -gt "$max" ] && max=$t
  done
  if [ "$max" -gt 0 ]; then LC_ALL=C awk -v m="$max" 'BEGIN { printf "%.1f", m / 1000 }'; fi
  return 0
}

_cpu_freq_khz() {
  cat "/sys/devices/system/cpu/cpu$1/cpufreq/scaling_cur_freq" 2>/dev/null || true
}

_throttle_state() {
  # RPi: hex bitmask; x86: summed core_throttle_count of the pinned cores.
  if command -v vcgencmd >/dev/null 2>&1; then
    vcgencmd get_throttled 2>/dev/null | sed -n "s/^throttled=//p" || true
    return 0
  fi
  local sum=0 found=0 c f
  for c in $(_expand_cores "$MONITOR_CORES"); do
    f="/sys/devices/system/cpu/cpu$c/thermal_throttle/core_throttle_count"
    if [ -r "$f" ]; then
      sum=$((sum + $(cat "$f"))); found=1
    fi
  done
  if [ "$found" -eq 1 ]; then echo "$sum"; fi
  return 0
}

monitor_init() {
  MONITOR_CSV="$1"
  MONITOR_CORES="${2:-0}"
  mkdir -p "$(dirname "$MONITOR_CSV")"
  if [ ! -f "$MONITOR_CSV" ]; then
    echo "run_id,implementation,security,benchmark,start_utc,end_utc,temp_start_c,temp_end_c,freq_start_khz,freq_end_khz,throttle_start,throttle_end,target_rate" \
      > "$MONITOR_CSV"
  fi
}

monitor_run_start() {
  local core
  core=$(_first_core "$MONITOR_CORES")
  _MON_START_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  _MON_TEMP_START=$(_soc_temp_c)
  _MON_FREQ_START=$(_cpu_freq_khz "$core")
  _MON_THR_START=$(_throttle_state)
}

monitor_run_end() {
  local impl="$1" sec="$2" bench="$3" run="$4" rate="${5:-0}" core
  core=$(_first_core "$MONITOR_CORES")
  echo "$run,$impl,$sec,$bench,$_MON_START_UTC,$(date -u +%Y-%m-%dT%H:%M:%SZ),$_MON_TEMP_START,$(_soc_temp_c),$_MON_FREQ_START,$(_cpu_freq_khz "$core"),$_MON_THR_START,$(_throttle_state),$rate" \
    >> "$MONITOR_CSV"
}

_kv() {
  printf '%-24s: %s\n' "$1" "$2"
}

record_environment() {
  local env_file="$1" platform="$2" cores="$3" c
  mkdir -p "$(dirname "$env_file")"
  {
    echo "# FlexStack benchmark environment"
    _kv "date_utc" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    _kv "platform" "$platform"
    _kv "hostname" "$(hostname)"
    _kv "kernel" "$(uname -srvm)"
    _kv "os" "$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
    _kv "cpu_model" "$(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -1)"
    [ -r /proc/device-tree/model ] && _kv "board" "$(tr -d '\0' < /proc/device-tree/model)"
    _kv "online_cpus" "$(cat /sys/devices/system/cpu/online 2>/dev/null)"
    _kv "smt_active" "$(cat /sys/devices/system/cpu/smt/active 2>/dev/null)"
    _kv "intel_no_turbo" "$(cat /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null)"
    _kv "pinned_cores" "$cores"
    for c in $(_expand_cores "$cores"); do
      _kv "cpu${c}_governor" "$(cat /sys/devices/system/cpu/cpu$c/cpufreq/scaling_governor 2>/dev/null)"
      _kv "cpu${c}_freq_khz" "$(_cpu_freq_khz "$c")"
      _kv "cpu${c}_max_freq_khz" "$(cat /sys/devices/system/cpu/cpu$c/cpufreq/scaling_max_freq 2>/dev/null)"
    done
    _kv "mem_total" "$(sed -n 's/^MemTotal:[[:space:]]*//p' /proc/meminfo)"
    _kv "swap_active" "$(swapon --noheadings 2>/dev/null | wc -l) device(s)"
    _kv "soc_temp_c" "$(_soc_temp_c)"
    _kv "throttle_state" "$(MONITOR_CORES="$cores" _throttle_state)"
    command -v vcgencmd >/dev/null 2>&1 && _kv "rpi_firmware" "$(vcgencmd version 2>/dev/null | tail -1)"
    echo
    echo "# Software under test"
    if [ -n "${RUST_BIN:-}" ] && [ -f "$RUST_BIN" ]; then
      _kv "rust_bin" "$RUST_BIN"
      _kv "rust_bin_size_bytes" "$(stat -c %s "$RUST_BIN")"
      _kv "rust_bin_sha256" "$(sha256sum "$RUST_BIN" | cut -d' ' -f1)"
    fi
    if [ -n "${CARGO_LOCK:-}" ] && [ -f "$CARGO_LOCK" ]; then
      for crate in rustflexstack rasn p256; do
        _kv "crate_$crate" "$(awk -v n="$crate" '$0 == "name = \"" n "\"" { getline; gsub(/version = |"/, ""); print; exit }' "$CARGO_LOCK")"
      done
    fi
    command -v rustc >/dev/null 2>&1 && _kv "rustc" "$(rustc --version)"
    local py
    for py in "${CPYTHON:-}" "${PYPY:-}"; do
      [ -n "$py" ] && command -v "$py" >/dev/null 2>&1 || continue
      _kv "interpreter" "$("$py" -c 'import sys; print(sys.executable, "|", sys.version.replace(chr(10), " "))' 2>/dev/null)"
      _kv "  v2xflexstack" "$("$py" -c 'from importlib.metadata import version; print(version("v2xflexstack"))' 2>/dev/null)"
      _kv "  v2xflexstack_size_kb" "$("$py" -c 'import os, flexstack; print(os.path.dirname(flexstack.__file__))' 2>/dev/null | xargs -r du -sk 2>/dev/null | cut -f1)"
      _kv "  asn1tools" "$("$py" -c 'from importlib.metadata import version; print(version("asn1tools"))' 2>/dev/null)"
      _kv "  cryptography" "$("$py" -c 'from importlib.metadata import version; print(version("cryptography"))' 2>/dev/null)"
    done
    echo
    echo "# Running services (background load)"
    systemctl list-units --type=service --state=running --no-legend --plain 2>/dev/null | awk '{print "  " $1}'
  } > "$env_file"
  echo "  Environment recorded in $env_file"
}
