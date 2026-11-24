# Campaign artefacts

The software that ran on every host of the campaign, as built by
`scripts/prepare_campaign.sh` on 2026-11-23 (see `MANIFEST.txt`, the same file
that sits next to every results CSV in `../raw/`).

| Path | Content |
|---|---|
| `MANIFEST.txt` | versions, PyPI wheel SHA-256, crates.io checksum, harness commit and SHA-256 of every artefact |
| `bin/flexstack-bench-<arch>-linux` | the Rust harness binaries of the main campaign (static musl, rustflexstack 0.4.0): codec, sign and verify cells |
| `bin/rerun_rust_tx/` | the Rust harness binaries with the closed-loop TX warm-up (`MANIFEST.txt` there): the Rust TX reruns (known issue 7) and the Ethernet RX cells (known issue 12) |
| `bin/mk6/` | the C-V2X harness for the three Cohda MK6 variants, built with `scripts/build_cv2x_variants.sh` (`MANIFEST.txt` there); `mk6-fw19` is the one that was measured |
| `bin/vanetza/` | the measured Vanetza harness bundles, packed reproducibly (`MANIFEST.txt` there); unpacked they match `vanetza_bundles.sha256` |
| `certs/` | the certificate chain of the signed benchmarks (Root CA, AA, two ATs). **Test keys only**: they were generated for the benchmark and authorise nothing |
| `vanetza_bundles.sha256` | SHA-256 of every file of the Vanetza harness bundles (`dist/vanetza/<arch>/`); `vanetza/build.sh` rebuilds them from the pinned Vanetza commit, though not byte for byte (Ubuntu package versions change) |

`sha256sum -c ../SHA256SUMS` checks these files too. With them, a re-run uses
the measured binaries and produces signed messages with exactly the
certificates of the paper (`--certs-dir results/campaign_2026-11/artefacts/certs`).

Every GitHub release publishes these files unchanged, under the names of
`scripts/stage_release.sh`, which checks each one against its manifest first.
Which binary produced which rows is in the `rust_bin_sha256` line of the
`*_env.txt` next to every results CSV: that is the measured SHA-256. In the
four FlexStack Rust binaries stored here, the build user name inside the 76–77
Cargo source paths compiled in for panic messages was overwritten with `x` of
the same length before publication; no other byte differs, and writing the
name back gives the measured file again. `MANIFEST.txt` and
`bin/rerun_rust_tx/MANIFEST.txt` map each measured SHA-256 to the published
one. The MK6 and Vanetza binaries are unmodified.
