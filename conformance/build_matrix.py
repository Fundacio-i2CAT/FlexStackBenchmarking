#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""
Validate the test-to-TP traceability mapping and summarise it.

Inputs (this directory):
  test_purposes.csv   TP identifiers extracted by extract_tps.py
  traceability.csv    hand-maintained mapping: tp_id, py_status, py_tests,
                      rs_status, rs_tests, note
  excluded.csv        hand-maintained list of the TSS&TP documents (or parts)
                      deliberately left out of the mapping, with the reason

Checks (non-zero exit on any failure):
  * every TP has exactly one mapping row, and no row names an unknown TP;
  * statuses are valid; covered/partial rows list tests, the others list none;
  * every referenced test exists in the Python (FlexStack/tests) and Rust
    (RustFlexstack/src, #[test] functions) repositories;
  * every TP not covered in a stack states why (note);
  * every excluded document gives its TP count and the reason.

Outputs:
  summary.csv         counts per protocol x status x implementation
  tab_traceability.tex LaTeX table of the same counts
  traceability.md     every TP with its referenced clauses, status and tests
                      (ETSI objective text is not reproduced)

Status vocabulary:
  covered          a unit test asserts the behaviour the TP checks
  partial          a test exercises the behaviour but not all TP conditions
                   (e.g. header-codec level, or one case of several)
  untested         implemented, but no unit test
  not_implemented  the behaviour is not implemented
  not_applicable   outside the implementation's PICS (e.g. RSU-only, CAMv1)

These are unit tests *traced to* ETSI conformance test purposes; they are not
an execution of the ETSI abstract test suites (TTCN-3) and do not amount to
conformance testing by an accredited test lab.

Usage:
  python3 build_matrix.py --python-repo ../../FlexStack --rust-repo ../../RustFlexstack
"""

import argparse
import ast
import collections
import csv
import os
import re
import sys

STATUSES = ("covered", "partial", "untested", "not_implemented", "not_applicable")
WITH_TESTS = ("covered", "partial")
PROTOCOL_ORDER = ("BTP", "GN", "CAM", "DEN", "SEC", "PKI")
HERE = os.path.dirname(os.path.abspath(__file__))


def python_tests(repo):
    """{id: source}, ids tests.flexstack.<pkg>.<module>.<Class>.<method>; the
    source is the test function with its docstring."""
    found = {}
    root = os.path.join(repo, "tests")
    for dirpath, _, files in os.walk(root):
        for name in files:
            if not (name.startswith("test_") and name.endswith(".py")):
                continue
            path = os.path.join(dirpath, name)
            module = os.path.relpath(path, repo)[:-3].replace(os.sep, ".")
            text = open(path, encoding="utf-8").read()
            tree = ast.parse(text)
            for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
                for fn in cls.body:
                    if isinstance(fn, ast.FunctionDef) and fn.name.startswith("test"):
                        found[f"{module}.{cls.name}.{fn.name}"] = ast.get_source_segment(text, fn) or ""
    return found


def _rust_fn_source(lines, test_line, fn_line):
    """Doc comments / attributes above ``#[test]`` and the function up to its closing brace."""
    start = test_line
    while start > 0 and re.match(r"\s*(///|//|#\[)", lines[start - 1]):
        start -= 1
    depth, end, opened = 0, fn_line, False
    for end in range(fn_line, len(lines)):
        depth += lines[end].count("{") - lines[end].count("}")
        opened = opened or "{" in lines[end]
        if opened and depth <= 0:
            break
    return "\n".join(lines[start:end + 1])


def rust_tests(repo):
    """{id: source}, ids <module path>::<fn>, e.g.
    btp::router::btpa_request_produces_gn_request (the `tests` sub-module name
    is omitted); the source is the function with its doc comments."""
    found = {}
    root = os.path.join(repo, "src")
    for dirpath, _, files in os.walk(root):
        for name in files:
            if not name.endswith(".rs"):
                continue
            path = os.path.join(dirpath, name)
            module = os.path.relpath(path, root)[:-3].replace(os.sep, "::")
            module = re.sub(r"(^|::)mod$", "", module)
            lines = open(path, encoding="utf-8").read().splitlines()
            for i, line in enumerate(lines):
                if line.strip() != "#[test]":
                    continue
                for j in range(i + 1, min(i + 4, len(lines))):
                    m = re.match(r"\s*(?:async\s+)?fn\s+(\w+)", lines[j])
                    if m:
                        found[f"{module}::{m.group(1)}"] = _rust_fn_source(lines, i, j)
                        break
    return found


# Protocols whose tests have been audited TP by TP: every test listed for a
# TP quotes the TP identifier, and every test quoting a TP identifier is
# listed for it.
TAGGED_PROTOCOLS = ("BTP", "CAM", "DEN", "GN", "SEC", "PKI")


def _mentions(source, tp_id):
    return re.search(re.escape(tp_id) + r"(?![\w-])", source) is not None


def validate_tags(tps, mapping, py_found, rs_found, protocols=TAGGED_PROTOCOLS):
    """Errors for the tagged protocols, and the untagged pairs of the others."""
    errors, pending = [], collections.Counter()
    protocol = {t["tp_id"]: t["protocol"] for t in tps}
    listed = {}
    for m in mapping:
        for impl, found in (("py", py_found), ("rs", rs_found)):
            for test in split_tests(m[f"{impl}_tests"]):
                listed.setdefault((impl, test), set()).add(m["tp_id"])
                if test in found and not _mentions(found[test], m["tp_id"]):
                    if protocol[m["tp_id"]] in protocols:
                        errors.append(f"{m['tp_id']}: {impl} test {test} does not quote the TP identifier")
                    else:
                        pending[protocol[m["tp_id"]]] += 1
    tagged_ids = [t for t in protocol if protocol[t] in protocols]
    for impl, found in (("py", py_found), ("rs", rs_found)):
        for test, source in found.items():
            for tp_id in tagged_ids:
                if _mentions(source, tp_id) and tp_id not in listed.get((impl, test), set()):
                    errors.append(f"{tp_id}: {impl} test {test} quotes the TP but is not listed for it")
    return errors, pending


def read_csv(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def split_tests(field):
    return [t.strip() for t in field.split(";") if t.strip()]


def validate(tps, mapping, py_found, rs_found):
    errors = []
    tp_ids = [t["tp_id"] for t in tps]
    rows = collections.Counter(m["tp_id"] for m in mapping)
    for tp in tp_ids:
        if rows[tp] != 1:
            errors.append(f"{tp}: {rows[tp]} mapping rows (expected 1)")
    for tp in set(rows) - set(tp_ids):
        errors.append(f"{tp}: mapping row for an unknown TP")
    for m in mapping:
        for impl, found in (("py", py_found), ("rs", rs_found)):
            status, tests = m[f"{impl}_status"], split_tests(m[f"{impl}_tests"])
            if status not in STATUSES:
                errors.append(f"{m['tp_id']}: invalid {impl}_status '{status}'")
            if status in WITH_TESTS and not tests:
                errors.append(f"{m['tp_id']}: {impl}_status {status} but no tests listed")
            if status not in WITH_TESTS and tests:
                errors.append(f"{m['tp_id']}: {impl}_status {status} must not list tests")
            for t in tests:
                if t not in found:
                    errors.append(f"{m['tp_id']}: {impl} test not found: {t}")
            if status != "covered" and not m["note"].strip():
                errors.append(f"{m['tp_id']}: {impl}_status {status} needs a note saying why")
    return errors


def validate_excluded(excluded):
    errors = []
    for e in excluded:
        if not e["document"].strip() or not e["reason"].strip() or not e["tps"].isdigit():
            errors.append(f"excluded.csv: incomplete row for {e['document']!r}")
    return errors


# Why a TP is not covered, from its status and note (traceability.md, "Not covered").
def category(m):
    status = m["py_status"] if m["py_status"] != "covered" else m["rs_status"]
    note = m["note"].lower()
    if status == "not_applicable":
        return "Outside the PICS of these implementations"
    if "optional" in note:
        return "Optional feature, not implemented"
    return "Not implemented"


def summarise(tps, mapping):
    protocol = {t["tp_id"]: t["protocol"] for t in tps}
    counts = collections.Counter()
    for m in mapping:
        for impl in ("py", "rs"):
            counts[(protocol[m["tp_id"]], impl, m[f"{impl}_status"])] += 1
    return counts


def write_outputs(counts, tps):
    totals = collections.Counter(t["protocol"] for t in tps)
    with open(os.path.join(HERE, "summary.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["protocol", "implementation", "tps", *STATUSES])
        for p in PROTOCOL_ORDER + ("ALL",):
            for impl in ("py", "rs"):
                if p == "ALL":
                    row = [sum(counts[(q, impl, s)] for q in PROTOCOL_ORDER) for s in STATUSES]
                    n = sum(totals.values())
                else:
                    row = [counts[(p, impl, s)] for s in STATUSES]
                    n = totals[p]
                w.writerow([p, "python" if impl == "py" else "rust", n, *row])

    names = {"BTP": "BTP", "GN": "GeoNetworking", "CAM": "CA basic service",
             "DEN": "DEN basic service", "SEC": "Security", "PKI": "PKI (ITS-S)"}
    lines = [
        r"\begin{table}[t]",
        r"    \centering",
        r"    \caption{Unit tests traced to ETSI conformance test purposes (TPs), "
        r"per protocol, for the Python (Py) and Rust (Rs) implementations. "
        r"Cov.: a unit test asserts the TP's expected behaviour; Part.: exercised, "
        r"not all TP conditions; Untest.: implemented, no unit test; N/I: not "
        r"implemented; N/A: outside the implementation's PICS. These are unit tests "
        r"traced to TPs, not an execution of the ETSI abstract test suites.}",
        r"    \label{tab:tp_traceability}",
        r"    \setlength{\tabcolsep}{3pt}",
        r"    \adjustbox{max width=\columnwidth}{%",
        r"    \begin{tabular}{l r l r r r r r}",
        r"        \toprule",
        r"        \textbf{Protocol (TSS\&TP)} & \textbf{TPs} & & \textbf{Cov.} & "
        r"\textbf{Part.} & \textbf{Untest.} & \textbf{N/I} & \textbf{N/A} \\",
        r"        \midrule",
    ]
    for p in PROTOCOL_ORDER + ("ALL",):
        for k, impl in enumerate(("py", "rs")):
            if p == "ALL":
                vals = [sum(counts[(q, impl, s)] for q in PROTOCOL_ORDER) for s in STATUSES]
                label, n = r"\textbf{Total}", sum(totals.values())
            else:
                vals = [counts[(p, impl, s)] for s in STATUSES]
                label, n = names[p], totals[p]
            first = f"{label} & {n}" if k == 0 else " & "
            lines.append(f"        {first} & {'Py' if impl == 'py' else 'Rs'} & "
                         + " & ".join(str(v) for v in vals) + r" \\")
        lines.append(r"        \midrule" if p != "SEC" else r"        \midrule")
    lines[-1] = r"        \bottomrule"
    lines += [r"    \end{tabular}", r"    }", r"\end{table}"]
    with open(os.path.join(HERE, "tab_traceability.tex"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


DOCUMENTS = {
    "BTP": ("BTP", "ETSI TS 102 870-2 V1.2.1 (2022-03)", "ETSI EN 302 636-5-1"),
    "GN": ("GeoNetworking", "ETSI TS 102 871-2 V2.1.1 (2026-01)", "ETSI TS 103 836-4-1 V2.2.1"),
    "CAM": ("CA basic service", "ETSI TS 102 868-2 V2.1.1 (2025-07)", "ETSI TS 103 900 V2.3.1"),
    "DEN": ("DEN basic service", "ETSI TS 102 869-2 V1.6.1 (2020-04)", "ETSI TS 103 831 V2.3.1"),
    "SEC": ("Security", "ETSI TS 103 096-2 V2.1.1 (2024-08)",
            "ETSI TS 103 097 V2.2.1 and IEEE Std 1609.2-2016"),
    "PKI": ("PKI (ITS-S)", "ETSI TS 103 525-2 V2.1.1",
            "ETSI TS 102 941 V2.2.1 and ETSI TS 103 601 V2.1.1"),
}
LABELS = {"covered": "covered", "partial": "partial", "untested": "untested",
          "not_implemented": "not implemented", "not_applicable": "N/A"}


def _md(text):
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _md_tests(status, field):
    tests = split_tests(field)
    label = f"**{LABELS[status]}**" if status != "covered" else LABELS[status]
    return "<br>".join([label] + [f"`{t}`" for t in tests])


# Unit tests of DCC (no TSS&TP mapped): Python modules and Rust module paths.
DCC_PY = ("tests.flexstack.management.test_dcc_reactive.", "tests.flexstack.management.test_dcc_adaptive.",
          "tests.flexstack.management.test_dcc_entity.", "tests.flexstack.management.test_cbr.",
          "tests.flexstack.geonet.test_dcc_net.")
DCC_RS = ("management::dcc_reactive::", "management::dcc_adaptive::", "management::dcc_entity::",
          "management::cbr::", "geonet::dcc_net::")


def dcc_tests(py_found, rs_found):
    """{module prefix: number of tests} for the DCC modules, per stack."""
    return ({p: sum(t.startswith(p) for t in py_found) for p in DCC_PY},
            {p: sum(t.startswith(p) for t in rs_found) for p in DCC_RS})


def write_markdown(counts, tps, mapping, excluded, dcc):  # pylint: disable=too-many-locals
    """traceability.md: one table per protocol plus the list of open TPs."""
    by_id = {m["tp_id"]: m for m in mapping}
    totals = collections.Counter(t["protocol"] for t in tps)
    out = [
        "# Test traceability to ETSI conformance test purposes",
        "",
        "Generated by `build_matrix.py` from `test_purposes.csv` and `traceability.csv`; "
        "do not edit by hand.",
        "",
        "Every Test Purpose (TP) of the ETSI TSS&TP documents below, with the clauses "
        "the TP references (as cited by the TSS&TP), the status in the Python "
        "(`v2xflexstack`) and Rust (`rustflexstack`) stacks and the unit tests traced to it. "
        "The TP objectives are ETSI text and are not reproduced: see the TSS&TP documents.",
        "",
        "These are unit tests *traced to* ETSI TPs, not an execution of the ETSI abstract "
        "test suites (TTCN-3) and not conformance testing by an accredited test lab.",
        "",
        "Status: **covered**: a unit test asserts the behaviour the TP checks; **partial**: "
        "exercised, not all TP conditions; **untested**: implemented, no unit test; "
        "**not implemented**; **N/A**: outside the implementation's PICS.",
        "",
        "Test ids: Python `tests.flexstack.<package>.<module>.<Class>.<method>`; Rust "
        "`<module path>::<test fn>` (test sub-module names omitted).",
        "",
        "## Summary",
        "",
        "| Protocol | TSS&TP | TPs | Impl. | Covered | Partial | Untested | Not impl. | N/A |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for p in PROTOCOL_ORDER + ("ALL",):
        for impl in ("py", "rs"):
            if p == "ALL":
                vals = [sum(counts[(q, impl, s)] for q in PROTOCOL_ORDER) for s in STATUSES]
                name, doc, n = "**Total**", "", sum(totals.values())
            else:
                vals = [counts[(p, impl, s)] for s in STATUSES]
                name, doc, n = DOCUMENTS[p][0], DOCUMENTS[p][1], totals[p]
            if impl == "rs":
                name, doc, n = "", "", ""
            out.append(f"| {name} | {doc} | {n} | {'Python' if impl == 'py' else 'Rust'} | "
                       + " | ".join(str(v) for v in vals) + " |")

    audited = ", ".join(DOCUMENTS[p][0] for p in TAGGED_PROTOCOLS)
    pending = ", ".join(DOCUMENTS[p][0] for p in PROTOCOL_ORDER if p not in TAGGED_PROTOCOLS)
    status = (f"Audited TP by TP: {audited}. Each covered TP has one dedicated test per stack, named "
              "after the TP and quoting its identifier (search the identifier to find it); "
              "`build_matrix.py` fails if a listed test does not quote its TP or a test quotes a TP "
              "it is not listed for, and if a TP not covered does not say why.")
    if pending:
        status += (f" Not yet audited: {pending}. Their mapping lists tests that exercise the "
                   "behaviour, but these tests do not quote the TP identifier yet.")
    out += ["", "**Audit status.** " + status,
            "", "TPs not covered and documents left out of the mapping, with the reasons: "
            "[Not covered](#not-covered) and [Outside the mapping](#outside-the-mapping)."]
    for p in PROTOCOL_ORDER:
        name, doc, base = DOCUMENTS[p]
        audit = ("Audited: one dedicated test per TP and stack, quoting the TP identifier."
                 if p in TAGGED_PROTOCOLS else
                 "Not yet audited: the listed tests do not quote the TP identifier.")
        out += ["", f"## {name}", "", audit, "",
                f"Test purposes: {doc}. Implemented standard: {base}.", "",
                "| TP | Referenced clauses | PICS | Python | Rust | Note |",
                "|---|---|---|---|---|---|"]
        for t in (t for t in tps if t["protocol"] == p):
            m = by_id[t["tp_id"]]
            out.append(f"| `{t['tp_id']}` | {_md(t['reference'])} | {_md(t['pics_selection'])} | "
                       f"{_md_tests(m['py_status'], m['py_tests'])} | "
                       f"{_md_tests(m['rs_status'], m['rs_tests'])} | {_md(m['note'])} |")

    out += ["", "## Scope and limitations", "",
            "What this traceability shows, and what it does not:", "",
            "- **In-process tests.** The tests drive the real protocol code (routers, sign and "
            "verify services, facilities) in one process, with injected clocks and a mocked or "
            "in-memory access layer. They do not send frames over the air.",
            "- **Not the ETSI ATS.** The TTCN-3 Abstract Test Suites were not executed, and no "
            "accredited test lab was involved. A TP marked covered means a unit or integration "
            "test asserts the behaviour the TP checks.",
            "- **Interoperability.** Python and Rust verify each other's frozen signed messages "
            "and certificate chains, and the implicit-certificate construction is checked "
            "against ETSI `itscertgen`'s formulas. Tests against third-party stacks (the kind "
            "done at an ETSI Plugtest) are not part of this matrix.",
            "- **DCC.** See [DCC](#dcc): unit tests against the base standards, no TSS&TP.",
            "- **Hardware-dependent behaviour.** The C-V2X link layer (`cv2x` feature) needs the "
            "vendor library and was not built or tested here; the TP below marked *not "
            "implemented* for C-V2X needs it.",
            "- **PICS.** N/A means outside the PICS of these implementations (vehicle ITS-S "
            "profile, CAM v2, the forwarding algorithms of TS 103 836-4-1 V2.2.1). Optional "
            "features listed as not implemented are left out of the PICS.",
            "- **Permutations.** A TP with a permutation table is one test that covers every "
            "permutation (signing on NIST P-256, brainpoolP256r1 and brainpoolP384r1; region "
            "kinds); the note lists them.",
            "",
            "## Not covered", "",
            "Every TP not covered in at least one stack, grouped by reason. The note is the "
            "reason recorded in `traceability.csv` (required by `build_matrix.py`).", ""]
    open_rows = [(t, by_id[t["tp_id"]]) for t in tps
                 if not by_id[t["tp_id"]]["py_status"] == by_id[t["tp_id"]]["rs_status"] == "covered"]
    groups = collections.OrderedDict()
    for t, m in open_rows:
        groups.setdefault(category(m), []).append((t, m))
    out += ["| Reason | TPs |", "|---|---:|"]
    out += [f"| {g} | {len(rows)} |" for g, rows in groups.items()]
    out += [f"| **Total** | **{len(open_rows)}** |"]
    for g, rows in groups.items():
        out += ["", f"### {g}", "", "| Protocol | TP | Python | Rust | Reason |", "|---|---|---|---|---|"]
        for t, m in rows:
            out.append(f"| {DOCUMENTS[t['protocol']][0]} | `{t['tp_id']}` | {LABELS[m['py_status']]} | "
                       f"{LABELS[m['rs_status']]} | {_md(m['note'])} |")
    out += ["", "## Outside the mapping", "",
            "TSS&TP documents, or parts of them, deliberately not mapped (`excluded.csv`).", "",
            "| Document | Scope | TPs | Reason |", "|---|---|---:|---|"]
    out += [f"| {_md(e['document'])} | {_md(e['scope'])} | {e['tps']} | {_md(e['reason'])} |"
            for e in excluded]
    out += ["", "No TSS&TP was available for the VRU awareness service (VAM) or for DCC as "
            "implemented here; their behaviour is covered by unit tests only.",
            "", "## DCC", "",
            "DCC as implemented in both stacks: the reactive and adaptive algorithms of ETSI TS 102 687 "
            "V1.2.1 in the management layer, driving the CAM / VAM generation interval "
            "(T_GenCam_DCC), and DCC_NET of ETSI TS 103 836-4-2 V2.1.1 clauses 5 to 7 (CBR_G, "
            "LocTEX-G5, DCC-MCO) in GeoNetworking. Their unit tests (below) were written against "
            "these base standards and use injected CBR values; there is no TSS&TP for them, so "
            "they are not in the TP counts above, and unlike the TP-audited protocols they have "
            "not been re-audited clause by clause. On Linux ITS-G5 interfaces the local CBR comes from the "
            "nl80211 channel survey (driver CCA threshold, not the -85 dBm of TS 102 687). The "
            "access-layer DCC tested by ETSI TS 102 917-2 is not implemented (see "
            "[Outside the mapping](#outside-the-mapping)).", "",
            "| Python module | Tests | Rust module | Tests |", "|---|---:|---|---:|"]
    py_dcc, rs_dcc = dcc
    for (pm, pn), (rm, rn) in zip(py_dcc.items(), rs_dcc.items()):
        out.append(f"| `{pm.rstrip('.')}` | {pn} | `{rm.rstrip(':')}` | {rn} |")
    out.append(f"| **Total** | **{sum(py_dcc.values())}** | | **{sum(rs_dcc.values())}** |")
    with open(os.path.join(HERE, "traceability.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--python-repo", required=True)
    ap.add_argument("--rust-repo", required=True)
    args = ap.parse_args()

    tps = read_csv("test_purposes.csv")
    mapping = read_csv("traceability.csv")
    py_found, rs_found = python_tests(args.python_repo), rust_tests(args.rust_repo)
    excluded = read_csv("excluded.csv")
    errors = validate(tps, mapping, py_found, rs_found) + validate_excluded(excluded)
    tag_errors, pending_tags = validate_tags(tps, mapping, py_found, rs_found)
    errors += tag_errors
    if errors:
        print(f"{len(errors)} problem(s):", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
        sys.exit(1)

    counts = summarise(tps, mapping)
    write_outputs(counts, tps)
    write_markdown(counts, tps, mapping, excluded, dcc_tests(py_found, rs_found))
    print(f"{len(tps)} TPs, {len(py_found)} Python tests, {len(rs_found)} Rust tests scanned.")
    print(f"{'protocol':<8} {'impl':<6} " + " ".join(f"{s:>15}" for s in STATUSES))
    for p in PROTOCOL_ORDER:
        for impl in ("py", "rs"):
            print(f"{p:<8} {impl:<6} " + " ".join(f"{counts[(p, impl, s)]:>15}" for s in STATUSES))
    for impl in ("py", "rs"):
        print(f"{'ALL':<8} {impl:<6} " + " ".join(
            f"{sum(counts[(q, impl, s)] for q in PROTOCOL_ORDER):>15}" for s in STATUSES))
    print("Wrote summary.csv, tab_traceability.tex and traceability.md")
    print(f"TP tags enforced for: {', '.join(TAGGED_PROTOCOLS)}")
    for p in PROTOCOL_ORDER:
        if pending_tags[p]:
            print(f"  {p}: {pending_tags[p]} listed tests do not quote their TP yet")


if __name__ == "__main__":
    main()
