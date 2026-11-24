// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2024 Fundació Privada Internet i Innovació Digital a Catalunya (i2CAT)
//! Process CPU and memory accounting over the measurement window.
//!
//! Shared by `flexstack-bench` and `flexstack-bench-cv2x`, and mirrored by
//! `python/benchmark.py` (`ResourceSnapshot`) so that every implementation is
//! measured the same way, from the same Linux `/proc/self` counters:
//!
//! - `cpu_pct`: (utime + stime) consumed by the whole process (all threads,
//!   including kernel time spent on its behalf, e.g. socket I/O) during the
//!   measurement window, divided by the window's wall-clock time, × 100.
//!   100 = one fully busy core; the upper bound is 100 × pinned cores.
//! - `rss_start_mb`: resident set size when the measurement window opens. The
//!   stack is initialised and warmed up, but no latency samples have been
//!   recorded yet, so this is the stack's steady-state footprint.
//! - `peak_rss_mb`: process high-water mark (VmHWM). It includes the harness's
//!   latency sample buffer, so it is an upper bound on the stack's memory use.
//!
//! Values are NaN when `/proc` is unavailable.

use std::fs;
use std::time::Instant;

/// Kernel USER_HZ, the unit of utime/stime in /proc/<pid>/stat. It is fixed
/// at 100 in the Linux user-space ABI on x86_64 and aarch64.
const USER_HZ: f64 = 100.0;

/// CPU and memory usage over one measurement window.
#[derive(Debug, Clone, Copy)]
pub struct ResourceUsage {
    pub cpu_pct: f64,
    pub rss_start_mb: f64,
    pub peak_rss_mb: f64,
}

/// Counters captured when the measurement window opens.
pub struct ResourceSnapshot {
    cpu_ticks: Option<u64>,
    wall: Instant,
    rss_kb: Option<u64>,
}

impl ResourceSnapshot {
    /// Capture the counters. Call immediately before the measurement loop.
    pub fn take() -> Self {
        Self {
            cpu_ticks: cpu_ticks(),
            wall: Instant::now(),
            rss_kb: status_kb("VmRSS:"),
        }
    }

    /// Close the window. Call immediately after the measurement loop.
    pub fn finish(&self) -> ResourceUsage {
        let wall_s = self.wall.elapsed().as_secs_f64();
        let cpu_pct = match (self.cpu_ticks, cpu_ticks()) {
            (Some(a), Some(b)) if wall_s > 0.0 => (b.saturating_sub(a) as f64 / USER_HZ) / wall_s * 100.0,
            _ => f64::NAN,
        };
        ResourceUsage {
            cpu_pct,
            rss_start_mb: self.rss_kb.map_or(f64::NAN, kb_to_mb),
            peak_rss_mb: status_kb("VmHWM:").map_or(f64::NAN, kb_to_mb),
        }
    }
}

fn kb_to_mb(kb: u64) -> f64 {
    kb as f64 / 1024.0
}

/// utime + stime of the whole process, in clock ticks.
fn cpu_ticks() -> Option<u64> {
    parse_stat_cpu_ticks(&fs::read_to_string("/proc/self/stat").ok()?)
}

/// Parse utime (field 14) + stime (field 15) from a /proc/<pid>/stat line.
/// The command name (field 2) may contain spaces, so fields are counted from
/// the last ')'.
fn parse_stat_cpu_ticks(stat: &str) -> Option<u64> {
    let rest = &stat[stat.rfind(')')? + 1..];
    let fields: Vec<&str> = rest.split_whitespace().collect();
    // fields[0] is field 3 (state), so field N is fields[N - 3].
    let utime: u64 = fields.get(11)?.parse().ok()?;
    let stime: u64 = fields.get(12)?.parse().ok()?;
    Some(utime + stime)
}

/// Read a `kB` entry (e.g. `VmRSS:`) from /proc/self/status.
fn status_kb(key: &str) -> Option<u64> {
    parse_status_kb(&fs::read_to_string("/proc/self/status").ok()?, key)
}

fn parse_status_kb(status: &str, key: &str) -> Option<u64> {
    status
        .lines()
        .find(|l| l.starts_with(key))?
        .split_whitespace()
        .nth(1)?
        .parse()
        .ok()
}

/// Exit with an error if `path` exists with a different CSV header, so a new
/// campaign never appends rows with extra columns to an old-format file.
pub fn ensure_csv_header(path: &str, header: &str) {
    if let Ok(text) = fs::read_to_string(path) {
        if let Some(first) = text.lines().next() {
            if first != header {
                eprintln!(
                    "ERROR: {} has a different CSV header (older schema?). \
                     Use a new output file.",
                    path
                );
                std::process::exit(2);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_stat_with_spaces_in_comm() {
        let line = "1234 (my (odd) prog) R 1 2 3 4 5 6 7 8 9 10 250 70 0 0 20 0 3 0";
        assert_eq!(parse_stat_cpu_ticks(line), Some(320));
    }

    #[test]
    fn parses_status_kb() {
        let s = "Name:\tx\nVmHWM:\t   20480 kB\nVmRSS:\t   10240 kB\n";
        assert_eq!(parse_status_kb(s, "VmRSS:"), Some(10240));
        assert_eq!(parse_status_kb(s, "VmHWM:"), Some(20480));
        assert_eq!(parse_status_kb(s, "VmSwap:"), None);
    }

    #[test]
    fn live_snapshot_is_finite_on_linux() {
        let snap = ResourceSnapshot::take();
        let mut x = 0u64;
        for i in 0..5_000_000u64 {
            x = x.wrapping_add(i * i);
        }
        std::hint::black_box(x);
        let u = snap.finish();
        assert!(u.cpu_pct.is_finite() && u.cpu_pct >= 0.0);
        assert!(u.rss_start_mb > 0.0 && u.peak_rss_mb >= u.rss_start_mb);
    }
}
