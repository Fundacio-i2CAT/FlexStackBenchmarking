#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Stage the binaries of a GitHub release: the files that were measured in the
# campaign, taken from results/<campaign>/artefacts/ and checked against the
# SHA-256 in its manifests before they are copied (in the Rust binaries only
# the build user name in embedded source paths was overwritten; the manifests
# give the measured and the published SHA-256).
# Nothing is rebuilt here: a rebuild is not byte-identical to the measured
# binaries (build paths, toolchain and library versions are embedded), and the
# Cohda MK6 binaries need the proprietary Qualcomm Telux sysroot, which CI
# does not have. The release workflow runs this script; it can also be run by
# hand to inspect or upload the assets.
#
# Usage: scripts/stage_release.sh [campaign] [out_dir]
#   (defaults: campaign_2026-11, dist/release)
set -euo pipefail

BENCH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAMPAIGN="${1:-campaign_2026-11}"
OUT="${2:-$BENCH/dist/release}"
A="$BENCH/results/$CAMPAIGN/artefacts"

[[ -d "$A" ]] || { echo "no artefacts in $A" >&2; exit 1; }
mkdir -p "$OUT"
if compgen -G "$OUT/*" >/dev/null; then
    echo "$OUT is not empty: pass an empty or new directory" >&2; exit 1
fi

# check <dir> <manifest>: every entry under '## sha256' of the manifest must
# match. A path is looked up in <dir> (the manifest's folder) and, if it is
# not there, in the artefacts folder (the MK6 manifest lists ../../certs as
# certs/); a missing file is an error too.
check() {
    local dir="$1" manifest="$2" n=0 sum path f
    while read -r sum path; do
        if [[ -e "$dir/$path" ]]; then f="$dir/$path"; else f="$A/$path"; fi
        [[ -e "$f" ]] || { echo "missing: $path (listed in $manifest)" >&2; exit 1; }
        [[ "$(sha256sum "$f" | cut -d' ' -f1)" == "$sum" ]] \
            || { echo "checksum mismatch: $f against $manifest" >&2; exit 1; }
        n=$((n + 1))
    done < <(sed -n '/^## sha256/,$p' "$manifest" | grep -E '^[0-9a-f]{64}  ')
    [[ $n -gt 0 ]] || { echo "no checksums in $manifest" >&2; exit 1; }
    echo "verified: ${manifest#"$BENCH"/} ($n files)"
}

# stage <source> <release name>
stage() { cp "$1" "$OUT/$2"; }

# 1. Rust harness of the TX and RX cells (rerun binaries, current rust/ source)
check "$A/bin/rerun_rust_tx" "$A/bin/rerun_rust_tx/MANIFEST.txt"
for arch in x86_64 aarch64; do
    stage "$A/bin/rerun_rust_tx/flexstack-bench-$arch-linux" "flexstack-bench-$arch-linux"
done

# 2. Rust harness of the main campaign (codec, sign and verify cells)
check "$A" "$A/MANIFEST.txt"   # bin/ and certs/
for arch in x86_64 aarch64; do
    stage "$A/bin/flexstack-bench-$arch-linux" "flexstack-bench-$arch-linux-campaign-20261123"
done

# 3. C-V2X harness for the Cohda MK6 variants (built with
#    scripts/build_cv2x_variants.sh; mk6-fw19 is the variant that was measured)
check "$A/bin/mk6" "$A/bin/mk6/MANIFEST.txt"
for v in mk6-fw20 mk6-fw19 mk6c; do
    stage "$A/bin/mk6/flexstack-bench-cv2x-$v" "flexstack-bench-cv2x-$v"
done

# 4. Vanetza harness bundles (own glibc; start with run.sh)
check "$A/bin/vanetza" "$A/bin/vanetza/MANIFEST.txt"
for arch in x86_64 aarch64; do
    stage "$A/bin/vanetza/flexstack-bench-vanetza-$arch-linux.tar.gz" \
          "flexstack-bench-vanetza-$arch-linux.tar.gz"
done

# 5. Certificate chain of the signed benchmarks (test keys only)
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime='2026-11-23 00:00:00Z' \
    -C "$A" -cf - certs | gzip -n -9 > "$OUT/campaign-certs.tar.gz"

chmod 0755 "$OUT"/flexstack-bench-*-linux "$OUT"/flexstack-bench-*-linux-campaign-* \
           "$OUT"/flexstack-bench-cv2x-*
(cd "$OUT" && sha256sum -- * > SHA256SUMS.binaries && cat SHA256SUMS.binaries)
