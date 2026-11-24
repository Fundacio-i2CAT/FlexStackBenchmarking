#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Signed interoperability matrix: FlexStack Python, FlexStack Rust and Vanetza
# exchange signed CAMs and DENMs over raw Ethernet (EtherType 0x8947) on a
# private Docker bridge network; a fourth node ("rogue") signs with an AT of an
# untrusted Root CA, which every receiver must refuse.
#
# Usage: interop/run_interop.sh [--duration S] [--backends "openssl cryptopp"] [--tag TAG] [--out DIR]
#
# Needs: Docker, the image and the Rust node built by interop/build.sh.
# Output (default results/interop/<UTC timestamp>/):
#   certs/                  certificate chains (make_certs.py, image's FlexStack)
#   matrix-<backend>/       the three stacks (Vanetza with the OpenSSL / Crypto++ backend)
#   rogue-<backend>/        the three stacks and a node with an untrusted chain
#   <scenario>/<node>.log   JSON-lines log of each node (README.md, "Log format")
#   <scenario>/capture.pcap every frame on the bridge (tcpdump in the network)
#   <scenario>/summary.json, matrix.csv, matrix.md   built by summarize.py
#   versions.txt            image, Vanetza commit, FlexStack versions
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH="$(cd "$HERE/.." && pwd)"
DURATION=120
BACKENDS="openssl cryptopp"
TAG="dev"
OUT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --duration) DURATION="$2"; shift 2 ;;
        --backends) BACKENDS="$2"; shift 2 ;;
        --tag) TAG="$2"; shift 2 ;;
        --out) OUT="$2"; shift 2 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
done
IMAGE="flexstack-interop:$TAG"
RUST_NODE="$BENCH/rust/target/release/flexstack-interop-node"
OUT="${OUT:-$BENCH/results/interop/$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_ID="fsinterop$$"
NET="$RUN_ID-net"

[[ -x "$RUST_NODE" ]] || { echo "missing $RUST_NODE: run interop/build.sh" >&2; exit 1; }
docker image inspect "$IMAGE" >/dev/null || { echo "missing image $IMAGE: run interop/build.sh" >&2; exit 1; }
mkdir -p "$OUT/certs"
OUT="$(cd "$OUT" && pwd)"

CONTAINERS=()
cleanup() {
    for c in "${CONTAINERS[@]}"; do docker rm -f "$c" >/dev/null 2>&1 || true; done
    docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

backend_name() {  # Vanetza's --crypto-backend spelling
    case "$1" in
        openssl) echo OpenSSL ;;
        cryptopp) echo CryptoPP ;;
        *) echo "$1" ;;
    esac
}

run() {  # run <name> <args...>: a detached container on the test network
    local name="$RUN_ID-$1"; shift
    docker run -d --name "$name" --network "$NET" --cap-add NET_RAW --cap-add NET_ADMIN \
        -v "$HERE:/interop:ro" -v "$OUT/certs:/certs:ro" -v "$RUST_NODE:/opt/bin/flexstack-interop-node:ro" \
        "$IMAGE" "$@" >/dev/null
    CONTAINERS+=("$name")
}

echo "== certificates"
docker run --rm --user "$(id -u):$(id -g)" -v "$HERE:/interop:ro" -v "$OUT/certs:/out" "$IMAGE" \
    python /interop/make_certs.py --out /out
{
    echo "image: $IMAGE $(docker image inspect -f '{{.Id}}' "$IMAGE")"
    echo "vanetza_commit: $(docker run --rm "$IMAGE" cat /opt/vanetza/VANETZA_COMMIT)"
    echo "flexstack_python: $(docker run --rm "$IMAGE" python -c 'import importlib.metadata as m; print(m.version("v2xflexstack"))')"
    echo "flexstack_rust_node: $(sha256sum "$RUST_NODE" | cut -d' ' -f1)"
    echo "duration_s: $DURATION"
    echo "started_utc: $(date -u +%FT%TZ)"
} > "$OUT/versions.txt"
cat "$OUT/versions.txt"

scenario() {  # scenario <dir> <backend> <nodes...>: run the nodes for DURATION seconds
    local dir="$1" backend="$2"; shift 2
    local nodes=("$@")
    mkdir -p "$dir"
    docker network create --driver bridge "$NET" >/dev/null
    CONTAINERS=()
    # Positions within 30 m of each other (GBC areas of 1 km around each sender).
    for node in "${nodes[@]}"; do
        case "$node" in
            python) run python python /interop/python/interop_node.py --node python --iface eth0 \
                        --certs-dir /certs --at at_python --station-id 1 --lat 41.38700 --lon 2.17000 ;;
            rust)   run rust /opt/bin/flexstack-interop-node --node rust --iface eth0 \
                        --certs-dir /certs --at at_rust --station-id 2 --lat 41.38720 --lon 2.17010 ;;
            vanetza) run vanetza vanetza-interop-node --node vanetza --interface eth0 --station-id 3 \
                        --cam-interval 100 --denm-interval 1000 \
                        --positioning static --latitude 41.38710 --longitude 2.17020 \
                        --security certs --crypto-backend "$(backend_name "$backend")" \
                        --certificate /certs/at_vanetza.cert --certificate-key /certs/at_vanetza.pem \
                        --certificate-chain /certs/aa.cert /certs/root_ca.cert ;;
            rogue)  run rogue python /interop/python/interop_node.py --node rogue --iface eth0 \
                        --certs-dir /certs --root rogue_root_ca --aa rogue_aa --at at_rogue --station-id 4 \
                        --lat 41.38690 --lon 2.17030 ;;
        esac
    done
    docker run -d --name "$RUN_ID-capture" --network "container:$RUN_ID-${nodes[0]}" --cap-add NET_RAW \
        -v "$dir:/capture" "$IMAGE" tcpdump -i eth0 -U -w /capture/capture.pcap ether proto 0x8947 >/dev/null
    CONTAINERS+=("$RUN_ID-capture")
    sleep "$DURATION"
    for c in "${CONTAINERS[@]}"; do docker stop -t 5 "$c" >/dev/null || true; done
    local logs=()
    for node in "${nodes[@]}"; do
        docker logs "$RUN_ID-$node" > "$dir/$node.log" 2> "$dir/$node.stderr" || true
        logs+=("$dir/$node.log")
    done
    cleanup
    CONTAINERS=()
    python3 "$HERE/summarize.py" --manifest "$OUT/certs/manifest.json" --out "$dir" \
        --label "$(basename "$dir")" "${logs[@]}"
}

# 1. The matrix: the three stacks, trusted chain, for each Vanetza backend.
for backend in $BACKENDS; do
    echo "== matrix, Vanetza crypto backend: $backend"
    scenario "$OUT/matrix-$backend" "$backend" python rust vanetza
done
# 2. Untrusted chain: the rogue node's messages must be refused by everyone.
#    (Run apart: every receiver keeps requesting the unknown AA, which makes
#    the others include their certificate in every CAM.)
first="${BACKENDS%% *}"
echo "== untrusted chain (rogue), Vanetza crypto backend: $first"
scenario "$OUT/rogue-$first" "$first" python rust vanetza rogue
echo "Results: $OUT"
