#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Build the Vanetza benchmark bundle for this machine's architecture into
# ../dist/vanetza/<arch>/ (Docker, host network). Vanetza is exported from a
# host clone at VANETZA_COMMIT (same pin as ../interop/build.sh).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH="$(cd "$HERE/.." && pwd)"
VANETZA_REPO="${VANETZA_REPO:-https://github.com/riebl/vanetza.git}"
VANETZA_COMMIT="${VANETZA_COMMIT:-3b9a54446685979f467aefbeaaf6065c3c7dd902}"
VANETZA_CACHE="${VANETZA_CACHE:-$HOME/.cache/flexstack-interop/vanetza}"
ARCH="$(uname -m)"
OUT="$BENCH/dist/vanetza/$ARCH"
if [[ ! -d "$VANETZA_CACHE/.git" ]]; then
    mkdir -p "$(dirname "$VANETZA_CACHE")"; git clone --quiet "$VANETZA_REPO" "$VANETZA_CACHE"
fi
git -C "$VANETZA_CACHE" cat-file -e "$VANETZA_COMMIT^{commit}" 2>/dev/null || git -C "$VANETZA_CACHE" fetch --quiet origin
CTX="$(mktemp -d)"; trap 'rm -rf -- "$CTX"' EXIT
mkdir -p "$CTX/vanetza" "$CTX/bench_node"
git -C "$VANETZA_CACHE" archive "$VANETZA_COMMIT" | tar -x -C "$CTX/vanetza"
echo "$VANETZA_COMMIT" > "$CTX/vanetza/VANETZA_COMMIT"
cp "$HERE/bench_main.cpp" "$HERE/CMakeLists.txt" "$CTX/bench_node/"
rm -rf -- "$OUT"; mkdir -p "$OUT"
DOCKER_BUILDKIT=1 docker build --network host -f "$HERE/docker/Dockerfile" --output "type=local,dest=$OUT" "$CTX"
ls -la "$OUT"
