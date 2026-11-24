# SPDX-License-Identifier: AGPL-3.0-only
"""
Certificate chains for the signed interoperability matrix.

Writes, under ``<out>/``:

* the trusted chain: ``root_ca``, ``aa`` and one Authorization Ticket per node
  (``at_python``, ``at_rust``, ``at_vanetza``);
* an untrusted ("rogue") chain with its own Root CA, AA and ``at_rogue``, used
  by the negative scenario: a correctly signed message whose chain does not
  end in the trusted Root CA must be refused.

Each certificate is written as ``<name>.cert`` (COER, ETSI TS 103 097), its key
as ``<name>.pem`` (PKCS#8, read by FlexStack Python and Vanetza) and
``<name>.key`` (raw 32-byte P-256 scalar, read by FlexStack Rust).

The certificates are made with the FlexStack revision under test; they follow
the profile of the benchmark chain (``python/generate_certs.py``) with explicit
SSPs: CAM BitmapSsp version 3 with every bit of TS 103 900 V2.3.1 Table 3, DENM
BitmapSsp version 2 with every cause code of TS 103 831 V2.3.1 Table 10.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time

from cryptography.hazmat.primitives import serialization

from flexstack.security.certificate import OwnCertificate
from flexstack.security.ecdsa_backend import PythonECDSABackend

ITS_EPOCH = 1072915200  # 2004-01-01T00:00:00Z in Unix seconds (TAI offset ignored)
PSID_CAM, PSID_DENM, PSID_GN_MGMT, PSID_VAM = 36, 37, 141, 638
CAM_SSP = bytes([3, 0xFF, 0xFF])
DENM_SSP = bytes([2, 0xFF, 0xFF, 0xFF, 0xFF])
NODES = ("python", "rust", "vanetza")


def _validity() -> dict:
    # Start one hour in the past so that small clock offsets between the
    # containers cannot make the chain "not yet valid".
    return {"start": int(time.time()) - ITS_EPOCH - 3600, "duration": ("years", 1)}


def _key(name: str) -> tuple:
    return ("verificationKey", ("ecdsaNistP256", ("fill", None)))


def _chain(backend: PythonECDSABackend, label: str, ats: tuple) -> dict:
    root = OwnCertificate.initialize_certificate(
        backend=backend,
        to_be_signed_certificate={
            "id": ("name", f"{label}-root-ca"),
            "cracaId": b"\x00\x00\x00",
            "crlSeries": 0,
            "validityPeriod": _validity(),
            # Root CA -> AA -> AT: two certificates below the Root CA.
            "certIssuePermissions": [{"subjectPermissions": ("all", None), "minChainLength": 2}],
            "verifyKeyIndicator": _key("root"),
        },
        issuer=None,
    )
    aa = OwnCertificate.initialize_certificate(
        backend=backend,
        to_be_signed_certificate={
            "id": ("name", f"{label}-aa"),
            "cracaId": b"\x00\x00\x00",
            "crlSeries": 0,
            "validityPeriod": _validity(),
            # minChainLength 1, chainLengthRange 0 and eeType {app} are the
            # DEFAULTs (IEEE 1609.2 PsidGroupPermissions), hence omitted.
            "certIssuePermissions": [{"subjectPermissions": ("explicit", [
                {"psid": PSID_CAM, "sspRange": ("all", None)},
                {"psid": PSID_DENM, "sspRange": ("all", None)},
                {"psid": PSID_GN_MGMT, "sspRange": ("all", None)},
                {"psid": PSID_VAM, "sspRange": ("all", None)},
            ])}],
            "verifyKeyIndicator": _key("aa"),
        },
        issuer=root,
    )
    out = {"root_ca" if label == "interop" else f"{label}_root_ca": root,
           "aa" if label == "interop" else f"{label}_aa": aa}
    for name in ats:
        out[name] = OwnCertificate.initialize_certificate(
            backend=backend,
            to_be_signed_certificate={
                "id": ("none", None),
                "cracaId": b"\x00\x00\x00",
                "crlSeries": 0,
                "validityPeriod": _validity(),
                "appPermissions": [
                    {"psid": PSID_CAM, "ssp": ("bitmapSsp", CAM_SSP)},
                    {"psid": PSID_DENM, "ssp": ("bitmapSsp", DENM_SSP)},
                    {"psid": PSID_GN_MGMT},
                    {"psid": PSID_VAM},
                ],
                "verifyKeyIndicator": _key(name),
            },
            issuer=aa,
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    backend = PythonECDSABackend()
    certificates = _chain(backend, "interop", tuple(f"at_{n}" for n in NODES))
    certificates.update(_chain(backend, "rogue", ("at_rogue",)))

    manifest = {}
    for name, cert in certificates.items():
        encoded = cert.encode()
        pem = backend.export_signing_key(cert.key_id)
        key = serialization.load_pem_private_key(pem, None)
        pkcs8 = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption())
        scalar = key.private_numbers().private_value.to_bytes(32, "big")
        with open(os.path.join(args.out, f"{name}.cert"), "wb") as handle:
            handle.write(encoded)
        for suffix, data in ((".pem", pkcs8), (".key", scalar)):
            path = os.path.join(args.out, name + suffix)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
        # HashedId8 = last 8 octets of SHA-256 over the COER certificate
        # (TS 103 097 clause 6; all keys are P-256).
        manifest[name] = {"hashedid8": hashlib.sha256(encoded).digest()[-8:].hex(),
                          "hashedid8_check": cert.as_hashedid8().hex()}
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
    for name, item in manifest.items():
        assert item["hashedid8"] == item["hashedid8_check"], name
        print(f"{name:18s} {item['hashedid8']}")


if __name__ == "__main__":
    main()
