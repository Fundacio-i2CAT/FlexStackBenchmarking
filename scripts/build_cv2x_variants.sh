#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Build the C-V2X harness (flexstack-bench-cv2x, rust/src/bench_cv2x.rs) for
# every Cohda MK6 variant that RustFlexstack releases v2x_cli_cv2x for:
#
#   flexstack-bench-cv2x-mk6-fw20  MK6, Quectel AG550 / SA515M, firmware 20 (sysroot-mk6-fw20)
#   flexstack-bench-cv2x-mk6-fw19  MK6, Quectel AG550 / SA515M, firmware 19 (sysroot-mk6)
#   flexstack-bench-cv2x-mk6c      MK6C / MK6 ag15, Qualcomm MDM9150          (sysroot)
#
# The binaries link the Qualcomm Telux libraries of the device dynamically, so
# they are built against the Telux sysroots of RustFlexstack's cohda-toolchain/
# (proprietary, not redistributed: pass their location) and with the cross
# toolchain of the MK6 userland, Ubuntu 20.04 (glibc 2.31, libstdc++ of GCC 9),
# in Docker. rustflexstack comes from crates.io as pinned in rust/Cargo.lock.
# The -rpath-link that rustflexstack's build.rs emits applies only to its own
# examples (cargo does not pass a dependency's rustc-link-arg on), so it is
# given here for the dependent harness, to resolve the Telux libraries' own
# dependencies (libtelux_qmi, libtelux_data, ...) in the sysroot.
#
# Usage: scripts/build_cv2x_variants.sh /path/to/RustFlexstack/cohda-toolchain [out_dir]
# Pick the variant on a device as RustFlexstack's installer does:
#   grep -q Cv2xFactoryImpl /usr/lib/libtelux_cv2x.so            -> mk6-fw20
#   grep -q Cv2xRadio ... && ! grep -q DsiCv2xRadio ...           -> mk6c
#   otherwise                                                     -> mk6-fw19
set -euo pipefail

BENCH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLCHAIN="$(cd "${1:?path to RustFlexstack/cohda-toolchain}" && pwd)"
OUT="$(mkdir -p "${2:-$BENCH/dist/bin}" && cd "${2:-$BENCH/dist/bin}" && pwd)"
IMAGE=flexstack-mk6-cross:20.04

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    docker build -t "$IMAGE" - <<'EOF'
FROM ubuntu:20.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates build-essential pkg-config \
      gcc-aarch64-linux-gnu g++-aarch64-linux-gnu libc6-dev-arm64-cross \
    && rm -rf /var/lib/apt/lists/*
ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo PATH=/opt/cargo/bin:$PATH
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain 1.95.0 \
    && rustup target add aarch64-unknown-linux-gnu
ENV CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc \
    CC_aarch64_unknown_linux_gnu=aarch64-linux-gnu-gcc \
    CXX_aarch64_unknown_linux_gnu=aarch64-linux-gnu-g++ \
    AR_aarch64_unknown_linux_gnu=aarch64-linux-gnu-ar
EOF
fi

for entry in mk6-fw20:sysroot-mk6-fw20 mk6-fw19:sysroot-mk6 mk6c:sysroot; do
    variant="${entry%%:*}" sysroot="${entry##*:}"
    [[ -d "$TOOLCHAIN/$sysroot/include" && -d "$TOOLCHAIN/$sysroot/lib" ]] || {
        echo "missing $TOOLCHAIN/$sysroot/{include,lib}" >&2; exit 1; }
    echo "== $variant ($sysroot)"
    docker run --rm \
        -v "$BENCH/rust:/src:ro" -v "$TOOLCHAIN/$sysroot:/sysroot:ro" -v "$OUT:/out" \
        -v flexstack-mk6-cargo:/opt/cargo/registry \
        -e TELUX_INCLUDE_DIR=/sysroot/include -e TELUX_LIB_DIR=/sysroot/lib \
        -e CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_RUSTFLAGS="-C link-arg=-Wl,-rpath-link,/sysroot/lib" \
        -e OUT_NAME="flexstack-bench-cv2x-$variant" -e OWNER="$(id -u):$(id -g)" \
        "$IMAGE" bash -c '
            set -e
            cargo build --manifest-path /src/Cargo.toml --locked --release \
                --target aarch64-unknown-linux-gnu --features cv2x --bin flexstack-bench-cv2x \
                --target-dir /tmp/target
            aarch64-linux-gnu-strip -o "/out/$OUT_NAME" \
                /tmp/target/aarch64-unknown-linux-gnu/release/flexstack-bench-cv2x
            chown "$OWNER" "/out/$OUT_NAME"'
done
(cd "$OUT" && sha256sum flexstack-bench-cv2x-*)
