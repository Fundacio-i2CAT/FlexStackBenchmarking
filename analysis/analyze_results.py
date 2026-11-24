#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""
FlexStack Benchmark — Statistical Analysis

Reads CSV output from the benchmark orchestrator and produces:
  1. Summary table (mean ± std, 95% CI) per cell
  2. LaTeX-formatted tables for the paper
  3. Comparison ratios (Rust vs CPython, PyPy vs CPython)
  4. Outlier diagnostics (reported only; no run is ever removed)

Statistical method
------------------
Each benchmark cell (implementation × platform × security × benchmark) has
N independent runs (N = 30 in the paper campaign). Every run reports its own
latency mean and p50/p95/p99, computed over all messages of that run.

For throughput and for each latency statistic, the cell value is the mean of
the N per-run values, and its 95% confidence interval is the two-sided
Student-t interval of that mean:

    x̄ ± t_{0.975, N-1} · s / √N        (df = N - 1 = 29 for N = 30)

The latency CIs therefore express run-to-run reproducibility of each
statistic (e.g. "mean per-run p99"), not the sampling error of a single
pooled percentile.

Outliers: a run is flagged when its throughput or p99 lies outside Tukey's
fences [Q1 - 1.5·IQR, Q3 + 1.5·IQR] within its cell. Flagged runs are
counted and listed, but are never excluded from any statistic.

Resources and thermal state (campaigns from harness v0.2.9 on)
---------------------------------------------------------------
If the CSV has cpu_pct / rss_start_mb / peak_rss_mb, they are summarised
the same way (mean ± 95% CI). If a `<results>_thermal.csv` sidecar written by
scripts/lib_monitor.sh sits next to a results file, it is joined per run;
runs whose throttling state changed during the run are counted per cell
(`throttled_runs`) and listed, but kept.

Fixed-rate runs (--rate, column target_rate; 0 or absent = max rate) form
separate cells. The max-rate tables only use target_rate == 0; fixed-rate
cells go to their own report and tab_fixed_rate.tex. A fixed-rate cell whose
mean throughput is below 98% of its target is flagged: the implementation
cannot sustain that rate.

Usage:
  python3 analyze_results.py --campaign ../results/campaign_2026-11 --output-summary ../results/campaign_2026-11/summary.csv
  python3 analyze_results.py --input ../results/results.csv
  python3 analyze_results.py --input ../results/results_laptop_*.csv ../results/results_rx_laptop_*.csv
  python3 analyze_results.py --input ../results/results.csv --latex
  python3 analyze_results.py --input ../results/results.csv --latex-dir ../results/tables
"""

import argparse
import csv
import glob
import io
import os

import numpy as np
import pandas as pd
from scipy import stats


RESOURCE_COLS = ("cpu_pct", "rss_start_mb", "peak_rss_mb")
GROUP_COLS = ["implementation", "platform", "security", "benchmark", "target_rate"]
SUSTAINED_FRACTION = 0.98


def with_target_rate(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure a numeric target_rate column (0 = max rate, older CSVs)."""
    df = df.copy()
    if "target_rate" not in df.columns:
        df["target_rate"] = 0.0
    df["target_rate"] = pd.to_numeric(df["target_rate"], errors="coerce").fillna(0.0)
    return df


def impl_family(implementation: str) -> str:
    """'cpython_3.13' -> 'cpython', 'pypy_3.11' -> 'pypy'; others unchanged.
    Matches the implementation names the orchestrator scripts write in the
    thermal sidecar."""
    for fam in ("cpython", "pypy"):
        if implementation.startswith(fam):
            return fam
    return implementation


def attach_thermal(df: pd.DataFrame, results_path: str) -> pd.DataFrame:
    """Join `<results>_thermal.csv` (if present) per run. Adds temp_start_c,
    temp_end_c, throttle_start/end and a boolean `throttled` column."""
    base, ext = os.path.splitext(results_path)
    thermal_path = f"{base}_thermal{ext}"
    if not os.path.exists(thermal_path):
        return df
    th = pd.read_csv(thermal_path, dtype={"throttle_start": str, "throttle_end": str})
    th = th.rename(columns={"implementation": "impl_family"})
    keys = ["run_id", "impl_family", "security", "benchmark"]
    if "target_rate" in th.columns:
        th["target_rate"] = pd.to_numeric(th["target_rate"], errors="coerce").fillna(0.0)
        keys.append("target_rate")
    th = th.drop_duplicates(subset=keys, keep="last")
    df = df.copy()
    df["impl_family"] = df["implementation"].map(impl_family)
    df = df.merge(th, on=keys, how="left")
    start, end = df["throttle_start"], df["throttle_end"]
    df["throttled"] = start.notna() & end.notna() & (start != end)
    print(f"  thermal sidecar joined: {thermal_path} "
          f"({int(df['temp_end_c'].notna().sum())}/{len(df)} runs matched)")
    return df


def campaign_inputs(campaign_dir: str):
    """(results CSV, platform label) pairs of a campaign folder.

    The folder holds platforms.csv (columns dir, platform) and one raw/<dir>/
    folder per host. The label replaces the CSV's platform column, so that
    hosts reporting the same platform name in different configurations
    (e.g. the two Jetson AGX Orin power modes) form separate cells, and
    hosts that split one platform's cells between them (the Orin Nanos)
    share one label.
    """
    index = pd.read_csv(os.path.join(campaign_dir, "platforms.csv"), comment="#")
    pairs = []
    for row in index.itertuples(index=False):
        folder = os.path.join(campaign_dir, "raw", row.dir)
        files = sorted(
            f for f in glob.glob(os.path.join(folder, "results_*.csv"))
            if not f.endswith(("_thermal.csv", "_env.csv"))
        )
        if not files:
            print(f"  [campaign] no results in {folder}")
        pairs += [(f, row.platform) for f in files]
    return pairs


def read_results_csv(path: str) -> pd.DataFrame:
    """Read a results CSV, skipping malformed lines.

    A line whose number of fields differs from the header (e.g. lines garbled
    when a board froze while writing, RPi3 known issue in the campaign README)
    is skipped and reported; the raw file is not modified.
    """
    with open(path, newline="") as fh:
        rows = list(csv.reader(fh))
    header, body = rows[0], rows[1:]
    good = [r for r in body if len(r) == len(header)]
    bad = sum(1 for r in body if r and len(r) != len(header))
    if bad:
        print(f"  [load] {os.path.basename(path)}: {bad} malformed line(s) skipped")
    buf = io.StringIO()
    csv.writer(buf).writerows([header] + good)
    buf.seek(0)
    return pd.read_csv(buf)


def drop_superseded(df: pd.DataFrame, campaign_dir: str) -> pd.DataFrame:
    """Drop the rows of cells that were measured again after the campaign.

    superseded.csv (optional, columns dir, rerun_file, implementation,
    benchmark and, optionally, security) names, per host folder, the results
    file of a rerun and the cells it replaces. The rows of those cells in
    every other results file of that folder are dropped; the raw files
    themselves are kept unchanged. A rule with an empty (or no) security
    replaces both security modes of the cell; "off" or "on" replaces only
    that mode.
    """
    path = os.path.join(campaign_dir, "superseded.csv")
    if not os.path.exists(path):
        return df
    rules = pd.read_csv(path, comment="#", dtype=str, keep_default_na=False)
    if "security" not in rules.columns:
        rules["security"] = ""
    drop = pd.Series(False, index=df.index)
    for r in rules.itertuples(index=False):
        if not (df["source_file"] == r.rerun_file).any():
            raise SystemExit(f"superseded.csv: {r.dir}/{r.rerun_file} has no rows")
        drop |= (
            (df["source_dir"] == r.dir)
            & (df["implementation"] == r.implementation)
            & (df["benchmark"] == r.benchmark)
            & ((r.security == "") | (df["security"] == r.security))
            & (df["source_file"] != r.rerun_file)
        )
    print(f"  [campaign] {int(drop.sum())} rows replaced by reruns (superseded.csv)")
    return df[~drop].reset_index(drop=True)


def load_results(paths) -> pd.DataFrame:
    """paths: CSV paths, or (path, platform label) pairs from campaign_inputs."""
    if isinstance(paths, str):
        paths = [paths]
    frames = []
    for item in paths:
        path, label = item if isinstance(item, tuple) else (item, None)
        part = with_target_rate(read_results_csv(path))
        if label is not None:
            part["platform"] = label
        part["source_dir"] = os.path.basename(os.path.dirname(os.path.abspath(path)))
        part["source_file"] = os.path.basename(path)
        frames.append(attach_thermal(part, path))
    df = pd.concat(frames, ignore_index=True, sort=False)
    # Normalize numeric columns
    for col in [
        "duration_s",
        "total_cams",
        "throughput_cams_s",
        "latency_mean_us",
        "latency_std_us",
        "latency_p50_us",
        "latency_p95_us",
        "latency_p99_us",
        "latency_min_us",
        "latency_max_us",
        "sign_latency_mean_us",
        *RESOURCE_COLS,
        "temp_start_c",
        "temp_end_c",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


LATENCY_STATS = ("mean", "p50", "p95", "p99")


def mean_ci95(values: pd.Series):
    """Mean, sample std and two-sided Student-t 95% CI of the mean.

    Returns (mean, std, ci_low, ci_high, half_width). With fewer than two
    values the spread is undefined and the CI collapses to the mean.
    """
    v = values.dropna().astype(float)
    n = len(v)
    if n == 0:
        nan = float("nan")
        return nan, nan, nan, nan, nan
    mean = float(v.mean())
    if n < 2:
        return mean, 0.0, mean, mean, 0.0
    std = float(v.std(ddof=1))
    half = float(stats.t.ppf(0.975, df=n - 1)) * std / np.sqrt(n)
    return mean, std, mean - half, mean + half, half


def tukey_outliers(values: pd.Series) -> pd.Series:
    """Boolean mask of values outside Tukey's 1.5·IQR fences (flag only)."""
    v = values.astype(float)
    q1, q3 = v.quantile(0.25), v.quantile(0.75)
    iqr = q3 - q1
    return (v < q1 - 1.5 * iqr) | (v > q3 + 1.5 * iqr)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Compute summary statistics per (implementation, platform, security, benchmark) cell."""
    rows = []

    for keys, group in df.groupby(GROUP_COLS):
        impl_, plat, sec, bench, rate = keys
        n = len(group)

        tp = group["throughput_cams_s"]
        tp_mean = tp.mean()
        tp_std = tp.std(ddof=1) if n > 1 else 0.0
        tp_se = tp_std / np.sqrt(n) if n > 0 else 0.0
        t_crit = stats.t.ppf(0.975, df=max(n - 1, 1))
        tp_ci_low = tp_mean - t_crit * tp_se
        tp_ci_high = tp_mean + t_crit * tp_se

        # Across-run Student-t CIs of the per-run latency statistics.
        lat_ci = {}
        for stat in LATENCY_STATS:
            col = f"latency_{stat}_us"
            _, sd, lo, hi, half = mean_ci95(group[col])
            lat_ci[f"latency_{stat}_run_std_us"] = sd
            lat_ci[f"latency_{stat}_ci95_low"] = lo
            lat_ci[f"latency_{stat}_ci95_high"] = hi
            lat_ci[f"latency_{stat}_ci95_half"] = half

        # Outlier diagnostics (never used to drop runs).
        tp_out = tukey_outliers(tp) if n >= 4 else pd.Series(False, index=tp.index)
        p99_out = (
            tukey_outliers(group["latency_p99_us"]) if n >= 4
            else pd.Series(False, index=tp.index)
        )

        lat_mean = group["latency_mean_us"].mean()
        lat_std = group["latency_std_us"].mean()
        lat_p50 = group["latency_p50_us"].mean()
        lat_p95 = group["latency_p95_us"].mean()
        lat_p99 = group["latency_p99_us"].mean()
        lat_min = group["latency_min_us"].min()
        lat_max = group["latency_max_us"].max()

        cv = (tp_std / tp_mean * 100) if tp_mean > 0 else 0.0

        # Resource usage (harness v0.2.9+); NaN for older CSVs.
        res = {}
        for col in RESOURCE_COLS:
            if col in group:
                m, _, _, _, half = mean_ci95(group[col])
            else:
                m = half = float("nan")
            res[f"{col}_mean"] = m
            res[f"{col}_ci95_half"] = half
        if "throttled" in group:
            thr = group["throttled"].fillna(False).astype(bool)
            res["throttled_runs"] = int(thr.sum())
            res["throttled_run_ids"] = " ".join(
                str(r) for r in sorted(group.loc[thr, "run_id"].tolist()))
            res["temp_max_c"] = group[["temp_start_c", "temp_end_c"]].max().max()

        rows.append(
            {
                "implementation": impl_,
                "platform": plat,
                "security": sec,
                "benchmark": bench,
                "n": n,
                "throughput_mean": tp_mean,
                "throughput_std": tp_std,
                "throughput_ci95_low": tp_ci_low,
                "throughput_ci95_high": tp_ci_high,
                "cv_pct": cv,
                "latency_mean_us": lat_mean,
                "latency_std_us": lat_std,
                "latency_p50_us": lat_p50,
                "latency_p95_us": lat_p95,
                "latency_p99_us": lat_p99,
                "latency_min_us": lat_min,
                "latency_max_us": lat_max,
                **lat_ci,
                "outliers_throughput": int(tp_out.sum()),
                "outliers_p99": int(p99_out.sum()),
                "outlier_runs_throughput": " ".join(
                    str(r) for r in sorted(group.loc[tp_out, "run_id"].tolist())
                ) if "run_id" in group else "",
                "outlier_runs_p99": " ".join(
                    str(r) for r in sorted(group.loc[p99_out, "run_id"].tolist())
                ) if "run_id" in group else "",
                **res,
                "target_rate": rate,
                "achieved_ratio": tp_mean / rate if rate > 0 else float("nan"),
                "below_target": bool(rate > 0 and tp_mean < SUSTAINED_FRACTION * rate),
            }
        )

    return pd.DataFrame(rows)


def _bench_label(row) -> str:
    rate = row.get("target_rate", 0) or 0
    return row["benchmark"] if rate <= 0 else f"{row['benchmark']}@{rate:g}"


def print_summary(summary: pd.DataFrame):
    """Print a human-readable summary table."""
    print()
    print("=" * 120)
    print(f"{'Implementation':>15s} | {'Platform':>8s} | {'Sec':>3s} | {'Benchmark':>13s} | "
          f"{'N':>3s} | {'Throughput (CAMs/s)':>25s} | {'95% CI':>25s} | {'CV%':>5s} | "
          f"{'Lat p50 (μs)':>12s} | {'Lat p99 (μs)':>12s}")
    print("-" * 120)

    for _, row in summary.iterrows():
        tp_str = f"{row['throughput_mean']:.0f} ± {row['throughput_std']:.0f}"
        ci_str = f"[{row['throughput_ci95_low']:.0f}, {row['throughput_ci95_high']:.0f}]"
        print(
            f"{row['implementation']:>15s} | {row['platform']:>8s} | {row['security']:>3s} | "
            f"{_bench_label(row):>13s} | {row['n']:>3.0f} | {tp_str:>25s} | {ci_str:>25s} | "
            f"{row['cv_pct']:>5.1f} | {row['latency_p50_us']:>12.1f} | {row['latency_p99_us']:>12.1f}"
        )

    print("=" * 120)


def compute_speedup(summary: pd.DataFrame):
    """Compute speedup ratios (Rust vs CPython, PyPy vs CPython)."""
    print("\n── Speedup Ratios ──")
    print(f"{'Comparison':>30s} | {'Platform':>8s} | {'Sec':>3s} | {'Benchmark':>13s} | {'Speedup':>10s}")
    print("-" * 80)

    for (plat, sec, bench), group in summary.groupby(["platform", "security", "benchmark"]):
        # Find CPython baseline
        cpython_rows = group[group["implementation"].str.contains("cpython", case=False)]
        if cpython_rows.empty:
            continue
        baseline = cpython_rows.iloc[0]["throughput_mean"]
        if baseline <= 0:
            continue

        for _, row in group.iterrows():
            if "cpython" in row["implementation"].lower():
                continue
            speedup = row["throughput_mean"] / baseline
            label = f"{row['implementation']} vs CPython"
            print(
                f"{label:>30s} | {plat:>8s} | {sec:>3s} | {bench:>13s} | {speedup:>10.1f}×"
            )


def generate_latex(summary: pd.DataFrame):
    """Generate LaTeX table for the paper."""
    print("\n── LaTeX Table (B1: TX Throughput) ──\n")
    print(r"\begin{table}[htbp]")
    print(r"\centering")
    print(r"\caption{Full-stack TX throughput (B1) across implementations and platforms.}")
    print(r"\label{tab:tx-throughput}")
    print(r"\begin{tabular}{llcrrr}")
    print(r"\toprule")
    print(r"Implementation & Platform & Security & Throughput (CAMs/s) & Latency $\tilde{x}$ (\si{\micro\second}) & Speedup \\")
    print(r"\midrule")

    tx = summary[summary["benchmark"] == "tx"].copy()
    if tx.empty:
        tx = summary.copy()

    # Get CPython baselines for speedup
    for (plat, sec), group in tx.groupby(["platform", "security"]):
        cpython = group[group["implementation"].str.contains("cpython", case=False)]
        baseline = cpython.iloc[0]["throughput_mean"] if not cpython.empty else 1.0

        for _, row in group.iterrows():
            speedup = row["throughput_mean"] / baseline if baseline > 0 else 0
            speedup_str = f"{speedup:.1f}$\\times$" if "cpython" not in row["implementation"].lower() else "1.0$\\times$"
            print(
                f"  {row['implementation']} & {plat} & {sec} & "
                f"${row['throughput_mean']:.0f} \\pm {row['throughput_std']:.0f}$ & "
                f"${row['latency_p50_us']:.1f}$ & {speedup_str} \\\\"
            )
        print(r"\midrule")

    print(r"\bottomrule")
    print(r"\end{tabular}")
    print(r"\end{table}")


# Row order of the paper's latency tables.
# Rows are matched by implementation family (impl_family), so a change of
# interpreter version does not drop rows; the label shows the version found.
_LATENCY_ROWS = [
    ("pypy", "laptop", "PyPy", "Laptop", False),
    ("cpython", "laptop", "CPython", "Laptop", False),
    ("rust", "laptop", "Rust", "Laptop", True),
    None,
    ("pypy", "rpi5", "PyPy", "RPi5", False),
    ("cpython", "rpi5", "CPython", "RPi5", False),
    ("rust", "rpi5", "Rust", "RPi5", True),
    None,
    ("rust-cv2x", "mk6", "Rust-cv2x", "MK6", False),
]


def _row_mask(df: pd.DataFrame, family: str, platform: str) -> pd.Series:
    return (df["implementation"].map(impl_family) == family) & (df["platform"] == platform)


def _impl_label(df: pd.DataFrame, family: str, platform: str, base: str) -> str:
    """'CPython' -> 'CPython~3.13' using the version found in the data."""
    names = sorted(df.loc[_row_mask(df, family, platform), "implementation"].unique())
    if family in ("cpython", "pypy") and names:
        versions = "/".join(n.split("_", 1)[1] for n in names if "_" in n)
        return f"{base}~{versions}" if versions else base
    return base


def _fmt_num(x: float) -> str:
    """One decimal, LaTeX thin space as thousands separator (e.g. 1\\,129.3)."""
    if not np.isfinite(x):
        return "--"
    return f"{x:,.1f}".replace(",", "\\,")


def _fmt_ci(mean: float, half: float) -> str:
    # Half-widths that round to 0.0 are real but tiny (~0.01 µs); show "<0.1".
    half_txt = "$<$0.1" if np.isfinite(half) and half < 0.05 else _fmt_num(half)
    return f"{_fmt_num(mean)}\\,{{\\scriptsize$\\pm${half_txt}}}"


def latency_table_latex(summary: pd.DataFrame, benchmark: str) -> str:
    """LaTeX table of p50/p95/p99 (mean of N runs ± 95% CI half-width)."""
    stats_cols = ("p50", "p95", "p99")
    is_tx = benchmark == "tx"
    label = "tab:latency" if is_tx else "tab:rx_latency"
    what = (
        "from CA Basic Service trigger to loopback/radio write call completion. "
        "Secured latency includes ECDSA-P256 signing."
        if is_tx else
        "from socket read start to CA decoder delivery. "
        "Secured values include ECDSA-P256 verification in the timed path."
    )
    n_vals = summary.loc[summary["benchmark"] == benchmark, "n"]
    n_txt = f"N={int(n_vals.min())}" if n_vals.min() == n_vals.max() else \
        f"N={int(n_vals.min())}--{int(n_vals.max())}"
    df_txt = f"df={int(n_vals.min()) - 1}" if n_vals.min() == n_vals.max() else "df=N-1"

    out = []
    out.append(r"\begin{table}[t]")
    out.append(r"    \centering")
    out.append(
        rf"    \caption{{Per-CAM full-stack {benchmark.upper()} processing latency in $\mu$s, "
        rf"measured {what} Each value is the mean over {n_txt} runs of the per-run "
        rf"percentile, $\pm$ the half-width of its two-sided Student-$t$ 95\% "
        rf"confidence interval ({df_txt}). No runs were excluded.}}"
    )
    out.append(rf"    \label{{{label}}}")
    out.append(r"    \setlength{\tabcolsep}{3pt}")
    out.append(r"    \adjustbox{max width=\columnwidth}{%")
    out.append(r"    \begin{tabular}{l l r r r r r r}")
    out.append(r"        \toprule")
    out.append(r"        \textbf{Impl.} & \textbf{Plat.} &")
    out.append(r"        \multicolumn{3}{c}{\textbf{Unsecured ($\mu$s)}} &")
    out.append(r"        \multicolumn{3}{c}{\textbf{Secured ($\mu$s)}} \\")
    out.append(r"        \cmidrule(lr){3-5}\cmidrule(lr){6-8}")
    out.append(
        r"        & & \textbf{p50} & \textbf{p95} & \textbf{p99} "
        r"& \textbf{p50} & \textbf{p95} & \textbf{p99} \\"
    )
    out.append(r"        \midrule")

    worst = (-1.0, None)
    for spec in _LATENCY_ROWS:
        if spec is None:
            out.append(r"        \midrule")
            continue
        impl_, plat, impl_tex, plat_tex, bold = spec
        impl_tex = _impl_label(summary, impl_, plat, impl_tex)
        cells = []
        for sec in ("off", "on"):
            row = summary[
                _row_mask(summary, impl_, plat)
                & (summary["security"] == sec) & (summary["benchmark"] == benchmark)
            ]
            for st in stats_cols:
                if row.empty:
                    cells.append("--")
                    continue
                r = row.iloc[0]
                cells.append(_fmt_ci(r[f"latency_{st}_us"], r[f"latency_{st}_ci95_half"]))
                if st == "p99" and r["latency_p99_us"] > worst[0]:
                    worst = (r["latency_p99_us"], r["latency_p99_ci95_high"])
        if bold:
            impl_tex, plat_tex = rf"\textbf{{{impl_tex}}}", rf"\textbf{{{plat_tex}}}"
        out.append(f"        {impl_tex} & {plat_tex} & " + " & ".join(cells) + r" \\")

    out.append(r"        \midrule")
    if worst[1] is not None:
        out.append(
            rf"        \multicolumn{{8}}{{l}}{{\emph{{Max.\ p99: {_fmt_num(worst[0])}~$\mu$s "
            rf"(95\% CI upper bound {_fmt_num(worst[1])}~$\mu$s)\;=\;"
            rf"{worst[1] / 1000.0:.1f}\% of $T_\mathrm{{GenCamMin}}$ (100\,000~$\mu$s).}}}} \\"
        )
    out.append(r"        \bottomrule")
    out.append(r"    \end{tabular}")
    out.append(r"    }")
    out.append(r"\end{table}")
    return "\n".join(out) + "\n"


def outlier_sensitivity(df: pd.DataFrame) -> pd.DataFrame:
    """Largest relative change (%) of a cell mean if its Tukey-flagged runs
    were excluded, per metric. Used only to show that keeping them is
    immaterial; the reported statistics always use all runs."""
    rows = []
    for col in ("throughput_cams_s", "latency_p50_us", "latency_p95_us", "latency_p99_us"):
        best = (0.0, None)
        for keys, group in df.groupby(GROUP_COLS):
            v = group[col].dropna().astype(float)
            if len(v) < 4 or v.mean() == 0:
                continue
            kept = v[~tukey_outliers(v)]
            change = abs(kept.mean() - v.mean()) / abs(v.mean()) * 100.0
            if change > best[0]:
                best = (change, keys)
        rows.append({"metric": col, "max_change_pct": best[0],
                     "cell": " | ".join(str(k) for k in best[1]) if best[1] else ""})
    return pd.DataFrame(rows)


def print_outliers(summary: pd.DataFrame, df: pd.DataFrame):
    """Report Tukey-flagged runs. They are diagnostics only and are kept."""
    total_tp = int(summary["outliers_throughput"].sum())
    total_p99 = int(summary["outliers_p99"].sum())
    total_runs = int(summary["n"].sum())
    print("\n── Outlier diagnostics (Tukey 1.5·IQR, flagged only, none removed) ──")
    print(f"  Throughput: {total_tp} of {total_runs} runs flagged; "
          f"p99 latency: {total_p99} of {total_runs} runs flagged.")
    flagged = summary[(summary["outliers_throughput"] > 0) | (summary["outliers_p99"] > 0)]
    for _, row in flagged.iterrows():
        print(
            f"  {row['implementation']:>13s} | {row['platform']:>6s} | {row['security']:>3s} | "
            f"{row['benchmark']:>15s} — throughput runs [{row['outlier_runs_throughput']}], "
            f"p99 runs [{row['outlier_runs_p99']}]"
        )
    print("  Sensitivity (max change of a cell mean if flagged runs were excluded):")
    for _, row in outlier_sensitivity(df).iterrows():
        print(f"    {row['metric']:>18s}: {row['max_change_pct']:.2f}%  ({row['cell']})")


def print_resources(summary: pd.DataFrame):
    """Console table of CPU / memory per cell (only when measured)."""
    if summary["cpu_pct_mean"].isna().all():
        return
    print("\n── Resource usage (mean ± 95% CI half-width over runs) ──")
    print("  cpu_pct: 100 = one core busy; rss_start: stack footprint when the "
          "measurement window opens; peak: VmHWM incl. latency sample buffer")
    for _, r in summary.iterrows():
        if np.isnan(r["cpu_pct_mean"]):
            continue
        thr = ""
        if "throttled_runs" in r and r["throttled_runs"] > 0:
            thr = f"  ⚠ throttled runs [{r['throttled_run_ids']}]"
        print(
            f"  {r['implementation']:>13s} | {r['platform']:>6s} | {r['security']:>3s} | "
            f"{r['benchmark']:>15s} — CPU {r['cpu_pct_mean']:6.1f} ±{r['cpu_pct_ci95_half']:.1f} % | "
            f"RSS start {r['rss_start_mb_mean']:7.2f} ±{r['rss_start_mb_ci95_half']:.2f} MB | "
            f"peak {r['peak_rss_mb_mean']:7.2f} MB{thr}"
        )
    if "throttled_runs" in summary:
        total = int(summary["throttled_runs"].fillna(0).sum())
        print(f"  Runs with a throttling-state change: {total} (kept, not removed)")


def resource_table_latex(summary: pd.DataFrame) -> str:
    """LaTeX table: CPU % and steady-state RSS for full-stack TX and RX."""
    out = [
        r"\begin{table}[t]",
        r"    \centering",
        r"    \caption{Process CPU utilisation (\%, 100 = one core) and resident memory "
        r"(MB) at the start of the measurement window (stack initialised and warmed "
        r"up, before latency samples are stored), for full-stack TX and RX. "
        r"Mean over runs $\pm$ 95\% CI half-width. All benchmarks run at the "
        r"maximum achievable rate, so CPU utilisation reflects a saturated stack.}",
        r"    \label{tab:resources}",
        r"    \setlength{\tabcolsep}{3pt}",
        r"    \adjustbox{max width=\columnwidth}{%",
        r"    \begin{tabular}{l l r r r r r r r r}",
        r"        \toprule",
        r"        \textbf{Impl.} & \textbf{Plat.} &",
        r"        \multicolumn{4}{c}{\textbf{TX}} & \multicolumn{4}{c}{\textbf{RX}} \\",
        r"        \cmidrule(lr){3-6}\cmidrule(lr){7-10}",
        r"        & & \multicolumn{2}{c}{Unsecured} & \multicolumn{2}{c}{Secured} "
        r"& \multicolumn{2}{c}{Unsecured} & \multicolumn{2}{c}{Secured} \\",
        r"        & & CPU & RSS & CPU & RSS & CPU & RSS & CPU & RSS \\",
        r"        \midrule",
    ]
    for spec in _LATENCY_ROWS:
        if spec is None:
            out.append(r"        \midrule")
            continue
        impl_, plat, impl_tex, plat_tex, bold = spec
        impl_tex = _impl_label(summary, impl_, plat, impl_tex)
        cells = []
        for bench in ("tx", "rx"):
            for sec in ("off", "on"):
                row = summary[
                    _row_mask(summary, impl_, plat)
                    & (summary["security"] == sec) & (summary["benchmark"] == bench)
                ]
                if row.empty or np.isnan(row.iloc[0]["cpu_pct_mean"]):
                    cells += ["--", "--"]
                    continue
                r = row.iloc[0]
                cells.append(_fmt_ci(r["cpu_pct_mean"], r["cpu_pct_ci95_half"]))
                cells.append(_fmt_ci(r["rss_start_mb_mean"], r["rss_start_mb_ci95_half"]))
        if bold:
            impl_tex, plat_tex = rf"\textbf{{{impl_tex}}}", rf"\textbf{{{plat_tex}}}"
        out.append(f"        {impl_tex} & {plat_tex} & " + " & ".join(cells) + r" \\")
    out += [
        r"        \bottomrule",
        r"    \end{tabular}",
        r"    }",
        r"\end{table}",
    ]
    return "\n".join(out) + "\n"


_FIXED_RATE_COLS = (("tx", "off", "TX unsec."), ("tx", "on", "TX sec."),
                    ("rx", "off", "RX unsec."), ("rx", "on", "RX sec."),
                    ("security-verify", "on", "Verify"))


def print_fixed_rate(summary: pd.DataFrame):
    """CPU / memory of fixed-rate cells and whether the rate was sustained."""
    fr = summary[summary["target_rate"] > 0]
    if fr.empty:
        return
    print("\n── Fixed-rate cells (CPU at a given load; ✗ = rate not sustained) ──")
    for _, r in fr.sort_values(["platform", "implementation", "benchmark", "security",
                                "target_rate"]).iterrows():
        mark = "✗" if r["below_target"] else "✓"
        print(
            f"  {mark} {r['implementation']:>13s} | {r['platform']:>6s} | {r['security']:>3s} | "
            f"{r['benchmark']:>15s} @ {r['target_rate']:>6g}/s — achieved "
            f"{r['throughput_mean']:8.1f}/s ({r['achieved_ratio'] * 100:5.1f}%) | "
            f"CPU {r['cpu_pct_mean']:6.1f} ±{r['cpu_pct_ci95_half']:.1f} % | "
            f"RSS {r['rss_start_mb_mean']:.2f} MB"
        )


def fixed_rate_table_latex(summary: pd.DataFrame) -> str:
    """LaTeX table: CPU % per (benchmark, security) at each fixed rate."""
    fr = summary[summary["target_rate"] > 0]
    groups = [g for g in _FIXED_RATE_COLS
              if not fr[(fr["benchmark"] == g[0]) & (fr["security"] == g[1])].empty]
    rates = {g: sorted(fr[(fr["benchmark"] == g[0]) & (fr["security"] == g[1])]
                       ["target_rate"].unique()) for g in groups}
    ncols = sum(len(v) for v in rates.values())
    out = [
        r"\begin{table}[t]",
        r"    \centering",
        r"    \caption{Process CPU utilisation (\%, 100 = one core) at fixed message "
        r"rates (msg/s), mean over runs $\pm$ 95\% CI half-width. "
        r"$^\dagger$Rate not sustained (mean throughput below 98\% of target).}",
        r"    \label{tab:fixed_rate}",
        r"    \setlength{\tabcolsep}{3pt}",
        r"    \adjustbox{max width=\columnwidth}{%",
        r"    \begin{tabular}{l l " + "r " * ncols + "}",
        r"        \toprule",
        r"        \textbf{Impl.} & \textbf{Plat.} & " + " & ".join(
            rf"\multicolumn{{{len(rates[g])}}}{{c}}{{\textbf{{{g[2]}}}}}" for g in groups) + r" \\",
    ]
    col, rules = 3, []
    for g in groups:
        rules.append(rf"\cmidrule(lr){{{col}-{col + len(rates[g]) - 1}}}")
        col += len(rates[g])
    out.append("        " + "".join(rules))
    out.append("        & & " + " & ".join(f"{r:g}" for g in groups for r in rates[g]) + r" \\")
    out.append(r"        \midrule")
    for spec in _LATENCY_ROWS:
        if spec is None:
            out.append(r"        \midrule")
            continue
        impl_, plat, impl_tex, plat_tex, bold = spec
        impl_tex = _impl_label(fr, impl_, plat, impl_tex)
        cells = []
        for g in groups:
            for rate in rates[g]:
                row = fr[_row_mask(fr, impl_, plat)
                         & (fr["benchmark"] == g[0]) & (fr["security"] == g[1])
                         & (fr["target_rate"] == rate)]
                if row.empty:
                    cells.append("--")
                    continue
                r = row.iloc[0]
                cell = _fmt_ci(r["cpu_pct_mean"], r["cpu_pct_ci95_half"])
                cells.append(cell + (r"$^\dagger$" if r["below_target"] else ""))
        if all(c == "--" for c in cells):
            continue
        if bold:
            impl_tex, plat_tex = rf"\textbf{{{impl_tex}}}", rf"\textbf{{{plat_tex}}}"
        out.append(f"        {impl_tex} & {plat_tex} & " + " & ".join(cells) + r" \\")
    while out[-1].strip() == r"\midrule":
        out.pop()
    out += [r"        \bottomrule", r"    \end{tabular}", r"    }", r"\end{table}"]
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description="FlexStack Benchmark Analysis")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", "-i", nargs="+",
                        help="CSV results file(s); several campaigns are concatenated")
    source.add_argument("--campaign", type=str,
                        help="campaign folder with platforms.csv and raw/<host>/ "
                        "(e.g. ../results/campaign_2026-11)")
    parser.add_argument("--latex", action="store_true", help="Generate LaTeX tables")
    parser.add_argument(
        "--latex-dir",
        type=str,
        default=None,
        help="Write the TX/RX latency tables (p50/p95/p99 with 95%% CI) "
        "as tab_latency.tex and tab_rx_latency.tex into this directory",
    )
    parser.add_argument(
        "--output-summary",
        type=str,
        default=None,
        help="Save summary CSV to this path",
    )
    args = parser.parse_args()

    inputs = campaign_inputs(args.campaign) if args.campaign else args.input
    df = load_results(inputs)
    if args.campaign:
        df = drop_superseded(df, args.campaign)
    print(f"Loaded {len(df)} result rows from {len(inputs)} file(s)")

    summary_all = summarize(df)
    # Max-rate cells feed the existing throughput / latency / resource tables.
    summary = summary_all[summary_all["target_rate"] <= 0].reset_index(drop=True)
    print_summary(summary_all)
    compute_speedup(summary)

    print_outliers(summary_all, df)
    print_resources(summary)
    print_fixed_rate(summary_all)

    if args.latex:
        generate_latex(summary)
        for bench in ("tx", "rx"):
            if not (summary["benchmark"] == bench).any():
                continue
            print(f"\n── LaTeX Table ({bench.upper()} latency, 95% CI) ──\n")
            print(latency_table_latex(summary, bench))

    if args.latex_dir:
        os.makedirs(args.latex_dir, exist_ok=True)
        for bench, name in (("tx", "tab_latency.tex"), ("rx", "tab_rx_latency.tex")):
            if not (summary["benchmark"] == bench).any():
                continue
            path = os.path.join(args.latex_dir, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(latency_table_latex(summary, bench))
            print(f"LaTeX table written to {path}")
        if (summary_all["target_rate"] > 0).any():
            path = os.path.join(args.latex_dir, "tab_fixed_rate.tex")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(fixed_rate_table_latex(summary_all))
            print(f"LaTeX table written to {path}")
        if not summary["cpu_pct_mean"].isna().all():
            path = os.path.join(args.latex_dir, "tab_resources.tex")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(resource_table_latex(summary))
            print(f"LaTeX table written to {path}")

    if args.output_summary:
        summary_all.to_csv(args.output_summary, index=False)
        print(f"\nSummary saved to {args.output_summary}")

    # Flag high-variability cells
    high_cv = summary_all[summary_all["cv_pct"] > 5.0]
    if not high_cv.empty:
        print("\n⚠ High variability cells (CV > 5%):")
        for _, row in high_cv.iterrows():
            print(
                f"  {row['implementation']} | {row['platform']} | {row['security']} | "
                f"{row['benchmark']} — CV = {row['cv_pct']:.1f}%"
            )


if __name__ == "__main__":
    main()
