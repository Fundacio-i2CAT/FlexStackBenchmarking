#!/usr/bin/env bash
# Over-the-air C-V2X RX cells on the MK6 pair, after their other cells:
# MK6 .101 sends saturated CAMs in one continuous process (no gaps between
# the receiver's runs) while MK6 .107 runs the RX cell with run_after.sh.
# Credentials from the environment (SSHPASS). Log: stdout.
set -u
TX=<user>@<ip> RX=<user>@<ip>   # MK6 units on the router (wired)
O=(-o PubkeyAuthentication=no -o ConnectTimeout=15 -o ServerAliveInterval=30)
r() { sshpass -e ssh "${O[@]}" "$1" 'bash -s'; }
busy() { echo "pgrep -f 'scripts/run_after.sh|flexstack-bench-cv2x' >/dev/null && echo busy || echo idle" | r "$1"; }
log() { echo "[$(date '+%F %T')] $*"; }

log "waiting for the MK6 cells to finish"
until [[ "$(busy $TX)" == idle && "$(busy $RX)" == idle ]]; do sleep 60; done

RUNS=30 SENDER_S=2700   # 30 x (60 s + 5 s warm-up + 10 s cool-down + teardown) < 2700 s
for sec in off on; do
    stamp=$(date +%Y%m%dT%H%M%S)
    log "phase rx $sec: start sender on .101 for ${SENDER_S}s"
    r $TX <<E
cd ~/FlexStackBenchmarking
sudo bash -c "nohup setsid chrt -r 50 taskset -c 2,3 rust/target/release/flexstack-bench-cv2x --mode tx --security $sec \
  --duration $SENDER_S --warmup 2 --platform mk6 --run-id 1 --at 1 --certs-dir certs \
  --output results/ota_sender_${sec}_$stamp.csv > results/ota_sender_${sec}_$stamp.log 2>&1 </dev/null &"
E
    sleep 15
    log "phase rx $sec: receiver cell on .107"
    r $RX <<E
cd ~/FlexStackBenchmarking
sudo bash -c "nohup setsid scripts/run_after.sh --platform mk6 --cores 2,3 --at 2 --cell 'rust-cv2x rx $sec 0 $RUNS' >/dev/null 2>&1 </dev/null &"
E
    sleep 30
    until [[ "$(busy $RX)" == idle ]]; do sleep 60; done
    log "phase rx $sec: receiver done; waiting for the sender to end"
    until [[ "$(busy $TX)" == idle ]]; do sleep 30; done
    log "phase rx $sec: sender ended"
done
log "MK6 over-the-air RX done"
