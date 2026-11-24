# Test traceability to ETSI conformance test purposes

This folder maps the unit tests of the Python (`v2xflexstack`) and Rust
(`rustflexstack`) stacks to the **Test Purposes (TPs)** of the ETSI
conformance test specifications ("Part 2: TSS & TP"):

| Protocol | Document | TPs |
|---|---|---|
| BTP | ETSI TS 102 870-2 V1.2.1 (2022-03) | 5 |
| GeoNetworking | ETSI TS 102 871-2 V2.1.1 (2026-01) | 138 |
| CA basic service | ETSI TS 102 868-2 V2.1.1 (2025-07) | 32 |
| DEN basic service | ETSI TS 102 869-2 V1.6.1 (2020-04) | 57 |
| Security | ETSI TS 103 096-2 V2.1.1 (2024-08) | 91 |
| PKI (ITS-S) | ETSI TS 103 525-2 V2.1.1 | 76 |

**Scope of the claim.** These are unit tests *traced to* ETSI TPs. They are not
an execution of the ETSI Abstract Test Suites (TTCN-3), and they are not
conformance testing by an accredited test lab. Suggested wording: *"unit tests
traced to ETSI conformance test purposes"*, never "ETSI conformance-tested".

**PKI scope:** only the TS 103 525-2 TPs whose IUT is an ITS-S (`SECPKI_ITS-S_*`: enrolment, authorization, request repetition, CTL / CRL handling and P2P distribution, butterfly). Four identifiers are defined twice in the standard (ENR_REP_05, CRLDIST_02, CRLDIST_04, CRLDIST_06); each has one row and one test covering both texts.

**Not covered and not mapped.** `traceability.md` lists every TP not covered in a stack, grouped by reason (outside the PICS, optional feature not implemented, not implemented), with the reason recorded in `traceability.csv`; `build_matrix.py` fails if a TP that is not covered has no reason. Documents, or parts of them, deliberately left out of the mapping are in `excluded.csv` with their TP count and reason: the PKI-entity TPs of TS 103 525-2 (181; they test a PKI and are run against pythonpki, see `pythonpki/tests/conformance/traceability.md`) and the access-layer DCC TPs of TS 102 917-2 (73). DCC as implemented (TS 102 687 V1.2.1 reactive / adaptive, DCC_NET of TS 103 836-4-2) has no TSS&TP; its unit tests are listed in the DCC section of `traceability.md`.

## Files

| File | Content |
|---|---|
| `extract_tps.py` | Extracts the TPs from the ETSI PDFs (not redistributed; free from etsi.org). |
| `test_purposes.csv` | TP identifiers: protocol, document, TP Id, referenced clause, configuration, PICS. ETSI objective text is not included. |
| `test_purposes_full.csv` | Same, with objectives (`--with-objectives`); local only, git-ignored. |
| `traceability.csv` | **Hand-maintained mapping**: per TP, status and test ids for Python and Rust, plus a note (the reason, for a TP not covered). |
| `excluded.csv` | **Hand-maintained**: TSS&TP documents or parts deliberately not mapped, with TP count and reason. |
| `build_matrix.py` | Validates the mapping and writes `summary.csv`, `tab_traceability.tex` and `traceability.md`. |
| `traceability.md` | Generated: every TP with its referenced clauses, PICS, status and tests per stack, plus the list of open TPs. |

## Status vocabulary

| Status | Meaning |
|---|---|
| `covered` | A unit test asserts the behaviour the TP checks. |
| `partial` | A test exercises the behaviour but not all TP conditions (e.g. header codec only, one case of several, mocked collaborator). |
| `untested` | Implemented, but no unit test. |
| `not_implemented` | The behaviour is not implemented. |
| `not_applicable` | Outside the implementation's PICS (e.g. RSU profile, CAMv1). |

Test ids: Python `tests.flexstack.<package>.<module>.<Class>.<method>`; Rust
`<module path>::<test fn>` (the `tests` sub-module is omitted).

## Usage

```bash
# Re-extract TPs (only when a new TSS&TP version is adopted)
python3 extract_tps.py /path/to/testing_standards > test_purposes.csv
python3 extract_tps.py --with-objectives /path/to/testing_standards > test_purposes_full.csv

# Validate the mapping against both repositories and regenerate the summary
python3 build_matrix.py --python-repo ../../FlexStack --rust-repo ../../RustFlexstack
```

`build_matrix.py` exits non-zero if a TP is unmapped or mapped twice, a status
is inconsistent with its test list, or a referenced test no longer exists. Run
it after renaming or removing tests.
