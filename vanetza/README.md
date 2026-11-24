# Vanetza benchmark harness (WP-D, reviewer comment R2-1)

`flexstack-bench-vanetza` runs the benchmarks of the FlexStack harnesses
(`../rust/src/main.rs`, `../python/benchmark.py`) on
[Vanetza](https://github.com/riebl/vanetza), an independent open-source C++
ETSI C-ITS stack, pinned at commit `3b9a54446685979f467aefbeaaf6065c3c7dd902`
(the same pin as `../interop/`). Same modes, options, CAM and CSV schema
(`implementation` = `vanetza`), so `../analysis/analyze_results.py` reads its
results together with the others.

| Mode | What is timed, per operation |
|---|---|
| `codec-encode` / `codec-decode` | UPER encode / decode of the release-2 CAM (TS 103 900 V2.3.1) |
| `security-sign` | SN-ENCAP of the encoded CAM through Vanetza's security entity (TS 103 097, CAM policy) |
| `security-verify` | decode of the signed message + SN-DECAP |
| `tx` | CAM built and encoded → BTP-B → GeoNetworking SHB → (sign) → raw Ethernet socket |
| `rx` | frame read from the socket → GeoNetworking → (verify) → BTP → CAM decoded; the remote sender is a FlexStack harness in `tx` mode |

Options: `--mode --security --duration --warmup --rate --output --run-id
--platform --interface --certs-dir --at`, as the other harnesses, plus
`--crypto-backend` (default `OpenSSL`).

## Build

```bash
vanetza/build.sh        # -> dist/vanetza/<this machine's arch>/
```

The bundle carries the binary, all its shared libraries including glibc and
its loader, and `run.sh`, which starts the binary through the bundled loader.
It therefore runs on older systems than the build image (Ubuntu 24.04), e.g.
the laptop's Linux Mint 20.3 (glibc 2.31). The aarch64 bundle (RPi5, Jetson)
is built the same way on an aarch64 machine with Docker.

Deployed by `ansible/setup.yml` (tag `vanetza`); `run.yml` and `run_rx.yml`
know the implementation `vanetza`. To add the bundle to a host where a
campaign is running or has results, keep its folder:

```bash
ansible-playbook -i inventory.yml setup.yml --tags vanetza -e setup_clean=false
```

## Equivalence with the FlexStack harnesses

Checked: the same CAM content (41-byte UPER encoding in both), the same
certificate chain (`dist/certs`), and a certificate-signed message of the
same size (270 bytes) for the verify benchmark. Beacons are off in both.

Differences the comparison must state:

* **Codec**: asn1c-generated C (Vanetza) vs rasn (Rust) and asn1tools (Python).
* **Cryptography**: Vanetza's OpenSSL backend (libcrypto 3, optimised P-256)
  vs RustCrypto `p256` (Rust) and `python-ecdsa` (Python). A large part of any
  security-throughput difference is the ECDSA library, not the stack.
* **Verification scope**: one ECDSA verification per message in every
  harness. Vanetza (socktap's default V3 validation) does not verify the
  AT against its AA; FlexStack does not either for an AT it already knows,
  which is the case in its verify benchmark.
* **Threading**: Vanetza's send path is synchronous in one thread (the
  request returns once the frame is handed to the socket); FlexStack Rust
  passes each packet through router and link-layer threads (channels), and
  its TX latency ends when the frame reaches the wire counter. The TX
  latencies have the same start and end points (CAM built → frame handed to
  the socket); the cost of the thread hand-offs is part of what is compared.
* **RX**: in `rx` the receiver is the limit only when its CPU is saturated;
  at low cost per frame (unsecured) the remote sender limits the rate. The
  CPU column tells which case applies.

## Results so far (this desktop, Intel i5-4460, 5 s runs, indicative only)

| Mode | Vanetza | FlexStack Rust |
|---|---:|---:|
| codec-encode | 446,861/s | ~86,000/s |
| codec-decode | 420,103/s | ~314,000/s |
| security-sign | 6,383/s | ~4,550/s |
| security-verify | 4,220/s | ~2,836/s |
| tx unsecured / secured | 88,131 / 5,438/s | ~38,000 / ~3,900/s |
| rx from a FlexStack Rust sender, unsecured / secured | 34,973/s (sender-limited) / 3,644/s | — |

In `rx` secured, Vanetza verified every CAM signed by FlexStack Rust (0 lost
or refused), a further signed-interoperability check.
