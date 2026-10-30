#!/usr/bin/env python3
"""Benchmark uncached JMESPath parsing of long raw-string literals.

Usage:
    PYTHONPATH=/path/to/jmespath python3 benchmark/bench.py --impl baseline
    PYTHONPATH=/path/to/patched-jmespath python3 benchmark/bench.py --impl optimized

Each scale runs WARMUP untimed parses followed by REPS timed parses.  Every
timed sample is written to benchmark/raw/<impl>-<scale>-<i>.json; the
aggregate is written to benchmark/<impl>.json.

The parser caches results by expression text, so the cache is cleared before
each parse to measure real (uncached) parsing work.
"""
import argparse
import hashlib
import json
import os
import platform
import random
import statistics
import sys
import time

SEED = 20261031
SCALES = {"small": 8192, "medium": 32768, "large": 131072}
WARMUP = 3
REPS = 5


def make_expression(payload_bytes):
    """Deterministic payload: same bytes for baseline and optimized runs."""
    rnd = random.Random(SEED + payload_bytes)
    alphabet = "abcXYZ_09"
    payload = "".join(rnd.choice(alphabet) for _ in range(payload_bytes))
    return "'" + payload + "'"


def cpu_model():
    try:
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def mem_total_kb():
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


def env_info():
    return {
        "python": sys.version.split()[0],
        "python_full": sys.version,
        "platform": platform.platform(),
        "cpu_model": cpu_model(),
        "mem_total_kb": mem_total_kb(),
        "processor_count": os.cpu_count(),
    }


def percentile(values, q):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl", required=True, choices=["baseline", "optimized"])
    ap.add_argument("--outdir", default=os.path.join(os.path.dirname(os.path.abspath(__file__))))
    args = ap.parse_args()

    from jmespath.parser import Parser

    raw_dir = os.path.join(args.outdir, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    results = {}
    for scale, payload_bytes in SCALES.items():
        expression = make_expression(payload_bytes)
        digest = hashlib.sha256(expression.encode("utf-8")).hexdigest()

        for _ in range(WARMUP):
            Parser._CACHE.clear()
            Parser().parse(expression)

        samples = []
        for i in range(REPS):
            Parser._CACHE.clear()
            start = time.perf_counter()
            Parser().parse(expression)
            elapsed = time.perf_counter() - start
            samples.append(elapsed)
            raw = {
                "impl": args.impl,
                "scale": scale,
                "payload_bytes": payload_bytes,
                "iteration": i,
                "seconds": elapsed,
                "seed": SEED,
                "expression_sha256": digest,
            }
            with open(os.path.join(raw_dir, "%s-%s-%d.json" % (args.impl, scale, i)), "w") as fh:
                json.dump(raw, fh, sort_keys=True, indent=2)
                fh.write("\n")

        mean = statistics.fmean(samples)
        results[scale] = {
            "payload_bytes": payload_bytes,
            "expression_sha256": digest,
            "warmup": WARMUP,
            "reps": REPS,
            "samples_s": samples,
            "median_s": statistics.median(samples),
            "p25_s": percentile(samples, 0.25),
            "p75_s": percentile(samples, 0.75),
            "mean_s": mean,
            "stdev_s": statistics.stdev(samples),
            "rel_stdev": statistics.stdev(samples) / mean,
        }

    doc = {
        "impl": args.impl,
        "seed": SEED,
        "warmup": WARMUP,
        "reps": REPS,
        "clock": "time.perf_counter",
        "scales": list(SCALES),
        "command": " ".join(sys.argv),
        "env": env_info(),
        "results": results,
    }
    out = os.path.join(args.outdir, "%s.json" % args.impl)
    with open(out, "w") as fh:
        json.dump(doc, fh, sort_keys=True, indent=2)
        fh.write("\n")
    for scale in SCALES:
        r = results[scale]
        print("%-8s %8d B  median %9.3f ms  p25 %9.3f ms  p75 %9.3f ms  rel_stdev %5.1f%%"
              % (scale, r["payload_bytes"], r["median_s"] * 1e3,
                 r["p25_s"] * 1e3, r["p75_s"] * 1e3, r["rel_stdev"] * 100))
    print("wrote", out)


if __name__ == "__main__":
    main()
