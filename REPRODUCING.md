# Reproducing the results of the paper

This guide is for reviewers and readers who want to check the raw data behind
the V2X FlexStack paper, recompute its statistics, or re-run some or all of
the benchmarks. It covers three levels, from minutes to days of work:

| Level | What you get | Time | Needs |
|---|---|---|---|
| [A. Check and re-analyse the raw data](#a-check-and-re-analyse-the-raw-data) | every number of the performance section from the raw runs | minutes | Python 3 with pandas and scipy |
| [B. Re-run one cell](#b-re-run-one-benchmark-cell) | a fresh measurement on your own machine | ~10 min per cell | Linux, root, Python ≥ 3.11, Rust |
| [C. Re-run the campaign](#c-re-run-the-whole-campaign) | the full campaign on your hosts | ~15 h per host | as B, plus Ansible and Docker |

The signed interoperability test and the test-purpose traceability have their
own guides: [`interop/README.md`](interop/README.md) and
[`conformance/README.md`](conformance/README.md).

## Software under test

| Component | Version | Where it comes from |
|---|---|---|
| FlexStack Python | `v2xflexstack` 0.12.0 | PyPI, pinned in `python/requirements.txt` |
| FlexStack Rust | `rustflexstack` 0.4.0 | crates.io, pinned in `rust/Cargo.lock` |
| Vanetza | commit `3b9a54446685979f467aefbeaaf6065c3c7dd902` | GitHub, pinned in `vanetza/build.sh` |
| Harnesses | this repository | `python/benchmark.py`, `rust/src/main.rs`, `vanetza/bench_main.cpp` |

Every results file of the campaign has a `*_MANIFEST.txt` with the SHA-256 of
the FlexStack wheel and the crates.io checksum, so you can confirm that the
packages you install are the ones measured.

## A. Check and re-analyse the raw data

The raw data of the paper is in
[`results/campaign_2026-11/`](results/campaign_2026-11/README.md), with a
description of every file, column, platform and known issue.

```bash
git clone https://github.com/Fundacio-i2CAT/FlexStackBenchmarking
cd FlexStackBenchmarking/results/campaign_2026-11
sha256sum -c SHA256SUMS                 # the files are those of the campaign

cd ../../analysis
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python analyze_results.py --campaign ../results/campaign_2026-11 \
    --output-summary ../results/campaign_2026-11/summary.csv \
    --latex-dir /tmp/tables
```

`analyze_results.py` prints, per cell (platform × implementation × security ×
benchmark × rate): the number of runs, the mean throughput with its 95 %
Student-t confidence interval, the coefficient of variation, the latency
percentiles, CPU and memory, the runs outside Tukey's 1.5 × IQR fences
(flagged, never removed) and the runs whose throttling state changed. The
statistical method is described at the top of the script. `summary.csv` is the
same table in machine-readable form, and `--latex-dir` writes the LaTeX tables
of the paper.

To look at one platform or one file only, pass the files instead:

```bash
.venv/bin/python analyze_results.py --input ../results/campaign_2026-11/raw/rpi5/results_rpi5_*[0-9].csv
```

## B. Re-run one benchmark cell

On any Linux machine (x86-64 or aarch64). Absolute numbers depend on your
processor and its frequency; compare ratios between implementations on the
same machine rather than absolute values with the paper.

```bash
git clone https://github.com/Fundacio-i2CAT/FlexStackBenchmarking
cd FlexStackBenchmarking

# 1. Python stack (CPython; for PyPy, repeat with a PyPy 3.11 venv)
python3 -m venv venv && venv/bin/pip install -r python/requirements.txt

# 2. Rust harness on rustflexstack 0.4.0 (release build, LTO)
(cd rust && cargo build --release --locked)

# 3. Test certificate chain (Root CA, AA, two ATs) in certs/
venv/bin/python python/generate_certs.py

# 4. System preparation: performance governor, no swap, turbo off on x86
sudo scripts/prepare_system.sh laptop     # or rpi3 | rpi5
```

Then run a cell with the protocol of the paper (`--platform` only labels the
rows and accepts `laptop`, `rpi3`, `rpi5`, `agx-orin` or `orin-nano`): pinned to two cores,
real-time round-robin priority, 5 s warm-up (15 s for PyPy), 60 s measured,
repeated (the paper uses 30 runs, 10 s apart):

```bash
for run in $(seq 1 30); do
  sudo timeout -k 10 185 chrt -r 50 taskset -c 2,3 \
    rust/target/release/flexstack-bench --mode security-verify --security on \
    --duration 60 --warmup 5 --run-id "$run" --platform laptop \
    --certs-dir certs --output results/mine.csv
  sleep 10
done

for run in $(seq 1 30); do
  sudo timeout -k 10 185 chrt -r 50 taskset -c 2,3 \
    venv/bin/python python/benchmark.py --mode security-verify --security on \
    --duration 60 --warmup 5 --run-id "$run" --platform laptop \
    --output results/mine.csv
  sleep 10
done

analysis/.venv/bin/python analysis/analyze_results.py --input results/mine.csv
```

To use the binaries and certificates that were measured instead of building
your own, take them from a GitHub release of this repository (each asset is
the measured file, checked against the campaign manifests; in the Rust
binaries only the build user name in embedded source paths is overwritten,
see `artefacts/MANIFEST.txt`; the release notes
list which cells each one measured) or from
`results/campaign_2026-11/artefacts/` (README there), and replace
`--certs-dir certs` by `--certs-dir results/campaign_2026-11/artefacts/certs`
(or the `certs/` of the release's `campaign-certs.tar.gz`):

| Cells | Binary (release asset) |
|---|---|
| Rust TX and RX | `flexstack-bench-<arch>-linux` (`artefacts/bin/rerun_rust_tx/`) |
| Rust codec, sign, verify | `flexstack-bench-<arch>-linux-campaign-20261123` (`artefacts/bin/`) |
| Vanetza, all cells | `flexstack-bench-vanetza-<arch>-linux.tar.gz` (`artefacts/bin/vanetza/`); start `run.sh` |
| Cohda MK6 | `flexstack-bench-cv2x-mk6-fw19` (`artefacts/bin/mk6/`; `-mk6-fw20` and `-mk6c` for the other firmware variants) |

Modes: `codec-encode`, `codec-decode`, `security-sign`, `security-verify`,
`tx`, `rx`; `--security on|off`; `--rate R` for a fixed-rate cell. The exact
command lines of every cell of the paper are in the
`results/campaign_2026-11/raw/<host>/bench_run_*.sh` scripts.

**RX** needs a sender and one or more receivers on one Ethernet segment
with no other traffic. In the paper, a separate x86-64 computer sent with
the Vanetza harness (`run.sh --mode tx`, ~100 k frames/s unsecured, ~9.5 k
signed frames/s secured) while the receivers ran the `rx` cells with
`scripts/run_after.sh --cell '<impl> rx <off|on> 0 30'`; the orchestration
script, its logs and the sender's interface counters are in
`results/campaign_2026-11/rx_sender/` (known issue 12 of the campaign
README). A receiver that reaches the sender rate measures the sender: use a
faster sender, or several, to find its limit.

**Vanetza:** `vanetza/build.sh` builds the harness at the pinned commit in
Docker into `dist/vanetza/<arch>/`, with its own glibc, so the bundle runs on
any Linux of that architecture; run it as above with
`dist/vanetza/<arch>/run.sh` instead of the Rust binary. See
[`vanetza/README.md`](vanetza/README.md) for what it measures and how it
differs from the FlexStack harnesses.

## C. Re-run the whole campaign

[`CAMPAIGN_RERUN.md`](CAMPAIGN_RERUN.md) is the procedure used for the paper:

1. `scripts/prepare_campaign.sh` builds the campaign artefacts into `dist/`
   (static Rust binaries for x86-64 and aarch64, the certificate chain, the
   Vanetza bundles) and writes `dist/MANIFEST.txt`.
2. `ansible/inventory.yml` lists the hosts; the sudo password is read from
   the environment (`export BENCH_BECOME_PASSWORD=...`).
   `ansible-playbook -i ansible/inventory.yml ansible/setup.yml` installs
   everything; `ansible/run.yml` runs the campaign on every host and fetches
   the results with their sidecars.
3. `scripts/run_after.sh` adds cells (the Vanetza cells of the paper) behind
   a running campaign with the same protocol.

A full campaign takes about 15 h on a laptop-class host and longer on the
Raspberry Pi 3.

## What is not reproducible from this repository

- **C-V2X measurements on the Cohda MK6** need two MK6 units. The measured
  binaries run on them as released (`flexstack-bench-cv2x-<variant>`, with
  the Telux libraries of the device firmware); rebuilding them needs the
  Qualcomm Telux sysroots, which are licensed by their vendors
  (`scripts/build_cv2x_variants.sh`). The MK6 cells were run with
  `scripts/run_after.sh --platform mk6 --cell 'rust-cv2x <bench> <off|on> <rate> <runs>'`,
  and the over-the-air RX cells with `results/campaign_2026-11/rx_sender/mk6_ota_rx.sh`.
- **Over-the-air interoperability** with commercial stations needs those
  stations and a licensed radio set-up.
