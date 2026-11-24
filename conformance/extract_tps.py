#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""
Extract ETSI Test Purposes (TPs) from the "Part 2: Test Suite Structure and
Test Purposes (TSS & TP)" conformance specifications.

The PDFs are not redistributed here (download them free from etsi.org). Each
TP is a table starting with "TP Id"; this script reads, per TP:

    tp_id, objective, reference (base-standard clause), config_id (GN only),
    pics_selection

Usage:
    python3 extract_tps.py <dir with the ETSI PDFs> > test_purposes.csv
    python3 extract_tps.py --with-objectives <dir> > test_purposes_full.csv

By default the TP objective text is left out: the committed CSV carries only
identifiers (TP Id, referenced clause, configuration, PICS), not ETSI prose.
Use --with-objectives for a local, human-readable copy (git-ignored).

Requires `pdftotext` (poppler-utils), used in -raw mode.
"""

import csv
import os
import re
import subprocess
import sys

# TSS & TP documents (Part 2) and the protocol they cover.
DOCUMENTS = {
    "ts_10286802": ("CAM", "ETSI TS 102 868-2"),
    "ts_10286902": ("DEN", "ETSI TS 102 869-2"),
    "ts_10287002": ("BTP", "ETSI TS 102 870-2"),
    "ts_10287102": ("GN", "ETSI TS 102 871-2"),
    "ts_10309602": ("SEC", "ETSI TS 103 096-2"),
    "ts_10352502": ("PKI", "ETSI TS 103 525-2"),
}

# Only the TPs whose IUT is an ITS-S (TS 103 525-2 also specifies the TPs of
# the EA, AA, Root CA, TLM, CPOC and DC, which test a PKI, not the stack).
ID_PREFIX = {"PKI": "SECPKI_ITS-S_"}

FIELD_STARTS = ("Test objective", "Reference", "PICS Selection", "Initial conditions",
                "Expected behaviour")
# TS 103 096-2 (Security) labels the objective "Summary".
OBJECTIVE_LABELS = ("Test objective", "Summary")


def pdf_text(path):
    # -raw keeps content-stream order: a table label comes before its whole
    # (multi-line) cell, unlike -layout, which centres the label vertically.
    return subprocess.run(["pdftotext", "-raw", path, "-"], check=True,
                          capture_output=True, text=True).stdout


# Page furniture that can interrupt a table cell across a page break.
_PAGE_NOISE = re.compile(r"^(ETSI|\d+|ETSI TS \d{3} \d{3}(-\d+)? V\d+\.\d+\.\d+ \(\d{4}-\d{2}\))$")


def _clean(text):
    return re.sub(r"\s+", " ", text).strip()


def parse_tps(text):
    """Yield dicts with tp_id, objective, reference, pics_selection."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^\s*TP Id\s+([\w/.-]+(?: [\w/.-]+){0,2})\s*$", lines[i])
        if not m:
            i += 1
            continue
        # "SECPKI_ITS-S_ BFK_AUTH_01_BV", "SECPKI_ITS-S_ BFK_ AUTH_03_BV", "TP/DEN/ MSGF/BV-01":
        # identifiers split by one or two spaces in the PDF
        tp = {"tp_id": re.sub(r"\s+", "", m.group(1)), "objective": "", "reference": "", "config_id": "",
              "pics_selection": ""}
        field = None
        i += 1
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if (re.match(r"^\s*TP Id\s+\S+", line) or stripped.startswith(FIELD_STARTS[3:])
                    or stripped.startswith(("with {", "with", "ensure that"))):
                break
            label = next((lb for lb in OBJECTIVE_LABELS if stripped.startswith(lb)), None)
            if label:
                field, line = "objective", stripped[len(label):]
            elif stripped.startswith("Reference"):
                field, line = "reference", stripped[len("Reference"):]
            elif stripped.startswith("Config Id"):
                field, line = "config_id", stripped[len("Config Id"):]
            elif stripped.startswith("PICS Selection"):
                field, line = "pics_selection", stripped[len("PICS Selection"):]
            if field and stripped and not _PAGE_NOISE.match(stripped):
                tp[field] += " " + line
            i += 1
        yield {k: _clean(v) for k, v in tp.items()}


def main():
    args = sys.argv[1:]
    with_objectives = "--with-objectives" in args
    args = [a for a in args if a != "--with-objectives"]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    root = args[0]
    fields = ["protocol", "document", "tp_id", "reference", "config_id", "pics_selection"]
    if with_objectives:
        fields.insert(3, "objective")
    writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for dirpath, _, files in os.walk(root):
        for name in sorted(files):
            key = name[:11]
            if key not in DOCUMENTS or not name.endswith(".pdf"):
                continue
            protocol, document = DOCUMENTS[key]
            seen = set()
            for tp in parse_tps(pdf_text(os.path.join(dirpath, name))):
                if tp["tp_id"] in seen or not tp["tp_id"].startswith(ID_PREFIX.get(protocol, "")):
                    continue
                seen.add(tp["tp_id"])
                writer.writerow({"protocol": protocol, "document": document, **tp})


if __name__ == "__main__":
    main()
