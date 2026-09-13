"""
Requirement 8 - Concurrent User Handling Capacity & Load Testing Module.
Executes non-destructive, safe asynchronous load benchmarking against target endpoints:
- Concurrent simulated user sessions
- Requests Per Second (RPS) throughput
- Average latency (ms) & Median latency (ms)
- 95th percentile (P95) latency (ms)
- Error rate (%) & Success/Failure breakdown
- Feeds benchmark metrics directly into PerformanceMetricsCollector if run in-process or via CLI
"""

import argparse
import asyncio
import time
from datetime import datetime
from statistics import mean, median
from typing import Dict, List, Any, Optional
import urllib.request
import urllib.error
import json


async def _make_request(url: str, headers: Optional[dict] = None) -> Dict[str, Any]:
    """Asynchronous HTTP worker for load test."""
    loop = asyncio.get_event_loop()
    t_start = time.perf_counter()

    def _sync_fetch():
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                status_code = resp.getcode()
                body = resp.read()
                return {"status_code": status_code, "ok": 200 <= status_code < 400, "error": None}
        except urllib.error.HTTPError as e:
            return {"status_code": e.code, "ok": 200 <= e.code < 400, "error": str(e)}
        except Exception as e:
            return {"status_code": 0, "ok": False, "error": str(e)}

    res = await loop.run_in_executor(None, _sync_fetch)
    duration_ms = (time.perf_counter() - t_start) * 1000.0
    res["duration_ms"] = duration_ms
    return res


async def run_load_benchmark(
    base_url: str = "http://127.0.0.1:8000",
    endpoints: Optional[List[str]] = None,
    concurrency: int = 10,
    duration_seconds: int = 5,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes controlled concurrent load testing against endpoints for a specified duration.
    """
    if endpoints is None:
        endpoints = [
            "/api/health",
            "/api/alarms/active",
            "/api/challenges/types"
        ]

    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    urls = [f"{base_url.rstrip('/')}{ep}" for ep in endpoints]
    total_requests = 0
    successful_requests = 0
    failed_requests = 0
    durations: List[float] = []

    stop_event = asyncio.Event()
    start_time = time.perf_counter()

    async def _worker():
        nonlocal total_requests, successful_requests, failed_requests
        req_idx = 0
        while not stop_event.is_set():
            target_url = urls[req_idx % len(urls)]
            req_idx += 1
            res = await _make_request(target_url, headers)
            durations.append(res["duration_ms"])
            total_requests += 1
            if res["ok"]:
                successful_requests += 1
            else:
                failed_requests += 1
            # Small yield to prevent thread starvation
            await asyncio.sleep(0.01)

    # Launch concurrent worker tasks
    tasks = [asyncio.create_task(_worker()) for _ in range(concurrency)]

    # Wait for test duration
    await asyncio.sleep(duration_seconds)
    stop_event.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    total_time = time.perf_counter() - start_time
    rps = round(total_requests / max(0.001, total_time), 2)
    error_rate = round((failed_requests / max(1, total_requests)) * 100.0, 2)

    if durations:
        sorted_d = sorted(durations)
        avg_lat = round(mean(sorted_d), 2)
        med_lat = round(median(sorted_d), 2)
        p95_idx = int(round(0.95 * (len(sorted_d) - 1)))
        p95_lat = round(sorted_d[p95_idx], 2)
        max_lat = round(max(sorted_d), 2)
        min_lat = round(min(sorted_d), 2)
    else:
        avg_lat = None
        med_lat = None
        p95_lat = None
        max_lat = None
        min_lat = None

    result = {
        "status": "available",
        "concurrent_users_tested": concurrency,
        "duration_seconds": round(total_time, 2),
        "total_requests": total_requests,
        "successful_requests": successful_requests,
        "failed_requests": failed_requests,
        "requests_per_second": rps,
        "average_latency_ms": avg_lat,
        "median_latency_ms": med_lat,
        "p95_latency_ms": p95_lat,
        "min_latency_ms": min_lat,
        "max_latency_ms": max_lat,
        "error_rate_pct": error_rate,
        "tested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "message": f"Successfully benchmarked {concurrency} concurrent simulated users @ {rps} req/sec."
    }

    # Attempt to record into local metrics collector if available in process
    try:
        from services.metrics_collector import metrics_collector
        metrics_collector.record_load_test_result(result)
    except Exception:
        pass

    return result


def main():
    parser = argparse.ArgumentParser(description="WakeWise Real Concurrent Load Testing Tool")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base backend URL")
    parser.add_argument("--concurrency", type=int, default=10, help="Number of concurrent users")
    parser.add_argument("--duration", type=int, default=5, help="Test duration in seconds")
    parser.add_argument("--token", default=None, help="Optional admin/user JWT bearer token")
    args = parser.parse_args()

    print(f"=== Starting WakeWise Load Test ===")
    print(f"Target URL:    {args.url}")
    print(f"Concurrency:   {args.concurrency} concurrent users")
    print(f"Duration:      {args.duration} seconds")
    print("---------------------------------------")

    results = asyncio.run(run_load_benchmark(
        base_url=args.url,
        concurrency=args.concurrency,
        duration_seconds=args.duration,
        token=args.token
    ))

    print(json.dumps(results, indent=2))
    print("---------------------------------------")
    print(f"RESULT: {results['requests_per_second']} req/sec | Avg: {results['average_latency_ms']}ms | P95: {results['p95_latency_ms']}ms | Errors: {results['error_rate_pct']}%")


if __name__ == "__main__":
    main()
