"""bridge_test.py — PLAN.md Phase 0 / build step 3, the Linux half.

Runs ON THE UNO Q's Linux side (Qualcomm QRB2210, Debian), as an App Lab Python app or
anywhere `arduino.app_utils` is importable on the board. Talks to the MCU sketch
firmware/eyes_mcu/eyes_mcu.ino over Arduino_RouterBridge.

It does the three things Phase 0 and step 3 ask for:
  1. toggles the MCU's LED a few times     (Phase 0 pass check: "a Python call toggles an MCU pin")
  2. measures Bridge round-trip latency     (step 3 check: "round-trip latency logged")
  3. estimates the MCU-vs-Linux clock offset (groundwork for step 5, timestamping)

Results print to stdout and append one CSV row per run to bridge_log.csv beside this file,
so runs can be compared over time.

Runs with plain python3 on the board (via qbridge.py) or inside App Lab. First run
2026-11-05: 200/200 pings, RTT median 5.8 ms, clock offset bound +/-2.9 ms (PLAN.md changelog).
"""
import csv
import os
import statistics
import time

try:
    from arduino.app_utils import Bridge   # inside an App Lab app
except ImportError:
    from qbridge import Bridge             # plain python3 on the board (qbridge.py beside this)

N_PINGS = 200
N_CLOCK = 50
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge_log.csv")


def now_us() -> float:
    return time.monotonic_ns() / 1000.0


def toggle_led(times: int = 3, period_s: float = 0.5) -> None:
    for i in range(times):
        for on in (True, False):
            got = Bridge.call("set_led", on)
            print(f"[led] set_led({on}) -> {got}")
            time.sleep(period_s / 2)


def measure_rtt(n: int) -> list:
    rtts = []
    for i in range(n):
        t0 = now_us()
        got = Bridge.call("ping", i)
        t1 = now_us()
        if got != i:
            print(f"[ping] MISMATCH sent {i} got {got!r}")
            continue
        rtts.append(t1 - t0)
    return rtts


def measure_clock_offset(n: int):
    """offset = mcu_us - linux_us at the same instant, from the lowest-RTT sample.

    The MCU sample is assumed to land at the midpoint of the call; the error of that
    assumption is at most RTT/2, so the lowest-RTT sample is the best estimate.
    mcu_micros is 32-bit and wraps every ~71.6 min; within one short run the
    samples are unwrapped relative to the first one.
    """
    best = None
    base = None
    for _ in range(n):
        t0 = now_us()
        m = Bridge.call("mcu_micros")
        t1 = now_us()
        if base is None:
            base = m
        m_unwrapped = base + ((m - base) & 0xFFFFFFFF)
        rtt = t1 - t0
        offset = m_unwrapped - (t0 + t1) / 2
        if best is None or rtt < best[0]:
            best = (rtt, offset)
    return best


def pct(sorted_vals, p):
    if not sorted_vals:
        return float("nan")
    k = min(len(sorted_vals) - 1, int(round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[k]


def main():
    global LOG
    print("[mcu]", Bridge.call("status"))

    if getattr(Bridge, "remote", False):
        # Run from the PC through `adb forward`: every call also crosses USB + adbd, so the
        # numbers below are PC<->MCU, not the board's own Linux<->MCU Bridge. Keep them out
        # of the board log. For the real step-3 numbers, run it ON the board (CLAUDE.md).
        LOG = LOG.replace("bridge_log.csv", "bridge_log_remote.csv")
        print("[via] PC -> adb -> board: timings include USB, NOT the on-board Bridge")

    toggle_led()

    rtts = sorted(measure_rtt(N_PINGS))
    if rtts:
        print(f"[rtt] n={len(rtts)}/{N_PINGS}  min={rtts[0]:.0f} us  "
              f"median={statistics.median(rtts):.0f} us  p95={pct(rtts, 95):.0f} us  "
              f"max={rtts[-1]:.0f} us")

    best = measure_clock_offset(N_CLOCK)
    if best:
        print(f"[clock] mcu - linux = {best[1]:.0f} us  (+/- {best[0] / 2:.0f} us, "
              f"from the lowest-RTT of {N_CLOCK} probes)")

    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["unix_time", "n_ok", "rtt_min_us", "rtt_median_us", "rtt_p95_us",
                        "rtt_max_us", "clock_offset_us", "clock_bound_us"])
        w.writerow([int(time.time()), len(rtts),
                    f"{rtts[0]:.0f}" if rtts else "",
                    f"{statistics.median(rtts):.0f}" if rtts else "",
                    f"{pct(rtts, 95):.0f}" if rtts else "",
                    f"{rtts[-1]:.0f}" if rtts else "",
                    f"{best[1]:.0f}" if best else "", f"{best[0] / 2:.0f}" if best else ""])
    print(f"[log] appended to {LOG}")


if __name__ == "__main__":
    main()
