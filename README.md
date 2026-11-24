# FlexStack Benchmarking Suite

Rigorous benchmarking harness for [V2X FlexStack](https://flexstack.eu/) performance evaluation across Python (CPython, PyPy) and Rust implementations.


## Reproducing the paper

The raw data of every benchmark run reported in the V2X FlexStack paper is in
[`results/campaign_2026-11/`](results/campaign_2026-11/README.md), with the
exact commands each host executed, the environment and thermal record of every
run, and checksums. [`REPRODUCING.md`](REPRODUCING.md) explains how to verify
and re-analyse that data, how to re-run a single benchmark cell on your own
machine, and how to repeat the whole campaign.

## Project Structure

```
FlexStackBenchmarking/
├── python/                 # Python harness (CPython + PyPy), certificate generator
├── rust/                   # Rust harness (rustflexstack), C-V2X variant, interop node
├── vanetza/                # Vanetza harness (same benchmarks on Vanetza, Docker build)
├── scripts/                # system preparation, campaign build, orchestrators, monitoring
├── ansible/                # multi-host set-up and campaign playbooks
├── analysis/               # statistical analysis, LaTeX tables, plots
├── interop/                # signed interoperability test (FlexStack Python, Rust, Vanetza)
├── conformance/            # traceability of the unit tests to ETSI test purposes
├── results/
│   ├── campaign_2026-11/   # raw data of the paper (see its README)
│   ├── interop/            # signed interoperability runs (captures, verdicts)
│   └── archive/            # earlier campaigns on pre-release versions, not used in the paper
├── REPRODUCING.md          # how to check, re-analyse and re-run
├── CAMPAIGN_RERUN.md       # the procedure used for the 2026-11 campaign
└── README.md               # this file
```

## Benchmark Matrix

| ID | Benchmark | Security | Platforms | Implementations |
|----|-----------|----------|-----------|-----------------|
| B1 | Full-stack TX throughput | Off + On | Laptop, RPi3, RPi5 | CPython, PyPy, Rust |
| B2 | Full-stack RX throughput | Off + On | Laptop, RPi3, RPi5 | CPython, PyPy, Rust |
| B3 | Concurrent TX/RX throughput | Off + On | Laptop, RPi3, RPi5 | CPython, PyPy, Rust |
| B4 | ASN.1 Codec (encode + decode) | N/A | Laptop, RPi3, RPi5 | CPython, PyPy, Rust |
| B5 | Security Layer (sign + verify) | N/A | Laptop, RPi3, RPi5 | CPython, PyPy, Rust |

Each cell: **30 independent runs × 60s measurement** with warm-up discard (5s CPython/Rust, 15s PyPy).

## Quick Start

### 1. Prerequisites

#### Python

```bash
# CPython 3.13
pip install -r python/requirements.txt     # v2xflexstack (pinned, PyPI) + numpy

# PyPy (optional)
pypy3 -m pip install -r python/requirements.txt
```

#### Rust Binary

The fastest way to get started is to download the pre-built binary directly from the latest GitHub release — no Rust toolchain required. The release binaries are the files measured in the paper campaign (in the Rust ones only the build user name in embedded source paths is overwritten; see the release notes for which cells each one measured; the Vanetza bundles and the Cohda MK6 C-V2X binaries `flexstack-bench-cv2x-mk6-fw19|mk6-fw20|mk6c` are attached too):

```bash
wget https://github.com/Fundacio-i2CAT/FlexStackBenchmarking/releases/latest/download/flexstack-bench-$(uname -m)-linux
chmod +x flexstack-bench-$(uname -m)-linux
./flexstack-bench-$(uname -m)-linux --help
```

The `$(uname -m)` shell substitution resolves automatically to your CPU architecture — `x86_64` on a laptop/desktop or `aarch64` on a Raspberry Pi 4/5. No cross-compilation or Rust toolchain needed.

Alternatively, build from source:

```bash
cd rust && cargo build --release
# Binary: rust/target/release/flexstack-bench
```

### 2. Generate Certificates (for secured benchmarks)

```bash
cd python
python3 generate_certs.py
```

This creates an ECDSA-P256 certificate chain under `certs/` (Root CA → AA → AT1, AT2) used by both Python and Rust benchmarks:

- `*.cert`: COER-encoded ETSI TS 103 097 certificates
- `*.pem`: PEM private keys (Python harness)
- `*.key`: the same keys as raw 32-byte P-256 scalars (Rust harness, `import_signing_key`)

Generate the chain with the pinned FlexStack: from `v2xflexstack` 0.12.0 / `rustflexstack` 0.4.0 on, messages and certificates are signed over Hash(Hash(data) ‖ Hash(signer)) (IEEE 1609.2 clause 5.3.1), so chains and stations of earlier versions do not interoperate with them. Copy the same `certs/` directory to every host so that sender and receiver share one trust chain.

### 3. Run Individual Benchmarks

```bash
# Python TX benchmark (unsecured, loopback)
sudo python3 python/benchmark.py --mode tx --security off --duration 60

# Python TX benchmark (secured)
sudo python3 python/benchmark.py --mode tx --security on --duration 60 --warmup 5

# PyPy TX benchmark (15s JIT warm-up)
sudo pypy3 python/benchmark.py --mode tx --security off --duration 60 --warmup 15

# Rust TX benchmark — using pre-built binary (replace arch as needed)
sudo ./flexstack-bench-$(uname -m)-linux --mode tx --security off --duration 60

# Rust TX benchmark — using locally compiled binary
sudo rust/target/release/flexstack-bench --mode tx --security off --duration 60

# Rust TX benchmark (secured, using AT1 certificate)
sudo ./flexstack-bench-$(uname -m)-linux --mode tx --security on --certs-dir certs --at 1 --duration 60

# Codec benchmarks (no sudo needed)
python3 python/benchmark.py --mode codec-encode --duration 60
./flexstack-bench-$(uname -m)-linux --mode codec-decode --duration 60
```

### 4. Run Full Benchmark Suite

```bash
# Prepare system (disable turbo boost, lock CPU freq, etc.)
sudo scripts/prepare_system.sh laptop

# Run all benchmarks (3 impl × 2 security × 4 modes × 30 runs)
sudo scripts/run_benchmarks.sh laptop 30 60
```

### 4b. Run via Ansible (remote hosts)

```bash
cd ansible

# 1. Edit inventory.yml — add your hosts and tune benchmark parameters
#    (bench_runs, bench_duration, bench_cores, bench_modes, etc.)

# 2. Install dependencies on all hosts
ansible-playbook -i inventory.yml setup.yml

# 3. Run benchmarks and fetch results back to ./results/
ansible-playbook -i inventory.yml run.yml

# Selective setup (only install PyPy, or only Rust binary):
ansible-playbook -i inventory.yml setup.yml --tags pypy
ansible-playbook -i inventory.yml setup.yml --tags rust
```

### 5. Analyze Results

```bash
cd analysis
pip install -r requirements.txt

# Summary table + speedup ratios
python3 analyze_results.py --input ../results/results_laptop_*.csv

# With LaTeX table output
python3 analyze_results.py --input ../results/results.csv --latex

# Paper campaign: summary with latency CIs + TX/RX latency tables (p50/p95/p99 ± 95% CI)
python3 analyze_results.py --input ../results/general.csv \
    --output-summary ../results/out.csv --latex-dir ../results/tables
```

Statistics: every cell value is the mean of the N per-run values (throughput, latency
mean, p50, p95, p99) with a two-sided Student-t 95% confidence interval (df = N − 1).
Runs outside Tukey's 1.5·IQR fences are listed as diagnostics together with how much
excluding them would change each mean, but no run is ever removed.

```bash

# Generate plots
python3 generate_plots.py --input ../results/results.csv
```

## Benchmark Modes

### `--mode tx` (B1: Full-Stack TX Throughput)

Measures CAM generation rate through the complete stack: CA Service → BTP → GeoNetworking → loopback interface. Bypasses the ETSI 100ms rate limiter to measure maximum software processing throughput.

### `--mode rx` (B2: Full-Stack RX Throughput)

Receive-only mode: listens on the network interface for incoming CAMs sent by a remote sender (e.g. another machine running `--mode tx`). No internal TX stack is spawned. Measures per-packet RX decode latency and throughput.

Cross-machine example:
```bash
# Machine A (sender)
sudo ./flexstack-bench --mode tx --interface eth0 --duration 70
# Machine B (receiver)
sudo ./flexstack-bench --mode rx --interface eth0 --duration 60
```

### `--mode concurrent` (B3: Concurrent TX/RX)

Simultaneous TX and RX. TX generates CAMs at maximum rate while RX decodes incoming loopback packets. Simulates a real ITS station processing both directions.

### `--mode codec-encode` / `--mode codec-decode` (B4: ASN.1 Codec)

In-memory UPER encode/decode of CAM messages. No networking involved. Measures pure ASN.1 processing throughput.

### `--mode security-sign` / `--mode security-verify` (B5: Security Layer)

In-memory ECDSA-P256 signing or verification of a CAM-sized payload. No networking involved. Measures pure cryptographic throughput of the security layer.

### Fixed-rate mode (`--rate R`)

All modes above run as fast as possible by default, so CPU utilisation is that of
a saturated stack. `--rate R` (msg/s) instead releases message *i* at
`start + i/R` and **sleeps** in between, so `cpu_pct` is the cost of handling R
messages per second: the CPU and memory needed at a realistic load. It applies to
`tx`, `concurrent`, `codec-*` and `security-*` (Rust: `rust/src/pacing.rs`,
Python: `Pacer` in `python/benchmark.py`). A late message is released at once and
counted, never bursted to catch up, so an implementation that cannot keep up shows
an achieved throughput below R. `analyze_results.py` flags such cells (< 98 %).

`rx` is never paced, because the remote sender sets the load. Pace the sender and
label the receiver with the same rate:

```bash
# sender (e.g. laptop): secured CAMs at 1000 msg/s = 100 neighbours at 10 Hz
sudo ./send_packets_for_rx_benchmarks.sh eth0 7200 on 1000
# receiver (device under test), 5th argument = sender rate
sudo ./run_rx_benchmarks.sh rpi5 10 60 eth0 1000
```

Single-machine sweep (TX unsecured/secured and in-memory verification, all
implementations; default rates 10, 100 and 1000 msg/s):

```bash
sudo ./prepare_system.sh rpi5          # 'performance' governor is essential here
sudo ./run_rate_benchmarks.sh rpi5 10 60          # or: ... 10 60 10 100 1000 2000
```

Use the `performance` governor (`prepare_system.sh`). Otherwise the CPU clocks down
between paced messages and every operation becomes slower; the script warns about
this. The remaining extra per-message cost at low rates (wake-up from idle, cold
caches) is real and part of what the mode measures.

The rate is recorded in the `target_rate` column (0 = max rate) and in the
thermal sidecar. With Ansible, add `rate:` to a `bench_modes` cell
(`inventory.yml`) or pass `-e rx_rate=N` to `run_rx.yml`.

## CLI Interface

Both Python and Rust benchmarks share the same CLI:

```
flexstack-bench / benchmark.py [OPTIONS]

OPTIONS:
  --mode <tx|rx|concurrent|codec-encode|codec-decode|security-sign|security-verify>  Benchmark mode
  --security <off|on>                                  ECDSA-P256 security
  --duration <seconds>                                 Measurement time [60]
  --warmup <seconds>                                   Warm-up discard [5]
  --output <csv_path>                                  CSV output file
  --run-id <integer>                                   Run identifier
  --platform <laptop|rpi3|rpi5>                        Platform tag
  --interface <iface>                                  Network interface [lo]
  --certs-dir <path>       (Rust) Path to certificate directory [certs]
  --at <1|2>               (Rust) Authorization Ticket index to use [1]
```

## CSV Output Format

Each run appends one row:

```
run_id, implementation, platform, security, benchmark, duration_s, total_cams,
throughput_cams_s, latency_mean_us, latency_std_us, latency_p50_us, latency_p95_us,
latency_p99_us, latency_min_us, latency_max_us, sign_latency_mean_us,
cpu_pct, rss_start_mb, peak_rss_mb, target_rate
```

- `sign_latency_mean_us`: mean ECDSA sign time (`security-sign`), verify time
  (`security-verify`) or, for secured `rx`, the mean verify time inside the stack.
- `cpu_pct`: process user + system CPU time during the measurement window divided
  by its wall time × 100 (100 = one core busy; max 100 × pinned cores). The
  benchmarks run at maximum rate, so this describes a saturated stack.
- `rss_start_mb`: resident memory when the measurement window opens (stack
  initialised and warmed up, before any latency sample is stored), i.e. the
  stack's footprint.
- `target_rate`: `--rate` in msg/s (0 = as fast as possible; for `rx`, the
  remote sender's rate).
- `peak_rss_mb`: VmHWM. Includes the harness's latency sample buffer, so it is
  an upper bound.

Rust and Python read the same `/proc/self` counters (`rust/src/resources.rs`,
`ResourceSnapshot` in `python/benchmark.py`). A run refuses to append to an
existing CSV with an older header (since harness v0.2.9).

Alongside each results file, the orchestrators (shell scripts and Ansible) write:

- `<results>_env.txt`: kernel, CPU, governor, turbo/SMT, swap, running services,
  interpreter / `v2xflexstack` / crate versions, Rust binary size and SHA-256,
  installed package size.
- `<results>_thermal.csv`: per run, SoC temperature, CPU frequency and
  throttling state before and after (`vcgencmd get_throttled` on Raspberry Pi,
  `core_throttle_count` on x86). `analyze_results.py` joins it automatically
  and lists runs whose throttling state changed; they are kept, not removed.

## Statistical Methodology

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Runs per cell | 30 | CLT-based CI estimation |
| Duration | 60s | Amortize startup transients |
| Cool-down | 10s | Prevent thermal throttling carryover |
| PyPy warm-up | 15s | Conservative JIT compilation margin |
| CPython/Rust warm-up | 5s | OS scheduler settling |

**Reported statistics per cell:**
- Mean ± std deviation
- 95% CI (Student-t: $\bar{x} \pm t_{0.025,29} \cdot s/\sqrt{n}$, where $t_{0.025,29} = 2.045$)
- Percentiles: p50, p95, p99
- Coefficient of variation (flagged if CV > 5%)

## System Preparation

Applied before every benchmark session (documented in paper):

| Setting | Laptop | RPi3/RPi5 |
|---------|--------|-----------|
| CPU governor | `performance` | `performance` |
| Turbo Boost | Disabled | N/A |
| Process pinning | `taskset -c 2,3` | `taskset -c 2,3` |
| RT priority | `chrt -r 50` (SCHED_RR; SCHED_FIFO starved stack threads on two pinned cores, 2026-11-23) | `chrt -r 50` |
| Swap | Disabled | Disabled |
| Background services | Stopped | Stopped |

## Cross-Compilation (RPi3/RPi5)

```bash
# Rust cross-compilation for aarch64
cd rust
rustup target add aarch64-unknown-linux-gnu
cargo build --release --target aarch64-unknown-linux-gnu
# Binary at: target/aarch64-unknown-linux-gnu/release/flexstack-bench
```

## Software Versions

| Component | Version |
|-----------|---------|
| Python FlexStack | pinned in `python/requirements.txt` |
| Rust FlexStack | pinned in `rust/Cargo.toml` / `Cargo.lock` |
| CPython | 3.13 |
| PyPy | 3.11 |
| Rust | stable (1.75+), `--release`, LTO |

The exact versions used in a campaign are recorded in its `<results>_env.txt`.

## License

AGPL-3.0 — See individual source files for copyright notices.

## Citation

If you use this benchmarking suite, please cite:
- Python FlexStack: https://github.com/Fundacio-i2CAT/FlexStack
- Rust FlexStack: https://github.com/Fundacio-i2CAT/RustFlexstack
