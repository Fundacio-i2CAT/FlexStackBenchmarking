#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# System preparation script for FlexStack benchmarks.
# Run this BEFORE starting any benchmark session.
#
# Usage: sudo ./prepare_system.sh [laptop|rpi3|rpi5|agx-orin|orin-nano|mk6]

set -euo pipefail

PLATFORM="${1:-laptop}"

echo "============================================================"
echo "FlexStack Benchmark — System Preparation"
echo "Platform: $PLATFORM"
echo "============================================================"
echo

case "$PLATFORM" in
  laptop)
    echo "[1/6] Setting CPU governor to 'performance'..."
    cpupower frequency-set -g performance 2>/dev/null || \
      echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null || \
      echo "  WARNING: could not set the 'performance' governor."
    echo "  Governor: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"

    echo "[2/6] Disabling Intel Turbo Boost..."
    if [ -f /sys/devices/system/cpu/intel_pstate/no_turbo ]; then
      echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo
      echo "  Turbo Boost disabled."
    else
      echo "  WARNING: intel_pstate not found. Skipping."
    fi

    echo "[3/6] Verifying CPU frequency..."
    grep "cpu MHz" /proc/cpuinfo | head -1 || true

    echo "[4/6] Disabling HT siblings on cores 6-7 (optional)..."
    for cpu in 6 7; do
      if [ -f "/sys/devices/system/cpu/cpu${cpu}/online" ]; then
        echo 0 > "/sys/devices/system/cpu/cpu${cpu}/online" 2>/dev/null || true
      fi
    done

    echo "[5/6] Stopping non-essential services..."
    for svc in bluetooth cups avahi-daemon snapd; do
      systemctl stop "$svc" 2>/dev/null && echo "  Stopped $svc" || true
    done

    echo "[6/6] Disabling swap..."
    swapoff -a 2>/dev/null && echo "  Swap disabled." || true
    ;;

  rpi3|rpi5)
    echo "[1/5] Setting CPU governor to 'performance'..."
    echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null

    echo "[2/5] Disabling WiFi and Bluetooth..."
    # Never cut the interface this host is reached through (e.g. a Pi on Wi-Fi only).
    default_dev="$(ip route show default 2>/dev/null | awk '{print $5; exit}')"
    if [[ "$default_dev" == wl* ]]; then
      echo "  WARNING: the default route is on $default_dev (Wi-Fi): Wi-Fi left on."
    else
      rfkill block wifi 2>/dev/null || true
    fi
    rfkill block bluetooth 2>/dev/null || true

    echo "[3/5] Disabling swap..."
    swapoff -a 2>/dev/null && echo "  Swap disabled." || true

    echo "[4/5] Stopping non-essential services..."
    for svc in triggerhappy dphys-swapfile bluetooth hciuart avahi-daemon; do
      systemctl stop "$svc" 2>/dev/null && echo "  Stopped $svc" || true
    done

    echo "[5/5] Verifying CPU frequency..."
    cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq || true
    ;;

  agx-orin|orin-nano)
    # NVIDIA Jetson (AGX Orin, Orin Nano): the power mode (nvpmodel) is left
    # as configured and recorded; jetson_clocks pins CPU/EMC clocks to the
    # maximum of that mode (reset at reboot, or `jetson_clocks --restore`).
    echo "[1/4] Power mode (unchanged): $(nvpmodel -q 2>/dev/null | head -1)"
    echo "[2/4] Pinning clocks (jetson_clocks) and governor 'performance'..."
    jetson_clocks 2>/dev/null || echo "  WARNING: jetson_clocks failed."
    echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null || true
    echo "[3/4] Disabling swap..."
    swapoff -a 2>/dev/null && echo "  Swap disabled." || true
    echo "[4/4] Verifying CPU frequency..."
    cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq || true
    ;;
  mk6)
    # Cohda MK6: only the governor and swap; the radio daemon (cv2x-daemon)
    # and the vendor services are left running, as the C-V2X benchmarks need them.
    echo "[1/3] Setting CPU governor to 'performance'..."
    echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null
    echo "[2/3] Disabling swap..."
    swapoff -a 2>/dev/null && echo "  Swap disabled." || true
    echo "[3/3] Verifying CPU frequency..."
    cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq || true
    ;;
  *)
    echo "ERROR: Unknown platform '$PLATFORM'. Use: laptop, rpi3, rpi5, agx-orin, orin-nano or mk6."
    exit 1
    ;;
esac

echo
echo "System preparation complete."
echo "Run benchmarks with: ./run_benchmarks.sh $PLATFORM"
