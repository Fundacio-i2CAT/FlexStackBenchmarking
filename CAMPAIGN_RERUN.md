# Re-running the paper campaign (revision 2026-11)

Every number in the revised manuscript must come from the code the paper now
describes. The paper campaign ran on v2xflexstack 0.11.x and the harness
v0.2.4–v0.2.8 binaries; the rerun uses the releases **v2xflexstack 0.12.0**
(PyPI, pinned in `python/requirements.txt`) and **rustflexstack 0.4.0**
(crates.io, `rust/Cargo.toml` / `Cargo.lock`). In between the stacks changed in
ways that move the results:

| Change | Effect on the benchmarks |
|---|---|
| Rust harness: the per-packet `println!` in unsecured TX removed | Rust unsecured TX / concurrent throughput was under-measured |
| Signing input Hash(Hash(tbs) ‖ Hash(signer)), IEEE 1609.2 clause 5.3.1 | one more hash per sign and verify |
| Canonical OER in every FlexStack coder | about 7 µs per encoded signed packet (Python) |
| Beacons signed (ITS-AID 141) when security is on | one extra signature every ~3 s |
| Area CBF: a GBC source re-broadcasts after TO_CBF_MAX | DENMs sent twice in a two-node set-up |
| Received tbsData verified as received when the re-encoding differs (2026-11-20) | no change when sender and receiver use the same ASN.1 (benchmarks); one more verify otherwise |
| Harness v0.2.9: CPU %, RSS, thermal sidecar, fixed-rate mode | new columns and cells (R4-7, R2-2) |

So: rerun **all** cells once, with the same protocol (30 × 60 s runs, warm-up
5 s / 15 s PyPy, cooldown 10 s, `prepare_system.sh`), plus the new fixed-rate
cells. Do it once, after the code is frozen: a later code change means
another rerun.

## 0. Freeze the harness

Commit FlexStackBenchmarking. The stacks are the published releases, so the
manifest records their versions and checksums; for this repository it records
the commit **and** a hash of any uncommitted change (an uncommitted run is
still traceable, but a commit is easier to cite).

## 1. Build the artefacts (controller, ~10 min)

```bash
cd FlexStackBenchmarking
scripts/prepare_campaign.sh          # -> dist/: Rust binaries (x86_64, aarch64), certs, MANIFEST.txt
cat dist/MANIFEST.txt
```

`ansible/setup.yml` installs the Python packages from PyPI
(`python/requirements.txt`) and, with `artifact_source: local` (the default in
`inventory.yml`), the harness binary and certificates of `dist/`. `release`
would download the harness binary of an older GitHub release instead: do not
use it for this campaign. The certificates are made with the pinned FlexStack:
chains made by versions before 0.12.0 no longer verify (signing input change).

## 2. Hosts and set-up

`ansible/inventory.yml`: add the laptop (`laptop:` group) next to
`rpi5-node1`, then:

```bash
cd ansible
ansible-playbook -i inventory.yml setup.yml
```

The summary must show `v2xflexstack 0.12.0` (the version of dist/MANIFEST.txt) for
CPython and PyPy, `Rust: OK` and `Certs: OK` on every host.

## 3. Smoke test (~15 min per host): every cell for 1 run of 5 s

```bash
ansible-playbook -i inventory.yml run.yml -e bench_runs=1 -e bench_duration=5 -e bench_cooldown=1
# wait for "All benchmarks complete" in results/bench_run.log, then:
ansible-playbook -i inventory.yml fetch_results.yml
python3 ../analysis/analyze_results.py -i ../results/<fetched>/results_*.csv
```

Every cell must appear with a non-zero throughput. Delete the smoke-test
files before the real run (or keep them in another folder).

## 4. The weekend run

Order matters: two campaigns on one host at the same time would disturb each
other's measurements.

| Step | Where | Command | Duration (estimate) |
|---|---|---|---|
| A | laptop and RPi5 in parallel | `ansible-playbook -i inventory.yml run.yml` | ~21 h per host (30 cells × 30 runs × ~83 s) |
| B | after A, RPi5 receives, laptop sends | `ansible-playbook -i inventory.yml run_rx.yml --limit "rpi5-node1,laptop-1" -e rx_interface=eth0` and again with `-e rx_security=on` | ~2.1 h each |
| C | after B, laptop receives (same sender as in the paper) | `run_rx.yml --limit "laptop-1,<sender>" -e rx_sender=<sender>` (off, then on) | ~2.1 h each |
| D | MK6 pair, any time (own hardware) | `scripts/run_benchmarks_cohda.sh mk6 30 60` (tx / rx on the two devices, see the script header); build `flexstack-bench-cv2x` against the **same** rustflexstack 0.4.0 | ~6 h |

A covers, per host: TX unsecured / secured, codec encode / decode, sign /
verify at max rate (the paper's cells) and the fixed-rate cells (TX at 10 Hz
unsecured / secured, verify at 100 and 1000 msg/s). The paper's cell list is
in `results/general.csv` (56 cells: laptop 24, RPi5 24, MK6 8).

Progress: `ssh <host> tail -f ~/FlexStackBenchmarking/results/bench_run.log`.
`prepare_system.sh` (called by run.yml) sets the `performance` governor,
disables turbo / SMT and swap and stops the listed services; reboot the hosts
afterwards to restore them.

## 5. Collect and analyse

```bash
ansible-playbook -i inventory.yml fetch_results.yml
python3 analysis/analyze_results.py -i results/<campaign>/results_*.csv --latex --latex-dir results/tables
```

Each `results_*.csv` comes with `_env.txt` (versions, governor, services),
`_thermal.csv` (temperature / frequency / throttling per run) and
`_MANIFEST.txt` (the revision under test). Keep all of them with the data
(`results/` is the source of every number in the paper).

## 6. Signed interoperability (laptop or desktop with Docker, ~10 min)

Independent of the hardware campaign; see `interop/README.md`:

```bash
interop/build.sh
interop/run_interop.sh --duration 300
```
