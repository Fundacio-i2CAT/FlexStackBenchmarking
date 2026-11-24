#!/usr/bin/env bash
# Ethernet RX cells of the laptop and the RPi5 at the same time, with this
# computer as the sender: NSEND Rust TX processes (released static harness,
# campaign certificates) flood GeoNetworking SHB CAMs on $IFACE from Docker
# (NET_RAW, no root needed on the host). One phase per security mode; the
# senders run for the whole phase, so the receivers' windows have no gaps.
# The sender rate is recorded from the interface counters.
# Env: LAPTOP_PASS, RPI5_PASS, RPI3_PASS. Usage: lan_rx.sh <iface> [runs] [nsend]
set -u
IFACE="$1" RUNS="${2:-30}" NSEND="${3:-3}"
S="$(cd "$(dirname "$0")" && pwd)"
BENCH=/home/<user>/Desktop/Flexstack/UpdatingRust/FlexStackBenchmarking
VZ=$BENCH/dist/vanetza/x86_64   # Vanetza harness bundle (sender)
CERTS=$BENCH/results/campaign_2026-11/artefacts/certs
OUT=$S/lan_rx_sender; mkdir -p "$OUT"
LAP=(<user>@<ip> "$LAPTOP_PASS" laptop enp0s31f6)   # control over Wi-Fi
RPI=(<user>@<ip> "$RPI5_PASS" rpi5 eth0)
RP3=(<user>@<ip> "$RPI3_PASS" rpi3 eth0)     # RPi3 board "a"
RP3B=<user>@<ip>                            # RPi3 board "b" (wired): must not be flooded while it runs
O=(-o PubkeyAuthentication=no -o ConnectTimeout=15 -o ServerAliveInterval=30)
log() { echo "[$(date '+%F %T')] $*"; }
r() { SSHPASS="$2" sshpass -e ssh "${O[@]}" "$1" 'bash -s'; }
busy() { echo "pgrep -f 'scripts/run_after.sh' >/dev/null && echo busy || echo idle" | r "$1" "$2"; }
txp() { cat /sys/class/net/$IFACE/statistics/tx_packets; }

start_receiver() {  # host pass platform iface sec
    { echo 'read -r PW'; printf '%s\n' "$2"; cat <<E; } | r "$1" "$2"
cd ~/FlexStackBenchmarking || exit 1
# governor only: prepare_system.sh would also block Wi-Fi, the control plane
printf '%s\n' "\$PW" | sudo -S -p "" bash -c "echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor >/dev/null"
printf '%s\n' "\$PW" | sudo -S -p "" bash -c "nohup setsid scripts/run_after.sh --platform $3 --cores 2,3 --interface $4 \
  --cell 'cpython rx $5 0 $RUNS' --cell 'pypy rx $5 0 $RUNS' --cell 'rust rx $5 0 $RUNS' --cell 'vanetza rx $5 0 $RUNS' \
  >/dev/null 2>&1 </dev/null &"
E
}

# RPi3 "b" (TX rerun, on the switch) must have finished before the flood. Its
# own job brings up its Wi-Fi only after the rerun ends: wait until a host on
# the Wi-Fi subnet answers with board b's wired MAC and that job's done file.
# Override (board b unplugged from the switch): touch $S/rpi3b_unplugged
find_rpi3b() {
    for i in $(seq 100 140); do
        timeout 1 bash -c "echo >/dev/tcp/<ip>$i/22" 2>/dev/null || continue
        echo 'test "$(cat /sys/class/net/eth0/address)" = <mac> && test -f /tmp/wifi_after_rerun.done && echo <ip>'$i \
          | SSHPASS="$RPI3_PASS" timeout 8 sshpass -e ssh "${O[@]}" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null <user>@<ip>$i 'bash -s' 2>/dev/null && return 0
    done; return 1; }
until [[ -f "$S/rpi3b_unplugged" ]] || B3=$(find_rpi3b); do
    log "RPi3 b still running its TX rerun (not yet on Wi-Fi): waiting"; sleep 120; done
log "RPi3 b done (${B3:-unplugged})"
all_idle() { [[ "$(busy "${LAP[0]}" "${LAP[1]}")" == idle && "$(busy "${RPI[0]}" "${RPI[1]}")" == idle && "$(busy "${RP3[0]}" "${RP3[1]}")" == idle ]]; }
until all_idle; do sleep 60; done
log "receivers idle; RPi3 b idle or disconnected"
# Safety interlock: flood only when the switch is isolated from the router
# (broadcasts would otherwise reach its Wi-Fi). Waits until <ip> is gone.
until ! ping -c 2 -W 2 -I "$IFACE" <ip> >/dev/null 2>&1; do
    log "router <ip> still reachable on $IFACE: waiting for the switch uplink to be unplugged"; sleep 60; done
[[ "$(cat /sys/class/net/$IFACE/operstate)" == up ]] || { log "$IFACE is not up"; exit 1; }
log "switch isolated from the router: removing the IPv4 addresses of the wired data plane"
nmcli device modify "$IFACE" ipv4.method disabled ipv6.method disabled >/dev/null   # this computer first
sleep 5
for h in LAP RPI RP3; do eval "u=\${$h[0]} pw=\${$h[1]} ifc=\${$h[3]}"
    { echo 'read -r PW'; printf '%s\n' "$pw"; echo "printf '%s\n' \"\$PW\" | sudo -S -p '' bash -c 'nohup nmcli device modify $ifc ipv4.method disabled ipv6.method disabled >/dev/null 2>&1 &'"; } | r "$u" "$pw" || true
done
sleep 10
for h in LAP RPI RP3; do eval "u=\${$h[0]} pw=\${$h[1]} ifc=\${$h[3]}"
    st=$(echo "echo \$(cat /sys/class/net/$ifc/operstate) \$(ip -4 -br addr show $ifc | awk '{print \$3}')" | r "$u" "$pw")
    log "${u#*@} (Wi-Fi control): wired $ifc = ${st:-UNREACHABLE}"
    [[ "$st" == "up" || "$st" == "up " ]] || { log "abort: ${u#*@} wired port not up without an address, or not reachable over Wi-Fi"; exit 1; }
done
log "data plane: wired, no IP; control plane: Wi-Fi"

for sec in off on; do
    stamp=$(date +%Y%m%dT%H%M%S)
    # Traffic generator: the Vanetza harness (commit 3b9a544), synchronous and
    # single-threaded, the fastest sender on this host; the same frames for every
    # receiver and implementation. Unsecured: 2 processes reach the NIC limit
    # (~100k frames/s); secured: 3 processes (~15k signed frames/s).
    # The Vanetza harness keeps ~160 B per message sent (known issue 9), so a
    # long-running sender runs out of memory: each of 3 slots runs 60 s chunks
    # back to back, the slots staggered by 20 s, so that >= 2 always send.
    NSEND=3
    log "phase rx $sec: starting $NSEND rolling Vanetza sender slots on $IFACE"
    rm -f "$OUT/stop_$sec"
    for i in $(seq 1 "$NSEND"); do
        ( sleep $(( (i - 1) * 20 )); k=0
          while [[ ! -f "$OUT/stop_$sec" ]]; do k=$((k + 1))
              docker run --rm --name "fsb-sender-$sec-$i-$k" --net host --cap-add NET_RAW --cap-add NET_ADMIN \
                  --cpuset-cpus "$i" -v "$VZ:/v:ro" -v "$CERTS:/c:ro" -v "$OUT:/out" ubuntu:24.04 \
                  /v/run.sh --mode tx --security "$sec" --interface "$IFACE" \
                  --duration 60 --warmup 0 --platform laptop --run-id "$i" --certs-dir /c --at 1 \
                  --output "/out/sender_${sec}_${stamp}.csv" > /dev/null 2>&1
          done ) &
    done
    sleep 30
    sleep 10
    p0=$(txp) t0=$(date +%s)
    sleep 5; p1=$(txp); log "phase rx $sec: sender rate ~$(( (p1 - p0) / 5 )) frames/s on $IFACE"
    start_receiver "${LAP[0]}" "${LAP[1]}" "${LAP[2]}" "${LAP[3]}" "$sec"
    start_receiver "${RPI[0]}" "${RPI[1]}" "${RPI[2]}" "${RPI[3]}" "$sec"
    start_receiver "${RP3[0]}" "${RP3[1]}" "${RP3[2]}" "${RP3[3]}" "$sec"
    sleep 60
    until all_idle; do
        log "phase rx $sec: running, sender ~$(( ($(txp) - p1) / ($(date +%s) - t0 - 5) )) frames/s average"
        sleep 300
    done
    p2=$(txp) t2=$(date +%s)
    log "phase rx $sec: receivers done; sender average $(( (p2 - p0) / (t2 - t0) )) frames/s over $(( t2 - t0 )) s"
    echo "$sec,$stamp,$t0,$t2,$p0,$p2,$NSEND,vanetza-3b9a544" >> "$OUT/sender_counters.csv"
    touch "$OUT/stop_$sec"; sleep 65   # let the running chunks end
    docker rm -f $(docker ps -aq --filter name=fsb-sender) >/dev/null 2>&1; wait
done
log "LAN RX done"
