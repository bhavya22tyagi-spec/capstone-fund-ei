#!/usr/bin/env python
"""
Load testing scaffolding — PRD §19.7.

Gates (PRD §19.7):
  p95 latency < 2000ms
  error rate  < 1%

Usage:
  python scripts/load_test.py                             # defaults: 10 users, 30s
  python scripts/load_test.py --url http://localhost:8000 --users 20 --duration 60

Requires: httpx  (pip install httpx)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from statistics import mean, quantiles

try:
    import httpx
except ImportError:
    print("httpx not installed. Run: pip install httpx", file=sys.stderr)
    sys.exit(1)

_ENDPOINTS = [
    ("GET", "/api/health"),
    ("GET", "/api/dashboard"),
    ("GET", "/api/funds"),
    ("GET", "/api/evals"),
]


async def _worker(
    client: httpx.AsyncClient,
    results: list[dict],
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        for method, path in _ENDPOINTS:
            t0 = time.perf_counter()
            try:
                r = await client.request(method, path)
                ms = (time.perf_counter() - t0) * 1000
                results.append({"path": path, "status": r.status_code, "ms": ms, "ok": r.status_code < 400})
            except Exception:
                ms = (time.perf_counter() - t0) * 1000
                results.append({"path": path, "status": 0, "ms": ms, "ok": False})


async def run_load_test(base_url: str, users: int, duration: int) -> bool:
    results: list[dict] = []
    stop = asyncio.Event()

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        tasks = [asyncio.create_task(_worker(client, results, stop)) for _ in range(users)]
        await asyncio.sleep(duration)
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    if not results:
        print("No results — is the API running?", file=sys.stderr)
        return False

    ok = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]
    latencies = [r["ms"] for r in ok]

    print(f"\n{'='*60}")
    print(f"Load Test — {users} concurrent users × {duration}s @ {base_url}")
    print(f"{'='*60}")
    print(f"  Total requests:  {len(results):>6}")
    print(f"  Successful:      {len(ok):>6}  ({100*len(ok)/len(results):.1f}%)")
    print(f"  Failed:          {len(fail):>6}  ({100*len(fail)/len(results):.1f}%)")

    p95 = float("inf")
    p99 = float("inf")
    if latencies:
        qs = quantiles(latencies, n=100)
        p50, p95, p99 = qs[49], qs[94], qs[98]
        print(f"  Latency p50:     {p50:>6.0f}ms")
        print(f"  Latency p95:     {p95:>6.0f}ms  ← PRD §19.7 gate: < 2000ms")
        print(f"  Latency p99:     {p99:>6.0f}ms")
        print(f"  Mean latency:    {mean(latencies):>6.0f}ms")
    print(f"  Throughput:      {len(results)/duration:>6.1f} req/s")

    # Per-endpoint breakdown
    print("\n  Per-endpoint (successes only):")
    for method, path in _ENDPOINTS:
        ep_lats = [r["ms"] for r in ok if r["path"] == path]
        if ep_lats:
            qs2 = quantiles(ep_lats, n=100) if len(ep_lats) >= 4 else ep_lats
            p95e = qs2[94] if len(ep_lats) >= 4 else max(ep_lats)
            print(f"    {path:<30} n={len(ep_lats):>4}  p95={p95e:.0f}ms")

    error_rate = len(fail) / len(results)
    gate_p95 = p95 < 2000
    gate_err = error_rate < 0.01
    gate_ok = gate_p95 and gate_err

    print(f"\nPRD §19.7 Performance Gate")
    print(f"  p95 < 2000ms:   {'PASS' if gate_p95 else 'FAIL'}  ({p95:.0f}ms)")
    print(f"  Error rate <1%: {'PASS' if gate_err else 'FAIL'}  ({error_rate*100:.1f}%)")
    print(f"  Overall:        {'PASS' if gate_ok else 'FAIL'}")
    print()
    return gate_ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Load test — PRD §19.7")
    parser.add_argument("--url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--users", type=int, default=10, help="Concurrent users")
    parser.add_argument("--duration", type=int, default=30, help="Test duration in seconds")
    args = parser.parse_args()
    passed = asyncio.run(run_load_test(args.url, args.users, args.duration))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
