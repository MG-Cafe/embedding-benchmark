#!/usr/bin/env python3
"""
=============================================================================
Async HTTP Load Generator for Vertex AI Embedding Endpoint
=============================================================================

This module implements a high-concurrency async HTTP load generator that sends
embedding requests to a Vertex AI endpoint and collects detailed metrics.

How It Works:
    1. We create N async workers (where N = concurrency level)
    2. Each worker runs in a loop: send request → record metrics → repeat
    3. Workers run for a specified duration (warmup + measurement period)
    4. During warmup, requests are sent but metrics are not recorded
    5. During measurement, we capture per-request latency and compute throughput

Why Async (aiohttp) Instead of Threads:
    - We need 128+ concurrent connections — threads are expensive at this scale
    - aiohttp uses a single event loop with non-blocking I/O
    - Each "worker" is a lightweight coroutine, not a system thread
    - This matches how the target inference service would actually call the endpoint
      (their Go/Java services use async HTTP clients internally)

Authentication:
    Vertex AI endpoints require a Bearer token from `gcloud auth print-access-token`.
    We fetch this token once before the benchmark starts and reuse it for all requests.
    For long benchmarks (>1 hour), the token would need to be refreshed, but our
    tests are 60-70 seconds each, so a single token is fine.

Metrics Collected Per Request:
    - latency_ms: End-to-end HTTP request time (including network + server processing)
    - status_code: HTTP response status (200 = success, anything else = error)
    - tokens_in_request: Number of input tokens (batch_size × tokens_per_text)
    - timestamp: When the request completed (for calculating throughput over time)
    - error: Error message if the request failed

Output:
    Returns a list of RequestResult objects that the run_benchmark.py orchestrator
    uses to compute aggregate metrics (throughput, percentile latencies, error rates).
=============================================================================
"""

import asyncio
import time
import json
import subprocess
from dataclasses import dataclass, field
from typing import Optional

import aiohttp
import numpy as np

from benchmark.workload_profiles import BenchmarkScenario


# ---------------------------------------------------------------------------
# Data Classes for Benchmark Results
# ---------------------------------------------------------------------------

@dataclass
class RequestResult:
    """
    Metrics from a single HTTP request to the embedding endpoint.

    Each request sends a batch of texts (e.g., 16 texts × 512 tokens each)
    and receives back embedding vectors. We measure the time for the full
    round-trip.
    """
    # Time from request sent to response received (milliseconds)
    latency_ms: float

    # HTTP status code (200 = success)
    status_code: int

    # Total input tokens in this request (batch_size × tokens_per_text)
    tokens_in_request: int

    # Unix timestamp when the response was received
    timestamp: float

    # Error message if the request failed (None if successful)
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        """Request was successful if status code is 200 and no error."""
        return self.status_code == 200 and self.error is None


@dataclass
class ConcurrencyResult:
    """
    Aggregated results for a single concurrency level within a scenario.

    For example: "Scenario: ingest-default-chunk, Concurrency: 16"
    This captures all the metrics needed for the throughput-vs-cost matrix.
    """
    # Which scenario and concurrency level this result is for
    scenario_name: str
    concurrency: int

    # All individual request results (for computing percentiles)
    requests: list[RequestResult] = field(default_factory=list)

    # Computed aggregate metrics (populated after benchmark completes)
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0

    # Throughput metrics
    total_tokens: int = 0
    duration_seconds: float = 0.0
    tokens_per_second: float = 0.0
    tokens_per_minute: float = 0.0
    requests_per_second: float = 0.0
    requests_per_minute: float = 0.0

    # Latency percentiles (milliseconds) — computed from successful requests
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    latency_mean_ms: float = 0.0
    latency_min_ms: float = 0.0
    latency_max_ms: float = 0.0

    # Error rate
    error_rate: float = 0.0

    # Whether all requests completed under 20s (the target timeout)
    all_under_20s: bool = True

    def compute_aggregates(self) -> None:
        """
        Compute aggregate metrics from individual request results.

        Called after all requests for this concurrency level have completed.
        This is where we calculate the numbers that go into the
        throughput-vs-cost matrix.
        """
        self.total_requests = len(self.requests)
        successful = [r for r in self.requests if r.is_success]
        self.successful_requests = len(successful)
        self.failed_requests = self.total_requests - self.successful_requests

        if not successful:
            return

        # Throughput: computed over the actual measurement window
        self.total_tokens = sum(r.tokens_in_request for r in successful)
        timestamps = [r.timestamp for r in successful]
        self.duration_seconds = max(timestamps) - min(timestamps) if len(timestamps) > 1 else 1.0

        self.tokens_per_second = self.total_tokens / self.duration_seconds
        self.tokens_per_minute = self.tokens_per_second * 60
        self.requests_per_second = self.successful_requests / self.duration_seconds
        self.requests_per_minute = self.requests_per_second * 60

        # Latency percentiles from successful requests
        latencies = np.array([r.latency_ms for r in successful])
        self.latency_p50_ms = float(np.percentile(latencies, 50))
        self.latency_p95_ms = float(np.percentile(latencies, 95))
        self.latency_p99_ms = float(np.percentile(latencies, 99))
        self.latency_mean_ms = float(np.mean(latencies))
        self.latency_min_ms = float(np.min(latencies))
        self.latency_max_ms = float(np.max(latencies))

        # Error rate
        self.error_rate = self.failed_requests / self.total_requests if self.total_requests > 0 else 0.0

        # Check the target 20s timeout requirement
        self.all_under_20s = all(r.latency_ms < 20000 for r in successful)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def get_access_token() -> str:
    """
    Get a Google Cloud access token for authenticating with Vertex AI.

    Uses Application Default Credentials (ADC) via
    `gcloud auth application-default print-access-token`. This is required
    because Vertex AI rawPredict rejects user-type tokens from
    `gcloud auth print-access-token` with ACCESS_TOKEN_TYPE_UNSUPPORTED.

    ADC tokens work correctly with Vertex AI prediction endpoints.
    Requires: `gcloud auth application-default login` to be run first.

    The token is valid for ~60 minutes, which is more than enough for our
    benchmark runs (each concurrency level test is ~70 seconds).
    """
    # Try ADC token first (works with Vertex AI rawPredict)
    result = subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()

    # Fallback to regular gcloud token
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        check=True,
    )
    token = result.stdout.strip()
    if not token:
        raise RuntimeError(
            "Failed to get access token. Make sure you're authenticated with gcloud:\n"
            "  gcloud auth application-default login"
        )
    return token


def build_endpoint_url(config: dict, endpoint_id: str) -> str:
    """
    Construct the Vertex AI endpoint URL for sending prediction requests.

    Vertex AI endpoints follow this URL pattern:
    https://<REGION>-aiplatform.googleapis.com/v1/projects/<PROJECT>/locations/<REGION>/endpoints/<ENDPOINT_ID>:rawPredict

    We use :rawPredict instead of :predict because:
    - :predict wraps the request/response in Vertex AI's format
    - :rawPredict passes the request body directly to the container
    - Since our container runs vLLM's OpenAI-compatible API, we want the
      raw request to reach /v1/embeddings as-is

    Args:
        config: The loaded config.yaml dictionary
        endpoint_id: The Vertex AI endpoint ID (numeric string)

    Returns:
        Full URL for sending raw prediction requests
    """
    project = config["gcp"]["project_id"]
    region = config["gcp"]["region"]
    return (
        f"https://{region}-aiplatform.googleapis.com/v1/"
        f"projects/{project}/locations/{region}/"
        f"endpoints/{endpoint_id}:rawPredict"
    )


# ---------------------------------------------------------------------------
# Async Load Generator
# ---------------------------------------------------------------------------

async def _worker(
    worker_id: int,
    session: aiohttp.ClientSession,
    url: str,
    headers: dict,
    scenario: BenchmarkScenario,
    results: list[RequestResult],
    warmup_end: float,
    test_end: float,
) -> None:
    """
    A single async worker that sends requests in a loop.

    Each worker:
    1. Generates a unique request payload (different text for each request)
    2. Sends it to the endpoint and times the response
    3. Records the result (only after warmup period)
    4. Immediately sends the next request (no artificial delay)

    The worker runs until test_end time is reached.

    Args:
        worker_id: Unique ID for this worker (used to vary request content)
        session: Shared aiohttp session (connection pooling)
        url: Vertex AI endpoint URL
        headers: HTTP headers including auth token
        scenario: The benchmark scenario (defines payload shape)
        results: Shared list to append results to (only measurement-period results)
        warmup_end: Unix timestamp when warmup ends and measurement begins
        test_end: Unix timestamp when this test should stop
    """
    request_counter = worker_id * 100000  # Offset to ensure unique batch_index per worker

    while time.time() < test_end:
        # Generate a unique payload for each request
        # Different batch_index → different synthetic text → no caching effects
        payload = scenario.get_request_payload(batch_index=request_counter)
        request_counter += 1

        # Time the request
        start_time = time.time()
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                # Read the full response body (important for accurate latency measurement)
                body = await response.read()
                end_time = time.time()

                latency_ms = (end_time - start_time) * 1000
                status_code = response.status

                # Parse error message if request failed
                error = None
                if status_code != 200:
                    try:
                        error_body = json.loads(body)
                        error = error_body.get("error", {}).get("message", body.decode()[:200])
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        error = f"HTTP {status_code}: {body[:200]}"

                result = RequestResult(
                    latency_ms=latency_ms,
                    status_code=status_code,
                    tokens_in_request=scenario.tokens_per_request,
                    timestamp=end_time,
                    error=error,
                )

        except asyncio.TimeoutError:
            end_time = time.time()
            result = RequestResult(
                latency_ms=(end_time - start_time) * 1000,
                status_code=0,
                tokens_in_request=scenario.tokens_per_request,
                timestamp=end_time,
                error="Request timed out",
            )

        except Exception as e:
            end_time = time.time()
            result = RequestResult(
                latency_ms=(end_time - start_time) * 1000,
                status_code=0,
                tokens_in_request=scenario.tokens_per_request,
                timestamp=end_time,
                error=str(e),
            )

        # Only record results after warmup period
        if end_time >= warmup_end:
            results.append(result)


async def run_concurrency_test(
    scenario: BenchmarkScenario,
    concurrency: int,
    endpoint_url: str,
    access_token: str,
) -> ConcurrencyResult:
    """
    Run a single concurrency level test for a given scenario.

    This starts N concurrent workers (where N = concurrency), lets them
    warm up for warmup_seconds, then measures for duration_seconds.

    Example: scenario=ingest-default-chunk, concurrency=16
    - Starts 16 async workers, each sending batch-of-16 embedding requests
    - Warmup: 10 seconds (requests sent but not measured)
    - Measurement: 60 seconds (all request metrics recorded)
    - Returns aggregated results with throughput and latency percentiles

    Args:
        scenario: The benchmark scenario definition
        concurrency: Number of concurrent workers to run
        endpoint_url: Vertex AI endpoint URL
        access_token: Google Cloud auth token

    Returns:
        ConcurrencyResult with all metrics computed
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    results: list[RequestResult] = []

    # Calculate time boundaries
    now = time.time()
    warmup_end = now + scenario.warmup_seconds
    test_end = warmup_end + scenario.duration_seconds

    # Create aiohttp session with connection pooling
    # The connector limits total connections and per-host connections
    # to avoid overwhelming the endpoint with TCP connections
    connector = aiohttp.TCPConnector(
        limit=concurrency + 10,         # Total connection pool size
        limit_per_host=concurrency + 10, # Per-host limit (we only have one host)
    )

    # Timeout: 30s per request (above the target 20s timeout so we can measure
    # if requests actually exceed 20s rather than cutting them off)
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # Start all workers concurrently
        workers = [
            _worker(
                worker_id=i,
                session=session,
                url=endpoint_url,
                headers=headers,
                scenario=scenario,
                results=results,
                warmup_end=warmup_end,
                test_end=test_end,
            )
            for i in range(concurrency)
        ]

        # Run all workers until they complete (when test_end is reached)
        await asyncio.gather(*workers)

    # Build and compute the aggregated result
    result = ConcurrencyResult(
        scenario_name=scenario.name,
        concurrency=concurrency,
        requests=results,
    )
    result.compute_aggregates()

    return result


def run_load_test(
    scenario: BenchmarkScenario,
    concurrency: int,
    endpoint_url: str,
    access_token: str,
) -> ConcurrencyResult:
    """
    Synchronous wrapper for run_concurrency_test.

    This is the main entry point called by run_benchmark.py.
    It handles the async event loop setup.

    Args:
        scenario: The benchmark scenario definition
        concurrency: Number of concurrent workers
        endpoint_url: Vertex AI endpoint URL
        access_token: Google Cloud auth token

    Returns:
        ConcurrencyResult with computed aggregate metrics
    """
    return asyncio.run(
        run_concurrency_test(
            scenario=scenario,
            concurrency=concurrency,
            endpoint_url=endpoint_url,
            access_token=access_token,
        )
    )


# ---------------------------------------------------------------------------
# Utility: Print result summary
# ---------------------------------------------------------------------------

def print_result_summary(result: ConcurrencyResult) -> None:
    """Print a formatted summary of a concurrency test result."""
    print(f"\n  {'─' * 50}")
    print(f"  Concurrency: {result.concurrency}")
    print(f"  {'─' * 50}")
    print(f"  Requests:    {result.successful_requests}/{result.total_requests} "
          f"successful ({result.error_rate:.1%} error rate)")
    print(f"  Throughput:  {result.tokens_per_second:,.0f} tokens/sec "
          f"({result.tokens_per_minute:,.0f} tokens/min)")
    print(f"  RPM:         {result.requests_per_minute:,.0f} requests/min")
    print(f"  Latency p50: {result.latency_p50_ms:,.1f}ms")
    print(f"  Latency p95: {result.latency_p95_ms:,.1f}ms")
    print(f"  Latency p99: {result.latency_p99_ms:,.1f}ms")
    print(f"  Max latency: {result.latency_max_ms:,.1f}ms")
    print(f"  Under 20s:   {'✅ Yes' if result.all_under_20s else '❌ No'}")

    # Check against the target 6M tokens/min target
    if result.tokens_per_minute >= 6_000_000:
        print(f"  6M tok/min:  ✅ PASSED ({result.tokens_per_minute / 6_000_000:.1f}x target)")
    else:
        print(f"  6M tok/min:  ❌ BELOW TARGET ({result.tokens_per_minute / 6_000_000:.1%} of target)")
