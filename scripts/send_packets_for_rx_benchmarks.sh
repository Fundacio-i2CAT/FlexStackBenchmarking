#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# FlexStack RX Benchmark — Packet Sender
#
# Runs on the SENDER machine to flood CAMs on a given L2 interface while
# the receiver machine runs run_rx_benchmarks.sh on the same interface.
#
# This uses the Rust benchmark in TX mode (fastest sender) to generate
# properly formatted GeoNetworking packets (EtherType 0x8947) with full
# stack encoding: CAM → BTP → GN → Link Layer.
#
# Usage:
#   sudo ./send_packets_for_rx_benchmarks.sh <interface> [duration] [security] [rate]
#
# Arguments:
#   interface   — L2 network interface connected to the receiver (e.g. eth0)
#   duration    — How long to send in seconds (default: 7200 = 2 hours)
#                 Set this longer than the total RX benchmark run time.
#   security    — "off" or "on" (default: off)
#                 Use "off" when receiver runs security=off benchmarks,
#                 switch to "on" for security=on benchmarks.
#   rate        — msg/s to send (default: 0 = as fast as possible). For a
#                 fixed-rate RX measurement, pass the same value as the
#                 receiver's 5th argument (run_rx_benchmarks.sh) so it is
#                 recorded in the results.
#
# Examples:
#   # Send unsecured CAMs for 2 hours on eth0
#   sudo ./send_packets_for_rx_benchmarks.sh eth0
#
#   # Send secured CAMs for 1 hour on enp3s0
#   sudo ./send_packets_for_rx_benchmarks.sh enp3s0 3600 on
#
#   # Send secured CAMs at 1000 msg/s (100 neighbours at 10 Hz)
#   sudo ./send_packets_for_rx_benchmarks.sh eth0 7200 on 1000
#
# Note: The receiver's RX benchmark must be started AFTER or concurrently
#       with this sender. The sender will keep transmitting until the
#       duration expires or it is stopped with Ctrl+C.

set -euo pipefail

INTERFACE="${1:?Usage: $0 <interface> [duration] [security] [rate msg/s, 0 = max]}"
DURATION="${2:-7200}"
SECURITY="${3:-off}"
RATE="${4:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RUST_BIN="$PROJECT_DIR/rust/target/release/flexstack-bench"

if [ ! -f "$RUST_BIN" ]; then
  echo "ERROR: Rust benchmark binary not found at $RUST_BIN"
  echo "       Build it first: cd $PROJECT_DIR/rust && cargo build --release"
  exit 1
fi

echo "============================================================"
echo "FlexStack RX Benchmark — Packet Sender"
echo "============================================================"
echo "  Interface : $INTERFACE"
echo "  Duration  : ${DURATION}s"
echo "  Security  : $SECURITY"
echo "  Rate      : $( [ "$RATE" = "0" ] && echo max || echo "$RATE msg/s")"
echo "  Binary    : $RUST_BIN"
echo "============================================================"
echo
echo "  Sending CAMs ($( [ "$RATE" = "0" ] && echo "max rate" || echo "$RATE msg/s")). Stop with Ctrl+C."
echo "  Start the receiver now: sudo ./run_rx_benchmarks.sh <platform> <runs> <duration> $INTERFACE $RATE"
echo

# Use warmup=0 — we want to start sending immediately.
# Output goes to /dev/null since we only care about sending.
exec "$RUST_BIN" \
  --mode tx \
  --security "$SECURITY" \
  --at 1 \
  --certs-dir "$PROJECT_DIR/certs" \
  --rate "$RATE" \
  --duration "$DURATION" \
  --warmup 0 \
  --interface "$INTERFACE" \
  --output /dev/null \
  --platform laptop \
  --run-id 1
