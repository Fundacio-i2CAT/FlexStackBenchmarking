# Signed interoperability: FlexStack Python, FlexStack Rust and Vanetza

Three independent C-ITS stacks exchange **signed** CAMs and DENMs (ETSI TS
103 097 V2.2.1 / IEEE 1609.2) over raw Ethernet (EtherType 0x8947), and each
receiver logs the verdict of its own security entity for every packet:

| Node | Stack | Messages |
|---|---|---|
| `python` | FlexStack (Python), `v2xflexstack` from PyPI at the version of `../python/requirements.txt` | CAM by the CA basic service (10 Hz), one new DENM per second |
| `rust` | FlexStack (Rust), `../rust/src/interop_node.rs` on the rustflexstack (crates.io) of `../rust/Cargo.lock` | same |
| `vanetza` | [Vanetza](https://github.com/riebl/vanetza) at a pinned commit, `vanetza_node/` (socktap's link layer, positioning and security set-up, unchanged) | CAM every 100 ms, DENM every second (release 2 messages, Vanetza's ASN.1) |
| `rogue` | FlexStack (Python) with an AT of an **untrusted** Root CA | same as `python` |

All nodes trust only `root_ca` and `aa`; they never preload another node's AT,
so a digest-signed CAM verifies only after the AT was received (signer
certificate, TS 103 097 clause 7.1.1 and P2PCD).

## Run

```bash
interop/build.sh                       # Docker image (Vanetza + node + FlexStack wheel) and the Rust node
interop/run_interop.sh --duration 300  # -> results/interop/<UTC time>/
```

`run_interop.sh` runs, on a private Docker bridge network:

1. `matrix-openssl/`, `matrix-cryptopp/`: `python`, `rust`, `vanetza`, with
   Vanetza's OpenSSL and Crypto++ backends;
2. `rogue-openssl/`: the same plus `rogue`, whose messages every receiver must
   refuse. Run apart because the receivers keep requesting the unknown AA,
   which makes every station include its certificate in each CAM.

Each scenario directory holds the JSON log of every node, `capture.pcap`
(every frame on the bridge) and `matrix.md` / `matrix.csv` / `summary.json`
from `summarize.py`. `certs/` holds the chains of the run (made by
`make_certs.py` with the FlexStack in the image) and `versions.txt` the image,
Vanetza commit and FlexStack versions.

Requirements: Docker (the build uses `--network host`: some Docker set-ups
have no DNS on the default bridge), Rust, Python 3 with pip. Vanetza is
cloned on the host into `~/.cache/flexstack-interop/vanetza` and exported
with `git archive` at `VANETZA_COMMIT`.

## Log format

One JSON object per line on stdout, common to the three nodes:

| `event` | Fields | Meaning |
|---|---|---|
| `start` / `stop` | `stack` | node started / stopped |
| `tx` | `its_aid`, `signer` (`digest` / `certificate`), `at` (HashedId8 of the signing AT), `signed` | a packet left the security entity (forwarded packets keep their originator's `at`) |
| `rx` | `its_aid`, `signer`, `at`, `report` (the stack's own SN-VERIFY report), `verified` | the security entity processed a received secured packet |
| `cam` / `denm` | `station_id`, `protocol_version`, `decoded` | a message reached the CA / DEN service |
| `cam_tx` / `denm_tx` | `accepted` | the application requested a message (Vanetza, FlexStack DENM) |

FlexStack logs `rx` through the GN router's verify observer
(`set_verify_observer`, both stacks); Vanetza through a decorator of its
security entity (`vanetza_node/logging_security_entity.hpp`).

## Reading the matrix

* **Received / Verified**: secured packets the receiver processed and
  accepted. GeoBroadcast DENMs are received several times (forwarded copies,
  CBF re-broadcast); CAMs are single hop.
* **AT not yet known**: digest-signed CAMs that arrived before the receiver
  learned the sender's AT: expected at start-up, a handful per pair.
* **Refused (report)**: every other refusal, with the receiver's report.
* **CAMs verified, not delivered**: verified CAMs the CA service could not
  decode (facility-level interoperability).

## Results with the released versions (2026-11-24, reported in the paper)

Run `results/interop/20261124T091518Z/` (300 s per scenario) with
`v2xflexstack` 0.12.0 and the Rust node on `rustflexstack` 0.4.0. Same
behaviour as the 2026-11-20 run below: in both matrices every directed pair
verifies the other's CAMs (digest and certificate) and DENMs; the refusals are
0 to 2 "AT not yet known" at start-up per pair and, at Vanetza, the Python CAMs
sent right after start-up that carried an `inlineP2pcdRequest` (1 with OpenSSL,
2 with Crypto++; each 30 to 100 ms after the Python node logged
`SIGNER_CERTIFICATE_NOT_FOUND`), finding 2. In `rogue-openssl` FlexStack
Python and Rust refuse every message of the untrusted chain; Vanetza refuses
the rogue CAMs and accepts the rogue DENMs (finding 3), and refuses most
FlexStack CAMs because they carry P2PCD requests for the unknown AA (finding 2).

## Results and findings (2026-11-20, Vanetza 3b9a544)

Final run `results/interop/20261120T191026Z/` (120 s per scenario, after
fixes 1 and 2 below): in `matrix-openssl` and `matrix-cryptopp` every one of
the 6 directed pairs verifies the other's CAMs (digest and certificate signer)
and DENMs: about 1 100 CAMs and 117 to 240 DENMs per sender and pair; the only
refusals are 0 to 2 "AT not yet known" at start-up per pair and, in one of the
two runs, one FalseSignature at Vanetza for a Python CAM (the run had 4 CAMs
carrying an `inlineP2pcdRequest`: finding 2, Vanetza side). In
`rogue-openssl` FlexStack Python and Rust refuse every message of the
untrusted chain (InconsistentChain).

1. **CAM extension containers (fixed in RustFlexstack).** rasn (0.26, still
   in 0.30) drops the constraints of a delegate type encoded as an extension
   addition: Rust wrote `CamParameters.extensionContainers` with the SEQUENCE
   OF count as an unconstrained length, so FlexStack Python could not decode
   Rust CAMs carrying a VeryLowFrequency or TwoWheeler container, and the
   reverse. Fixed by repeating the constraints on the field (also
   `HeaderInfo.pduFunctionalType` in COER); frozen vectors in both stacks.
2. **tbsData of another ASN.1 version (fixed in both FlexStack stacks).**
   Vanetza's IEEE 1609.2 module defines 2 HeaderInfo extension additions,
   the TS 103 097 V2.2.1 one 4, so the canonical extension presence bitmap of
   a CAM carrying `inlineP2pcdRequest` or `requestedCertificate` differs
   (`02 06 80` vs `02 04 80`). Every verifier re-encoded tbsData before
   hashing, so those CAMs failed with FalseSignature in both directions.
   FlexStack now verifies over the octets received when its re-encoding does
   not verify (IEEE 1609.2 clause 6.3.4: the signature covers the encoding the
   signer produced). Vanetza still re-encodes: FlexStack CAMs carrying these
   fields are refused by Vanetza (all rogue-scenario CAMs, where every station
   keeps requesting the unknown AA). A Vanetza limitation, to report upstream.
3. **Chain anchoring in socktap.** socktap's default V3 certificate
   validation (`certificate_validation_v3_strict.cpp`) configures no trust
   store, so Vanetza accepts messages whose chain does not end in a trusted
   Root CA (all rogue DENMs). The message signature itself is checked.
4. **VeryLowFrequency container not decoded by Vanetza (open).** Vanetza
   verifies but cannot decode exactly the FlexStack CAMs carrying a
   VeryLowFrequencyContainer (one every 10 s per station; `decoded: false`).
   FlexStack Python (asn1tools), Rust (rasn, after fix 1) and a hand
   derivation of X.691 agree on these octets (frozen vector
   `cam_with_extension_container_matches_x691` / `FROZEN_VLF_CAM`); the
   decoding of an open type nested in an extension addition by Vanetza's
   asn1c code is the likely cause, not yet confirmed.
