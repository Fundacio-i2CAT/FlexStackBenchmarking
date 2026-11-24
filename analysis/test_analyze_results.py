# SPDX-License-Identifier: AGPL-3.0-only
"""Tests of the campaign loading of analyze_results.py (run: python -m pytest)."""
import os

import pandas as pd
import pytest

from analyze_results import campaign_inputs, drop_superseded, load_results

HEADER = ("run_id,implementation,platform,security,benchmark,duration_s,total_cams,"
          "throughput_cams_s,latency_mean_us,latency_std_us,latency_p50_us,latency_p95_us,"
          "latency_p99_us,latency_min_us,latency_max_us,sign_latency_mean_us,cpu_pct,"
          "rss_start_mb,peak_rss_mb,target_rate\n")


def row(run, impl, bench, tp):
    return f"{run},{impl},host,off,{bench},60,{tp * 60},{tp},1,0,1,1,1,1,1,0,95,1,2,0\n"


def make_campaign(tmp_path, superseded=None):
    camp = tmp_path / "campaign"
    host = camp / "raw" / "h1"
    host.mkdir(parents=True)
    (camp / "platforms.csv").write_text("dir,platform\nh1,plat\n")
    (host / "results_h1_20260101T000000.csv").write_text(
        HEADER + row(1, "rust", "tx", 100) + row(1, "rust", "codec-encode", 50)
        + row(1, "vanetza", "tx", 300))
    (host / "results_h1_after_20260102T000000.csv").write_text(
        HEADER + row(1, "rust", "tx", 200) + row(2, "rust", "tx", 210))
    if superseded is not None:
        (camp / "superseded.csv").write_text(superseded)
    return str(camp)


def load(camp):
    return drop_superseded(load_results(campaign_inputs(camp)), camp)


def test_without_superseded_file_all_rows_are_kept(tmp_path):
    df = load(make_campaign(tmp_path))
    assert len(df) == 5
    assert set(df["platform"]) == {"plat"}


def test_rerun_replaces_only_the_named_cell(tmp_path):
    camp = make_campaign(tmp_path, "# reruns\ndir,rerun_file,implementation,benchmark\n"
                                   "h1,results_h1_after_20260102T000000.csv,rust,tx\n")
    df = load(camp)
    rust_tx = df[(df["implementation"] == "rust") & (df["benchmark"] == "tx")]
    assert sorted(rust_tx["throughput_cams_s"]) == [200, 210]
    # Other cells of the same file and other implementations are untouched
    assert len(df[df["benchmark"] == "codec-encode"]) == 1
    assert len(df[df["implementation"] == "vanetza"]) == 1


def test_rule_for_another_folder_does_not_apply(tmp_path):
    camp = make_campaign(tmp_path, "dir,rerun_file,implementation,benchmark\n"
                                   "h2,results_h1_after_20260102T000000.csv,rust,tx\n")
    assert len(load(camp)) == 5


def test_missing_rerun_file_is_an_error(tmp_path):
    camp = make_campaign(tmp_path, "dir,rerun_file,implementation,benchmark\n"
                                   "h1,results_h1_after_29990101T000000.csv,rust,tx\n")
    with pytest.raises(SystemExit):
        load(camp)


def test_malformed_lines_are_skipped_not_fatal(tmp_path):
    camp = make_campaign(tmp_path)
    f = os.path.join(camp, "raw", "h1", "results_h1_20260101T000000.csv")
    with open(f, "a") as fh:
        fh.write("29,vanetza,host,off,tx,60.000,6183\n")                        # truncated
        fh.write(row(30, "vanetza", "tx", 1).strip() + "," + row(31, "vanetza", "tx", 2))  # two merged
    df = load(camp)
    assert len(df) == 5            # only the 5 well-formed rows of the campaign files
    assert df["throughput_cams_s"].dtype.kind in "fi"   # columns still numeric


def test_security_column_limits_the_rule_to_one_mode(tmp_path):
    camp = make_campaign(tmp_path)
    host = os.path.join(camp, "raw", "h1")
    with open(os.path.join(host, "results_h1_after_20260103T000000.csv"), "w") as fh:
        fh.write(HEADER + row(1, "pypy", "rx", 10) + row(1, "pypy", "rx", 11).replace(",off,", ",on,"))
    with open(os.path.join(host, "results_h1_after_20260104T000000.csv"), "w") as fh:
        fh.write(HEADER + row(1, "pypy", "rx", 20))
    with open(os.path.join(camp, "superseded.csv"), "w") as fh:
        fh.write("dir,rerun_file,implementation,benchmark,security\n"
                 "h1,results_h1_after_20260104T000000.csv,pypy,rx,off\n"
                 "h1,results_h1_after_20260102T000000.csv,rust,tx,\n")
    df = load(camp)
    pypy = df[df["implementation"] == "pypy"]
    # the unsecured row is replaced by the rerun; the secured one is kept
    assert sorted(zip(pypy["security"], pypy["throughput_cams_s"])) == [("off", 20), ("on", 11)]
    # an empty security still replaces the cell in both modes
    assert sorted(df[(df["implementation"] == "rust") & (df["benchmark"] == "tx")]["throughput_cams_s"]) == [200, 210]
