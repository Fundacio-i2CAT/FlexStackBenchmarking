// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2024 Fundació Privada Internet i Innovació Digital a Catalunya (i2CAT)
//! Fixed-rate pacing for the measurement loops (`--rate`).
//!
//! Shared by `flexstack-bench` and `flexstack-bench-cv2x`, and mirrored by
//! `Pacer` in `python/benchmark.py`.
//!
//! Message `i` is released at `start + i / rate` (absolute schedule, so timing
//! errors do not accumulate). The thread *sleeps* until the release time, so
//! the process CPU time measured over the window is the cost of the work
//! itself, not of waiting. A message that is already late is released
//! immediately and counted; the schedule is not compressed to catch up, so an
//! implementation that cannot sustain the rate simply shows an achieved
//! throughput below `rate`.

use std::thread;
use std::time::{Duration, Instant};

pub struct Pacer {
    start: Instant,
    interval: Duration,
    next: u64,
    late: u64,
}

impl Pacer {
    /// `rate` in messages per second; `None` when `rate <= 0` (max rate).
    pub fn new(rate: f64, start: Instant) -> Option<Self> {
        if rate.is_finite() && rate > 0.0 {
            Some(Self {
                start,
                interval: Duration::from_secs_f64(1.0 / rate),
                next: 0,
                late: 0,
            })
        } else {
            None
        }
    }

    /// Sleep until the next release time. Returns `false` (without sleeping)
    /// when that release time is at or after `end`, i.e. the window is over.
    pub fn wait(&mut self, end: Instant) -> bool {
        let release = self.start + self.interval.mul_f64(self.next as f64);
        if release >= end {
            return false;
        }
        self.next += 1;
        let now = Instant::now();
        if release > now {
            thread::sleep(release - now);
        } else if self.next > 1 {
            self.late += 1;
        }
        true
    }

    /// Messages released later than scheduled.
    pub fn late(&self) -> u64 {
        self.late
    }
}

/// Wait for the next slot if pacing is enabled; `false` ends the loop.
pub fn pace(pacer: &mut Option<Pacer>, end: Instant) -> bool {
    match pacer {
        Some(p) => p.wait(end),
        None => true,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_or_negative_rate_disables_pacing() {
        assert!(Pacer::new(0.0, Instant::now()).is_none());
        assert!(Pacer::new(-5.0, Instant::now()).is_none());
        assert!(Pacer::new(f64::NAN, Instant::now()).is_none());
        let mut none: Option<Pacer> = None;
        assert!(pace(&mut none, Instant::now()));
    }

    #[test]
    fn releases_at_the_requested_rate() {
        let start = Instant::now();
        let end = start + Duration::from_millis(300);
        let mut p = Pacer::new(100.0, start);
        let mut n = 0;
        while pace(&mut p, end) {
            n += 1;
        }
        // 300 ms at 100 msg/s -> releases at 0, 10, ..., 290 ms = 30 messages.
        assert_eq!(n, 30);
        let elapsed = start.elapsed();
        assert!(elapsed >= Duration::from_millis(290), "{elapsed:?}");
        assert!(elapsed < Duration::from_millis(400), "{elapsed:?}");
    }

    #[test]
    fn late_messages_are_counted_not_bursted() {
        let start = Instant::now();
        let mut p = Pacer::new(1000.0, start).unwrap();
        thread::sleep(Duration::from_millis(20));
        let end = start + Duration::from_secs(10);
        // First call is slot 0 (never counted late), the next ones are late.
        for _ in 0..5 {
            assert!(p.wait(end));
        }
        assert_eq!(p.late(), 4);
    }
}

/// Wait until `counter` differs from `prev` (the packet reached the wire, or
/// the receiver), for the per-packet latency loops.
///
/// Busy-waits as before: the measured path is unchanged while the stack makes
/// progress (a packet takes tens of microseconds). The runs are started with
/// `chrt -f 50` on two pinned cores, so every stack thread has the same
/// SCHED_FIFO priority and a spinning thread is never preempted by the thread
/// that would deliver the packet on the same core; a lost packet would also
/// spin forever. After 50 ms without progress the wait yields the CPU on each
/// iteration (`sched_yield` lets equal-priority threads run), and after 1 s
/// it gives up: `false`, the packet is counted as lost.
pub fn wait_for_change(counter: &std::sync::atomic::AtomicU64, prev: u64) -> bool {
    use std::sync::atomic::Ordering;
    const YIELD_AFTER: Duration = Duration::from_millis(50);
    const GIVE_UP_AFTER: Duration = Duration::from_secs(1);
    let start = Instant::now();
    let mut spins: u32 = 0;
    while counter.load(Ordering::Acquire) == prev {
        spins = spins.wrapping_add(1);
        if spins.is_multiple_of(1024) {
            let waited = start.elapsed();
            if waited >= GIVE_UP_AFTER {
                return false;
            }
            if waited >= YIELD_AFTER {
                thread::yield_now();
                continue;
            }
        }
        std::hint::spin_loop();
    }
    true
}

/// Wait until `counter` has not changed for 100 ms, i.e. the stack has
/// finished the packets queued before the call. Gives up after 30 s and
/// returns `false`. Used between the warm-up and the measurement window.
pub fn wait_quiescent(counter: &std::sync::atomic::AtomicU64) -> bool {
    wait_quiescent_for(counter, Duration::from_millis(100), Duration::from_secs(30))
}

fn wait_quiescent_for(
    counter: &std::sync::atomic::AtomicU64,
    idle: Duration,
    give_up: Duration,
) -> bool {
    use std::sync::atomic::Ordering;
    let start = Instant::now();
    let mut last = counter.load(Ordering::Acquire);
    let mut since = Instant::now();
    loop {
        thread::sleep(Duration::from_millis(5));
        let now = counter.load(Ordering::Acquire);
        if now != last {
            last = now;
            since = Instant::now();
        } else if since.elapsed() >= idle {
            return true;
        }
        if start.elapsed() >= give_up {
            return false;
        }
    }
}

#[cfg(test)]
mod quiescent_tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::Arc;

    #[test]
    fn idle_counter_is_quiescent_after_the_idle_time() {
        let c = AtomicU64::new(7);
        let t = Instant::now();
        assert!(wait_quiescent_for(&c, Duration::from_millis(50), Duration::from_secs(5)));
        assert!(t.elapsed() >= Duration::from_millis(50));
    }

    #[test]
    fn waits_while_the_counter_keeps_changing() {
        let c = Arc::new(AtomicU64::new(0));
        let c2 = Arc::clone(&c);
        let busy = thread::spawn(move || {
            for _ in 0..40 {
                c2.fetch_add(1, Ordering::Release);
                thread::sleep(Duration::from_millis(5));
            }
        });
        let t = Instant::now();
        assert!(wait_quiescent_for(&c, Duration::from_millis(50), Duration::from_secs(5)));
        // The counter changed for ~200 ms, so the wait lasted at least that long
        assert!(t.elapsed() >= Duration::from_millis(200), "{:?}", t.elapsed());
        assert_eq!(c.load(Ordering::Acquire), 40);
        busy.join().unwrap();
    }

    #[test]
    fn gives_up_when_the_counter_never_settles() {
        let c = Arc::new(AtomicU64::new(0));
        let stop = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let (c2, s2) = (Arc::clone(&c), Arc::clone(&stop));
        let busy = thread::spawn(move || {
            while !s2.load(Ordering::Relaxed) {
                c2.fetch_add(1, Ordering::Release);
                thread::sleep(Duration::from_millis(2));
            }
        });
        assert!(!wait_quiescent_for(&c, Duration::from_millis(50), Duration::from_millis(300)));
        stop.store(true, Ordering::Relaxed);
        busy.join().unwrap();
    }
}
