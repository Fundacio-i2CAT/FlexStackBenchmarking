# SPDX-License-Identifier: AGPL-3.0-only
"""
Summarise the JSON-lines logs of an interop run into the sender x receiver
matrix.

For every (sender, receiver) pair, per message type (CAM = ITS-AID 36, DENM =
37, GN Beacon = 141) and signer type (digest / certificate):

* ``sent``      packets the sender originated while the receiver was running;
* ``received``  secured packets the receiver's security entity processed
  (GeoBroadcast DENMs can be received more than once: forwarded copies);
* ``verified``  of those, accepted (report Success);
* ``refused``   the others, by report.

The sender of a packet is identified by the HashedId8 of the AT that signed it
(``manifest.json`` of make_certs.py). Packets a receiver gets back signed with
its own AT (GeoBroadcast forwarded by a neighbour) are counted apart. A packet
received before the receiver has learned the sender's AT, signed with a digest,
is refused with "signer certificate not found": that is the expected P2PCD
start-up behaviour (TS 103 097 clause 7.1.1), reported in its own column.

Facility level: CAMs / DENMs delivered to the receiver's CA / DEN service, per
sender station ID, against the number the sender signed.

Writes ``summary.json``, ``matrix.csv`` and ``matrix.md`` into ``--out`` and
prints the Markdown table.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os

AID_NAMES = {36: "CAM", 37: "DENM", 141: "Beacon"}
STATIONS = {1: "python", 2: "rust", 3: "vanetza", 4: "rogue"}
NOT_FOUND = {"SIGNER_CERTIFICATE_NOT_FOUND", "SignerCertificateNotFound", "Signer_Certificate_Not_Found"}


def _events(path: str):
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith("{"):
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def _sent_while_up(times: list, window) -> int:
    """Packets sent while the receiver was running (start .. stop - 200 ms)."""
    if not window:
        return len(times)
    start, stop = window
    return sum(1 for t in times if start <= t <= stop - 200)


def summarize(logs: list[str], manifest: dict) -> dict:
    """The matrix of one run."""
    at_owner = {}
    for name, item in manifest.items():
        if name.startswith("at_"):
            at_owner[item["hashedid8"]] = name[3:]
    rx = collections.defaultdict(lambda: collections.Counter())
    tx = collections.defaultdict(lambda: collections.Counter())
    tx_times = collections.defaultdict(list)      # (sender, aid, signer) -> [t_ms]
    window = {}                                    # node -> (start, stop) t_ms
    facility = collections.defaultdict(lambda: collections.Counter())
    nodes = []
    for path in logs:
        for event in _events(path):
            node = event.get("node")
            if node not in nodes:
                nodes.append(node)
            kind = event.get("event")
            aid = AID_NAMES.get(event.get("its_aid"), str(event.get("its_aid")))
            if kind == "start":
                window[node] = (event["t_ms"], float("inf"))
            elif kind == "stop" and node in window:
                window[node] = (window[node][0], event["t_ms"])
            elif kind == "tx" and event.get("signed"):
                # Originated only: a forwarded packet keeps its originator's signature.
                if at_owner.get(event.get("at", "")) == node:
                    tx[node][(aid, event.get("signer"))] += 1
                    tx_times[(node, aid, event.get("signer"))].append(event["t_ms"])
            elif kind == "rx":
                sender = at_owner.get(event.get("at", ""), "unknown")
                key = (sender, node, aid, event.get("signer"))
                rx[key]["received"] += 1
                report = event.get("report", "")
                if event.get("verified"):
                    rx[key]["verified"] += 1
                elif report in NOT_FOUND:
                    rx[key]["refused_at_unknown"] += 1
                else:
                    rx[key]["refused"] += 1
                    rx[key]["report:" + report] += 1
            elif kind in ("cam", "denm"):
                # An undecodable message has no station ID: its sender is unknown.
                sender = STATIONS.get(event.get("station_id"), "(undecodable)")
                facility[(sender, node, kind.upper())]["delivered" if event.get("decoded") else "undecodable"] += 1
    rows = []
    for (sender, receiver, aid, signer), counts in sorted(rx.items()):
        rows.append({
            "sender": sender, "receiver": receiver, "message": aid, "signer": signer,
            "own_packet": sender == receiver,
            "sent": _sent_while_up(tx_times[(sender, aid, signer)], window.get(receiver)),
            "received": counts["received"], "verified": counts["verified"],
            "refused_at_unknown": counts["refused_at_unknown"], "refused": counts["refused"],
            "refusal_reports": {k[7:]: v for k, v in counts.items() if k.startswith("report:")},
        })
    facility_rows = []
    for (sender, receiver, kind), counts in sorted(facility.items()):
        sent = sum(_sent_while_up(tx_times[(sender, kind, signer)], window.get(receiver))
                   for signer in ("digest", "certificate"))
        verified = sum(c["verified"] for (snd, rcv, aid, _), c in rx.items()
                       if (snd, rcv, aid) == (sender, receiver, kind))
        facility_rows.append({"sender": sender, "receiver": receiver, "message": kind, "sent": sent,
                              "verified": verified, "delivered": counts["delivered"],
                              # A CAM is single hop: each verified CAM must reach the CA
                              # service. (DENMs: forwarded copies are verified, then
                              # dropped as duplicates.)
                              "verified_not_delivered": verified - counts["delivered"] if kind == "CAM" else None})
    return {"nodes": nodes, "security": rows, "facility": facility_rows,
            "tx": {n: {f"{a}/{s}": v for (a, s), v in c.items()} for n, c in tx.items()}}


def markdown(summary: dict, label: str) -> str:
    """The security matrix as a Markdown table."""
    lines = [f"### {label}", "",
             "| Sender | Receiver | Message | Signer | Sent | Received | Verified | AT not yet known | Refused (report) |",
             "|---|---|---|---|---:|---:|---:|---:|---|"]
    for row in summary["security"]:
        if row["own_packet"]:
            continue
        reports = ", ".join(f"{k} {v}" for k, v in sorted(row["refusal_reports"].items())) or "-"
        lines.append(f"| {row['sender']} | {row['receiver']} | {row['message']} | {row['signer']} | {row['sent']} | "
                     f"{row['received']} | {row['verified']} | {row['refused_at_unknown']} | "
                     f"{row['refused']} ({reports}) |")
    lines += ["", "| Sender | Receiver | Facility message | Sent (signed) | Verified | Delivered | CAMs verified, not delivered |",
              "|---|---|---|---:|---:|---:|---:|"]
    for row in summary["facility"]:
        if row["sender"] == row["receiver"]:
            continue
        missing = "-" if row["verified_not_delivered"] is None else row["verified_not_delivered"]
        lines.append(f"| {row['sender']} | {row['receiver']} | {row['message']} | {row['sent']} | "
                     f"{row['verified']} | {row['delivered']} | {missing} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("logs", nargs="+")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", default="Signed interoperability matrix")
    args = parser.parse_args()
    with open(args.manifest, encoding="utf-8") as handle:
        manifest = json.load(handle)
    summary = summarize(args.logs, manifest)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    with open(os.path.join(args.out, "matrix.csv"), "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[k for k in summary["security"][0] if k != "refusal_reports"]
                                + ["refusal_reports"]) if summary["security"] else None
        if writer:
            writer.writeheader()
            for row in summary["security"]:
                writer.writerow({**row, "refusal_reports": json.dumps(row["refusal_reports"])})
    text = markdown(summary, args.label)
    with open(os.path.join(args.out, "matrix.md"), "w", encoding="utf-8") as handle:
        handle.write(text)
    print(text)


if __name__ == "__main__":
    main()
