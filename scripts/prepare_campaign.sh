#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Build the artefacts of a benchmark campaign, so that every host runs the
# same, recorded software: FlexStack (Python) and RustFlexStack at the released
# versions pinned in python/requirements.txt (PyPI) and rust/Cargo.lock
# (crates.io), and the harness of this repository.
#
#   dist/bin/flexstack-bench-<arch>-linux Rust harness, static (musl), per target
#                                         (cross-built with cargo-zigbuild)
#   dist/certs/                           certificate chain made with the pinned FlexStack
#   dist/vanetza/<arch>/                  Vanetza harness bundles (vanetza/build.sh; kept)
#   dist/MANIFEST.txt                     versions (with the PyPI wheel SHA-256 and the
#                                         crates.io checksum), this repository's commit
#                                         + hash of its uncommitted changes, and the
#                                         SHA-256 of every artefact
#
# ansible/setup.yml installs these when artifact_source is "local" (the
# default; the Python packages come from PyPI through python/requirements.txt
# in both modes), and run.yml / run_rx.yml copy MANIFEST.txt next to the results.
#
# Usage: scripts/prepare_campaign.sh
# Environment:
#   TARGETS            Rust targets               (default x86_64 and aarch64 musl)
#   PYTHON             Python >= 3.11 with venv   (default python3)
set -euo pipefail

BENCH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGETS="${TARGETS:-x86_64-unknown-linux-musl aarch64-unknown-linux-musl}"
PYTHON="${PYTHON:-python3}"
DIST="$BENCH/dist"
FLEXSTACK_PIN="$(grep -E '^v2xflexstack==' "$BENCH/python/requirements.txt")"
[[ -n "$FLEXSTACK_PIN" ]] || { echo "python/requirements.txt must pin v2xflexstack==<version>" >&2; exit 1; }

# Only this script's artefacts are rebuilt; dist/vanetza/ (vanetza/build.sh) is kept.
rm -rf -- "$DIST/bin" "$DIST/certs" "$DIST/MANIFEST.txt"
mkdir -p "$DIST/bin" "$DIST/certs"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT

echo "== $FLEXSTACK_PIN (PyPI)"
"$PYTHON" -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install --quiet --upgrade pip
"$WORK/venv/bin/pip" install --quiet -r "$BENCH/python/requirements.txt"
"$WORK/venv/bin/pip" download --quiet --no-deps --dest "$WORK/wheel" "$FLEXSTACK_PIN"

echo "== Certificate chain (python/generate_certs.py with that FlexStack)"
"$WORK/venv/bin/python" "$BENCH/python/generate_certs.py" > "$WORK/certs.log"
cp "$BENCH"/certs/*.cert "$BENCH"/certs/*.pem "$BENCH"/certs/*.key "$DIST/certs/"

echo "== Rust harness (rustflexstack from crates.io, rust/Cargo.lock)"
if grep -q '^\[patch.crates-io\]' "$BENCH/rust/Cargo.toml"; then
    echo "rust/Cargo.toml has a [patch.crates-io] section: remove it to build against crates.io" >&2
    exit 1
fi
# ring (TLS of the PKI client) compiles C: zig (pip ziglang) is the cross C
# compiler and linker for every target, through cargo-zigbuild; no system
# cross toolchain or root needed.
"$WORK/venv/bin/pip" install --quiet ziglang cargo-zigbuild
export PATH="$WORK/venv/bin:$PATH"
for target in $TARGETS; do
    arch="${target%%-*}"
    rustup target list --installed | grep -qx "$target" || rustup target add "$target"
    (cd "$BENCH/rust" && cargo zigbuild --quiet --release --locked \
        --target "$target" --bin flexstack-bench)
    cp "$BENCH/rust/target/$target/release/flexstack-bench" "$DIST/bin/flexstack-bench-$arch-linux"
done

echo "== MANIFEST"
tree_state() {  # tree_state <dir>: commit, number of changed files, hash of the changes
    local dir="$1"
    if git -C "$dir" rev-parse --git-dir >/dev/null 2>&1; then
        local changes
        changes="$( { git -C "$dir" diff HEAD; git -C "$dir" ls-files --others --exclude-standard \
            | while read -r f; do sha256sum "$dir/$f"; done; } | sha256sum | cut -d' ' -f1)"
        echo "commit $(git -C "$dir" rev-parse HEAD), changed files $(git -C "$dir" status --porcelain | wc -l), changes sha256 $changes"
    else
        echo "not a git repository"
    fi
}
{
    echo "# FlexStack benchmark campaign artefacts"
    echo "built_utc: $(date -u +%FT%TZ)"
    echo "built_on: $(uname -srm)"
    echo "flexstack_version: $("$WORK/venv/bin/python" -c 'import importlib.metadata as m; print(m.version("v2xflexstack"))') (PyPI)"
    echo "flexstack_wheel: $(cd "$WORK/wheel" && sha256sum ./*.whl | sed 's| \./| |')"
    echo "rustflexstack: $(awk '/^name = "rustflexstack"$/{f=1} f&&/^version/{v=$3} f&&/^checksum/{print "version " v ", crates.io checksum " $3; exit}' "$BENCH/rust/Cargo.lock" | tr -d '"')"
    echo "flexstack_benchmarking: $(tree_state "$BENCH")"
    echo "rustc: $(rustc -V)"
    echo "python_build: $("$WORK/venv/bin/python" -V)"
    for b in "$DIST"/vanetza/*/VANETZA_COMMIT; do
        [[ -f "$b" ]] && echo "vanetza_$(basename "$(dirname "$b")"): commit $(cat "$b")"
    done
    echo "## sha256"
    (cd "$DIST" && find bin certs vanetza -type f \( -path 'vanetza/*/lib/*' -prune -o -print0 \) 2>/dev/null | sort -z | xargs -0 sha256sum)
} > "$DIST/MANIFEST.txt"
cat "$DIST/MANIFEST.txt"
echo "Artefacts in $DIST"
