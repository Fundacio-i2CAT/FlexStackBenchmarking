#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Build everything the signed interoperability matrix needs:
#   1. the Docker image flexstack-interop:<tag> (Vanetza at a pinned commit +
#      the Vanetza interop node + a venv with FlexStack (Python) at the version
#      pinned in ../python/requirements.txt, wheel from PyPI);
#   2. the FlexStack Rust interop node (cargo, against the rustflexstack of
#      ../rust/Cargo.lock, from crates.io).
#
# Usage: interop/build.sh [--tag TAG]
# Environment:
#   VANETZA_REPO    Vanetza repository                 (default github.com/riebl/vanetza)
#   VANETZA_COMMIT  pinned Vanetza commit              (default below)
#   VANETZA_CACHE   local clone of Vanetza             (default ~/.cache/flexstack-interop/vanetza)
#   PYTHON          Python used to download the wheel  (default python3; needs pip)
#
# Vanetza is cloned on the host and exported with `git archive`, so the image
# build needs no git or TLS access inside Docker. The build uses the host
# network (some Docker set-ups have no DNS on the default bridge).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH="$(cd "$HERE/.." && pwd)"
TAG="dev"
[[ "${1:-}" == "--tag" ]] && TAG="$2"

FLEXSTACK_PIN="$(grep -E '^v2xflexstack==' "$BENCH/python/requirements.txt")"
VANETZA_REPO="${VANETZA_REPO:-https://github.com/riebl/vanetza.git}"
VANETZA_COMMIT="${VANETZA_COMMIT:-3b9a54446685979f467aefbeaaf6065c3c7dd902}"
VANETZA_CACHE="${VANETZA_CACHE:-$HOME/.cache/flexstack-interop/vanetza}"
PYTHON="${PYTHON:-python3}"

echo "== Vanetza $VANETZA_COMMIT"
if [[ ! -d "$VANETZA_CACHE/.git" ]]; then
    mkdir -p "$(dirname "$VANETZA_CACHE")"
    git clone --quiet "$VANETZA_REPO" "$VANETZA_CACHE"
fi
if ! git -C "$VANETZA_CACHE" cat-file -e "$VANETZA_COMMIT^{commit}" 2>/dev/null; then
    git -C "$VANETZA_CACHE" fetch --quiet origin
fi
git -C "$VANETZA_CACHE" cat-file -e "$VANETZA_COMMIT^{commit}"

CTX="$(mktemp -d)"
trap 'rm -rf -- "$CTX"' EXIT
mkdir -p "$CTX/vanetza" "$CTX/wheels"
git -C "$VANETZA_CACHE" archive "$VANETZA_COMMIT" | tar -x -C "$CTX/vanetza"
echo "$VANETZA_COMMIT" > "$CTX/vanetza/VANETZA_COMMIT"
cp -r "$HERE/vanetza_node" "$CTX/vanetza_node"

echo "== FlexStack wheel: $FLEXSTACK_PIN (PyPI)"
"$PYTHON" -m pip download --quiet --no-deps --only-binary :all: --dest "$CTX/wheels" "$FLEXSTACK_PIN"
ls "$CTX/wheels"

echo "== Docker image flexstack-interop:$TAG"
docker build --network host -f "$HERE/docker/Dockerfile" -t "flexstack-interop:$TAG" "$CTX"

echo "== FlexStack Rust interop node"
(cd "$BENCH/rust" && cargo build --release --bin flexstack-interop-node)
ls -la "$BENCH/rust/target/release/flexstack-interop-node"
echo "Done: image flexstack-interop:$TAG, node $BENCH/rust/target/release/flexstack-interop-node"
