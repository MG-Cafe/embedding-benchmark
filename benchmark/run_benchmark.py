#!/usr/bin/env python3
"""
=============================================================================
Benchmark Orchestrator — Run All Test Scenarios
=============================================================================

This is the main entry point for running the the target application embedding benchmark.
It orchestrates the full benchmark workflow:

1. Loads configuration and validates the endpoint is reachable
2. Authenticates with Google Cloud
3. Runs each benchmark scenario (ingest-default-chunk, ingest-max-context)
4. For each scenario, ramps through all concurrency levels
5. Saves raw results to JSON and triggers report generation

The benchmark tests the target application's async batch ingest workload against a Vertex AI
endpoint running Jina Embeddings V5 via vLLM.

Usage:
    python benchmark/run_benchmark.py \\
        --config deploy/config.yaml \\
        --endpoint-id <ENDPOINT_ID> \\
        --gpu-label "1x-rtx-pro-6000"

    # Optional: run only specific scenarios
    python benchmark/run_benchmark.py \\
        --config deploy/config.yaml \\
        --endpoint-id <ENDPOINT_ID> \\
        --gpu-label "2x-rtx-pro-6000" \\
        --scenario ingest-default-chunk

Output:
    results/
    ├── benchmark_<gpu-label>_<timestamp>.json   # Raw results (all metrics)
    └── benchmark_<gpu-label>_<timestamp>.csv    # Summary table for analysis

The JSON file contains the full ConcurrencyResult data for each test,
including individual request latencies. The CSV contains the aggregated
metrics used for the throughput-vs-cost matrix.
=============================================================================
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

import yaml

# Add the project root to Python path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.workload_profiles import get_benchmark_scenarios, print_scenarios, BenchmarkScenario
from benchmark.load_generator import (
    get_access_token,
    build_endpoint_url,
    run_load_test,
    print_result_summary,
    ConcurrencyResult,
)


def load_config(config_path: str) -> dict:
    """Load and return the YAML configuration file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def validate_endpoint(endpoint_url: str, access_token: str) -> bool:
    """
    Send a single small test request to verify the endpoint is reachable.

    This catches common issues before starting the full benchmark:
    - Wrong endpoint ID
    - Endpoint not deployed yet
    - Authentication problems
    - Container not ready (still loading model)

    Returns True if the endpoint responds successfully, False otherwise.
    """
    import aiohttp
    import asyncio

    async def _test():
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        # Send a minimal embedding request
        payload = {
            "input": ["Hello, this is a test request."],
            "model": "jinaai/jina-embeddings-v5-text-small",
        }
        timeout = aiohttp.ClientTimeout(total=60)  # Allow generous timeout for first request
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(endpoint_url, json=payload, headers=headers) as response:
                body = await response.read()
                return response.status, body

    try:
        status, body = asyncio.run(_test())
        if status == 200:
            return True
        else:
            print(f"   ❌ Endpoint returned status {status}")
            try:
                error = json.loads(body)
                print(f"   Error: {json.dumps(error, indent=2)[:500]}")
            except json.JSONDecodeError:
                print(f"   Response: {body[:500]}")
            return False
    except Exception as e:
        print(f"   ❌ Failed to reach endpoint: {e}")
        return False


def save_results(
    all_results: list[ConcurrencyResult],
    gpu_label: str,
    results_dir: str,
) -> tuple[str, str]:
    """
    Save benchmark results to JSON and CSV files.

    JSON: Contains full results including individual request data.
          Used for detailed analysis and debugging.

    CSV: Contains aggregated metrics per (scenario, concurrency) combination.
         Used for the throughput-vs-cost matrix and report generation.

    Args:
        all_results: List of ConcurrencyResult from all tests
        gpu_label: Human-readable GPU configuration label (e.g., "1x-rtx-pro-6000")
        results_dir: Directory to save results to

    Returns:
        Tuple of (json_path, csv_path)
    """
    os.makedirs(results_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # --- Save JSON (full results) ---
    json_path = os.path.join(results_dir, f"benchmark_{gpu_label}_{timestamp}.json")

    json_data = {
        "metadata": {
            "gpu_label": gpu_label,
            "timestamp": timestamp,
            "run_date": datetime.now().isoformat(),
        },
        "results": [],
    }

    for result in all_results:
        json_data["results"].append({
            "scenario_name": result.scenario_name,
            "concurrency": result.concurrency,
            "total_requests": result.total_requests,
            "successful_requests": result.successful_requests,
            "failed_requests": result.failed_requests,
            "total_tokens": result.total_tokens,
            "duration_seconds": result.duration_seconds,
            "tokens_per_second": result.tokens_per_second,
            "tokens_per_minute": result.tokens_per_minute,
            "requests_per_second": result.requests_per_second,
            "requests_per_minute": result.requests_per_minute,
            "latency_p50_ms": result.latency_p50_ms,
            "latency_p95_ms": result.latency_p95_ms,
            "latency_p99_ms": result.latency_p99_ms,
            "latency_mean_ms": result.latency_mean_ms,
            "latency_min_ms": result.latency_min_ms,
            "latency_max_ms": result.latency_max_ms,
            "error_rate": result.error_rate,
            "all_under_20s": result.all_under_20s,
        })

    with open(json_path, "w") as f:
        json.dump(json_data, f, indent=2)

    # --- Save CSV (summary table) ---
    csv_path = os.path.join(results_dir, f"benchmark_{gpu_label}_{timestamp}.csv")

    csv_headers = [
        "scenario", "concurrency", "tokens_per_sec", "tokens_per_min",
        "requests_per_min", "latency_p50_ms", "latency_p95_ms", "latency_p99_ms",
        "latency_max_ms", "error_rate", "all_under_20s", "total_requests",
        "successful_requests", "gpu_label",
    ]

    with open(csv_path, "w") as f:
        f.write(",".join(csv_headers) + "\n")
        for result in all_results:
            row = [
                result.scenario_name,
                str(result.concurrency),
                f"{result.tokens_per_second:.1f}",
                f"{result.tokens_per_minute:.1f}",
                f"{result.requests_per_minute:.1f}",
                f"{result.latency_p50_ms:.1f}",
                f"{result.latency_p95_ms:.1f}",
                f"{result.latency_p99_ms:.1f}",
                f"{result.latency_max_ms:.1f}",
                f"{result.error_rate:.4f}",
                str(result.all_under_20s),
                str(result.total_requests),
                str(result.successful_requests),
                gpu_label,
            ]
            f.write(",".join(row) + "\n")

    return json_path, csv_path


def run_scenario(
    scenario: BenchmarkScenario,
    endpoint_url: str,
    access_token: str,
) -> list[ConcurrencyResult]:
    """
    Run all concurrency levels for a single scenario.

    For each concurrency level:
    1. Print what we're about to test
    2. Run the load test (warmup + measurement)
    3. Print results summary
    4. Collect results for the final report

    Args:
        scenario: The benchmark scenario to run
        endpoint_url: Vertex AI endpoint URL
        access_token: Google Cloud auth token

    Returns:
        List of ConcurrencyResult, one per concurrency level tested
    """
    results = []

    print(f"\n{'=' * 60}")
    print(f"SCENARIO: {scenario.name}")
    print(f"{'=' * 60}")
    print(f"  {scenario.description}")
    print(f"  Batch size: {scenario.batch_size} texts/request")
    print(f"  Tokens/text: {scenario.target_tokens_per_text:,}")
    print(f"  Tokens/request: {scenario.tokens_per_request:,}")
    print(f"  Concurrency levels: {scenario.concurrency_levels}")

    for concurrency in scenario.concurrency_levels:
        print(f"\n  🔄 Starting concurrency={concurrency} "
              f"(warmup: {scenario.warmup_seconds}s, measure: {scenario.duration_seconds}s)...")

        try:
            result = run_load_test(
                scenario=scenario,
                concurrency=concurrency,
                endpoint_url=endpoint_url,
                access_token=access_token,
            )
            print_result_summary(result)
            results.append(result)

        except Exception as e:
            print(f"\n  ❌ Error at concurrency={concurrency}: {e}")
            # Create a failed result so we capture the error in the report
            failed_result = ConcurrencyResult(
                scenario_name=scenario.name,
                concurrency=concurrency,
            )
            results.append(failed_result)

        # Brief pause between concurrency levels to let the GPU cool down
        # and vLLM's scheduler reset. 5 seconds is enough.
        if concurrency != scenario.concurrency_levels[-1]:
            print(f"\n  ⏸️  Pausing 5s before next concurrency level...")
            time.sleep(5)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Run the target application embedding benchmark against Vertex AI endpoint",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all scenarios with 1-GPU endpoint
  python benchmark/run_benchmark.py \\
      --config deploy/config.yaml \\
      --endpoint-id 1234567890 \\
      --gpu-label "1x-rtx-pro-6000"

  # Run only the default chunk scenario
  python benchmark/run_benchmark.py \\
      --config deploy/config.yaml \\
      --endpoint-id 1234567890 \\
      --gpu-label "1x-rtx-pro-6000" \\
      --scenario ingest-default-chunk

  # Run with 2-GPU endpoint
  python benchmark/run_benchmark.py \\
      --config deploy/config.yaml \\
      --endpoint-id 9876543210 \\
      --gpu-label "2x-rtx-pro-6000"
        """,
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to config.yaml file",
    )
    parser.add_argument(
        "--endpoint-id",
        type=str,
        required=True,
        help="Vertex AI endpoint ID (numeric string, printed during deployment)",
    )
    parser.add_argument(
        "--gpu-label",
        type=str,
        required=True,
        help="Human-readable GPU config label (e.g., '1x-rtx-pro-6000', '2x-rtx-pro-6000')",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        choices=["ingest-default-chunk", "ingest-max-context"],
        help="Run only a specific scenario (default: run all)",
    )

    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)
    results_dir = config["benchmark"]["results_dir"]

    # Print banner
    print("\n" + "=" * 60)
    print("  EMBEDDING INFERENCE BENCHMARK")
    print("  Jina Embeddings V5 on Vertex AI")
    print("=" * 60)
    print(f"  GPU Config:  {args.gpu_label}")
    print(f"  Endpoint ID: {args.endpoint_id}")
    print(f"  Project:     {config['gcp']['project_id']}")
    print(f"  Region:      {config['gcp']['region']}")

    # Step 1: Authenticate with Google Cloud
    print(f"\n🔑 Getting access token...")
    try:
        access_token = get_access_token()
        print(f"   ✅ Token obtained")
    except Exception as e:
        print(f"   ❌ Authentication failed: {e}")
        print(f"   Run: gcloud auth login && gcloud auth application-default login")
        sys.exit(1)

    # Step 2: Build endpoint URL and validate
    endpoint_url = build_endpoint_url(config, args.endpoint_id)
    print(f"\n🌐 Endpoint URL: {endpoint_url}")
    print(f"   🔄 Sending test request to validate endpoint...")

    if not validate_endpoint(endpoint_url, access_token):
        print(f"\n   ❌ Endpoint validation failed. Please check:")
        print(f"      1. Is the endpoint ID correct?")
        print(f"      2. Is the model deployed and ready?")
        print(f"      3. Do you have the right IAM permissions?")
        sys.exit(1)

    print(f"   ✅ Endpoint is ready!")

    # Step 3: Load and filter scenarios
    all_scenarios = get_benchmark_scenarios(config)

    if args.scenario:
        scenarios = [s for s in all_scenarios if s.name == args.scenario]
        if not scenarios:
            print(f"\n❌ Scenario '{args.scenario}' not found")
            sys.exit(1)
    else:
        scenarios = all_scenarios

    # Print what we're about to run
    print_scenarios(scenarios)

    # Step 4: Run all scenarios
    all_results: list[ConcurrencyResult] = []
    benchmark_start = time.time()

    for scenario in scenarios:
        scenario_results = run_scenario(
            scenario=scenario,
            endpoint_url=endpoint_url,
            access_token=access_token,
        )
        all_results.extend(scenario_results)

    benchmark_duration = time.time() - benchmark_start

    # Step 5: Save results
    print(f"\n{'=' * 60}")
    print(f"SAVING RESULTS")
    print(f"{'=' * 60}")

    json_path, csv_path = save_results(all_results, args.gpu_label, results_dir)

    print(f"  📄 JSON (full):    {json_path}")
    print(f"  📊 CSV (summary):  {csv_path}")

    # Step 6: Print final summary
    print(f"\n{'=' * 60}")
    print(f"BENCHMARK COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Total time:     {benchmark_duration / 60:.1f} minutes")
    print(f"  GPU config:     {args.gpu_label}")
    print(f"  Scenarios run:  {len(scenarios)}")
    print(f"  Total tests:    {len(all_results)}")

    # Quick summary of best results
    print(f"\n  {'─' * 50}")
    print(f"  BEST RESULTS PER SCENARIO")
    print(f"  {'─' * 50}")

    for scenario in scenarios:
        scenario_results = [r for r in all_results if r.scenario_name == scenario.name]
        if scenario_results:
            best = max(scenario_results, key=lambda r: r.tokens_per_minute)
            print(f"\n  📊 {scenario.name}")
            print(f"     Best throughput: {best.tokens_per_minute:,.0f} tokens/min "
                  f"(at concurrency={best.concurrency})")
            print(f"     Best RPM:        {best.requests_per_minute:,.0f}")
            print(f"     Latency (p50):   {best.latency_p50_ms:,.1f}ms")
            print(f"     Under 20s:       {'✅' if best.all_under_20s else '❌'}")

            if best.tokens_per_minute >= 6_000_000:
                print(f"     6M tok/min:      ✅ PASSED ({best.tokens_per_minute / 6_000_000:.1f}x)")
            else:
                print(f"     6M tok/min:      ❌ {best.tokens_per_minute / 6_000_000:.1%} of target")

    print(f"\n  Next steps:")
    print(f"  1. Generate report:  python analysis/generate_report.py --results-dir {results_dir}")
    print(f"  2. Clean up:         python deploy/cleanup_vertex.py --config {args.config}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
