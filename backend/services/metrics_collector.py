import time
import threading
from collections import deque, defaultdict
from statistics import mean, median
from typing import Dict, List, Optional, Any

class PerformanceMetricsCollector:
    """
    Thread-safe in-memory sliding window collector for real server-side performance metrics:
    - API endpoint request latencies (count, avg, median, P95, slowest endpoints)
    - Challenge generation latencies (AI Gemini/Groq vs local fallback, P95, success/fail)
    - Dashboard loading speed benchmarks
    - Concurrent load test results store
    """
    def __init__(self, max_records: int = 5000):
        self._lock = threading.RLock()
        self.max_records = max_records
        # Store individual request records: (path, method, status_code, duration_ms, timestamp)
        self._request_records = deque(maxlen=max_records)
        # Store challenge generation records: (challenge_type, difficulty, provider, duration_ms, success, is_fallback, timestamp)
        self._challenge_records = deque(maxlen=1000)
        # Store last known load test result
        self._last_load_test: Optional[Dict[str, Any]] = None

    def record_request(self, path: str, method: str, status_code: int, duration_ms: float):
        """Records an API request timing while omitting sensitive paths/tokens."""
        # Sanitize sensitive query parameters or identifiers
        clean_path = path.split("?")[0]
        with self._lock:
            self._request_records.append({
                "path": clean_path,
                "method": method.upper(),
                "status_code": status_code,
                "duration_ms": round(float(duration_ms), 2),
                "timestamp": time.time()
            })

    def record_challenge_generation(
        self,
        challenge_type: str,
        difficulty: str,
        provider: str,
        duration_ms: float,
        success: bool = True,
        is_fallback: bool = False
    ):
        """Records challenge generation duration, provider, and fallback status."""
        with self._lock:
            self._challenge_records.append({
                "challenge_type": challenge_type,
                "difficulty": difficulty,
                "provider": provider,
                "duration_ms": round(float(duration_ms), 2),
                "success": bool(success),
                "is_fallback": bool(is_fallback),
                "timestamp": time.time()
            })

    def record_load_test_result(self, result: Dict[str, Any]):
        """Saves results from a local/staging load test run."""
        with self._lock:
            self._last_load_test = result

    def get_api_metrics(self, path_filter: Optional[str] = None) -> Dict[str, Any]:
        """Calculates request count, avg, median, P95, and slowest requests."""
        with self._lock:
            records = list(self._request_records)

        if path_filter:
            records = [r for r in records if path_filter in r["path"]]

        if not records:
            return {
                "status": "insufficient_data",
                "request_count": 0,
                "average_response_time_ms": None,
                "median_response_time_ms": None,
                "p95_response_time_ms": None,
                "slowest_requests": []
            }

        durations = sorted([r["duration_ms"] for r in records])
        count = len(durations)
        avg_ms = round(mean(durations), 2)
        med_ms = round(median(durations), 2)
        p95_idx = int(round(0.95 * (count - 1)))
        p95_ms = round(durations[p95_idx], 2)

        # Slowest requests aggregated by endpoint
        endpoint_stats = defaultdict(list)
        for r in records:
            endpoint_stats[f"{r['method']} {r['path']}"].append(r["duration_ms"])

        slowest = []
        for endpoint, d_list in endpoint_stats.items():
            sorted_d = sorted(d_list)
            p95_val = sorted_d[int(round(0.95 * (len(sorted_d) - 1)))]
            slowest.append({
                "endpoint": endpoint,
                "calls": len(d_list),
                "avg_ms": round(mean(d_list), 2),
                "max_ms": round(max(d_list), 2),
                "p95_ms": round(p95_val, 2)
            })
        slowest.sort(key=lambda x: x["avg_ms"], reverse=True)

        return {
            "status": "available",
            "request_count": count,
            "average_response_time_ms": avg_ms,
            "median_response_time_ms": med_ms,
            "p95_response_time_ms": p95_ms,
            "slowest_requests": slowest[:10]
        }

    def get_dashboard_loading_speed(self) -> Dict[str, Any]:
        """Measures dashboard endpoint loading performance from recorded requests."""
        with self._lock:
            records = list(self._request_records)

        dashboard_paths = [
            "/api/admin/dashboard",
            "/api/admin/analytics",
            "/api/dashboard/stats",
            "/api/analytics/summary",
            "/api/admin/performance-metrics"
        ]

        dash_records = [r for r in records if any(p in r["path"] for p in dashboard_paths)]

        if not dash_records:
            return {
                "status": "insufficient_data",
                "initial_dashboard_request_ms": None,
                "total_dashboard_data_loading_ms": None,
                "dashboard_requests_measured": 0
            }

        durations = [r["duration_ms"] for r in dash_records]
        avg_initial = round(mean(durations), 2)
        total_data_ms = round(sum(sorted(durations, reverse=True)[:3]), 2)

        return {
            "status": "available",
            "initial_dashboard_request_ms": avg_initial,
            "total_dashboard_data_loading_ms": total_data_ms,
            "dashboard_requests_measured": len(dash_records)
        }

    def get_challenge_generation_metrics(self) -> Dict[str, Any]:
        """Calculates challenge generation latencies and provider fallback stats."""
        with self._lock:
            records = list(self._challenge_records)

        if not records:
            return {
                "status": "insufficient_data",
                "average_generation_latency_ms": None,
                "median_latency_ms": None,
                "p95_latency_ms": None,
                "successful_generations": 0,
                "failed_generations": 0,
                "fallback_generations": 0,
                "provider_breakdown": {}
            }

        durations = sorted([r["duration_ms"] for r in records])
        count = len(durations)
        avg_ms = round(mean(durations), 2)
        med_ms = round(median(durations), 2)
        p95_idx = int(round(0.95 * (count - 1)))
        p95_ms = round(durations[p95_idx], 2)

        success_count = sum(1 for r in records if r["success"])
        failed_count = count - success_count
        fallback_count = sum(1 for r in records if r["is_fallback"])

        provider_dist = defaultdict(int)
        for r in records:
            provider_dist[r["provider"]] += 1

        return {
            "status": "available",
            "average_generation_latency_ms": avg_ms,
            "median_latency_ms": med_ms,
            "p95_latency_ms": p95_ms,
            "successful_generations": success_count,
            "failed_generations": failed_count,
            "fallback_generations": fallback_count,
            "provider_breakdown": dict(provider_dist)
        }

    def get_concurrent_user_capacity(self) -> Dict[str, Any]:
        """Returns latest benchmarked capacity results or status if not tested."""
        with self._lock:
            if self._last_load_test:
                return {
                    "status": "available",
                    **self._last_load_test
                }
            return {
                "status": "insufficient_data",
                "message": "Run load test script to benchmark real concurrent user capacity",
                "concurrent_users_tested": None,
                "requests_per_second": None,
                "average_latency_ms": None,
                "p95_latency_ms": None,
                "error_rate_pct": None,
                "successful_requests": None,
                "tested_at": None
            }


# Global singleton collector
metrics_collector = PerformanceMetricsCollector()
