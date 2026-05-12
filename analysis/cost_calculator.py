#!/usr/bin/env python3
"""
=============================================================================
Cost Calculator — $/Million Tokens Computation
=============================================================================

This module takes benchmark throughput results and GPU pricing data to compute
the key metric users need: **how much does it cost to embed 1 million tokens?**

This is THE deliverable from the POC. The key question is:
"I'm interested in the function of how much money do we pay for what throughput
so that we can also plan for the users getting the throughput that we promised them."

How It Works:
    1. Load benchmark results (tokens/sec at each concurrency level)
    2. Load GPU pricing data ($/hour for G4 with 1 or 2 GPUs)
    3. For each (scenario, concurrency) combination, calculate:
       - tokens_per_hour = tokens_per_sec × 3600
       - cost_per_million_tokens = (hourly_cost / tokens_per_hour) × 1,000,000
    4. Output a cost matrix showing price/performance at each configuration

The matrix helps the user answer questions like:
    - "At our 6M tokens/min rate limit, what does it cost us per user?"
    - "If a customer wants 2× the rate limit, how much more does it cost?"
    - "How many G4 instances do we need for 100 concurrent users?"
    - "Does committing to 1-year CUD make sense for our usage?"

Example Output:
    GPU Config: 1× RTX Pro 6000 (on-demand: $4.50/hr)

    | Scenario             | Concurrency | Tokens/min  | $/M tokens | $/hr effective |
    |----------------------|-------------|-------------|------------|----------------|
    | ingest-default-chunk | 1           | 500,000     | $0.150     | $4.50          |
    | ingest-default-chunk | 16          | 4,000,000   | $0.019     | $4.50          |
    | ingest-default-chunk | 64          | 6,500,000   | $0.012     | $4.50          |
    | ingest-max-context   | 1           | 200,000     | $0.375     | $4.50          |
    | ...                  | ...         | ...         | ...        | ...            |
=============================================================================
"""

import json
import os
from dataclasses import dataclass

import yaml


@dataclass
class CostResult:
    """
    Cost analysis for a single (scenario, concurrency, gpu_config, pricing_tier) combination.

    This is one row in the throughput-vs-cost matrix.
    """
    # Test identification
    scenario_name: str
    concurrency: int
    gpu_label: str

    # Throughput from benchmark
    tokens_per_second: float
    tokens_per_minute: float
    tokens_per_hour: float

    # GPU pricing
    pricing_tier: str          # "on_demand", "cud_1yr", or "cud_3yr"
    hourly_cost_usd: float     # $/hour for this GPU config

    # THE KEY METRIC: cost per million tokens
    cost_per_million_tokens: float

    # Derived: how many of this GPU config needed to serve N tokens/min
    # Useful for capacity planning
    gpus_for_6m_tokens_min: float  # GPUs needed for the user's 6M tokens/min rate limit

    # Latency info (passed through from benchmark)
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float


def load_pricing(pricing_path: str) -> dict:
    """Load GPU pricing data from YAML file."""
    with open(pricing_path, "r") as f:
        return yaml.safe_load(f)


def load_benchmark_results(results_path: str) -> dict:
    """Load benchmark results from JSON file."""
    with open(results_path, "r") as f:
        return json.load(f)


def get_gpu_pricing(pricing_data: dict, gpu_label: str) -> dict:
    """
    Get the pricing configuration for a GPU label.

    Maps GPU labels like "1x-rtx-pro-6000" to the corresponding
    pricing data in pricing_data.yaml.

    Args:
        pricing_data: Loaded pricing YAML
        gpu_label: Label from benchmark run (e.g., "1x-rtx-pro-6000")

    Returns:
        Dict with pricing tiers:
        {
            "on_demand": 4.50,
            "cud_1yr": 2.835,
            "cud_3yr": 2.025,
            "gpu_name": "NVIDIA RTX Pro 6000",
            "accelerator_count": 1,
        }
    """
    # Parse gpu_label to determine GPU count (single vs dual)
    label_lower = gpu_label.lower()

    # This benchmark targets G4 (RTX Pro 6000) only
    family = "g4"

    if "2x" in label_lower or "2gpu" in label_lower or "dual" in label_lower or "2node" in label_lower:
        config_key = "dual_gpu"
    else:
        config_key = "single_gpu"

    family_data = pricing_data[family]
    config_data = family_data[config_key]

    return {
        "on_demand": config_data["on_demand_hourly_usd"],
        "cud_1yr": config_data["cud_1yr_hourly_usd"],
        "cud_3yr": config_data["cud_3yr_hourly_usd"],
        "gpu_name": family_data["gpu_name"],
        "gpu_memory_gb": family_data["gpu_memory_gb"],
        "accelerator_count": config_data["accelerator_count"],
        "machine_type": config_data["machine_type"],
    }


def calculate_costs(
    benchmark_results: dict,
    pricing_data: dict,
) -> list[CostResult]:
    """
    Calculate cost per million tokens for all benchmark results.

    For each (scenario, concurrency) combination in the benchmark results,
    we compute the cost at three pricing tiers:
    - On-demand: Pay-as-you-go, highest price, most flexible
    - 1-year CUD: ~37% discount, requires 1-year commitment
    - 3-year CUD: ~55% discount, requires 3-year commitment

    Args:
        benchmark_results: Loaded benchmark JSON
        pricing_data: Loaded pricing YAML

    Returns:
        List of CostResult objects, one per (scenario, concurrency, pricing_tier)
    """
    gpu_label = benchmark_results["metadata"]["gpu_label"]
    gpu_pricing = get_gpu_pricing(pricing_data, gpu_label)

    cost_results = []

    for result in benchmark_results["results"]:
        tokens_per_second = result["tokens_per_second"]

        # Skip failed tests (no throughput data)
        if tokens_per_second <= 0:
            continue

        tokens_per_minute = result["tokens_per_minute"]
        tokens_per_hour = tokens_per_second * 3600

        # Calculate cost at each pricing tier
        for tier_name, hourly_cost in [
            ("on_demand", gpu_pricing["on_demand"]),
            ("cud_1yr", gpu_pricing["cud_1yr"]),
            ("cud_3yr", gpu_pricing["cud_3yr"]),
        ]:
            # Core formula: $/M tokens = ($/hour) / (tokens/hour) × 1,000,000
            if tokens_per_hour > 0:
                cost_per_million = (hourly_cost / tokens_per_hour) * 1_000_000
            else:
                cost_per_million = float("inf")

            # How many instances of this GPU config needed for 6M tokens/min?
            # This helps the user plan capacity
            if tokens_per_minute > 0:
                gpus_for_6m = 6_000_000 / tokens_per_minute
            else:
                gpus_for_6m = float("inf")

            cost_results.append(CostResult(
                scenario_name=result["scenario_name"],
                concurrency=result["concurrency"],
                gpu_label=gpu_label,
                tokens_per_second=tokens_per_second,
                tokens_per_minute=tokens_per_minute,
                tokens_per_hour=tokens_per_hour,
                pricing_tier=tier_name,
                hourly_cost_usd=hourly_cost,
                cost_per_million_tokens=cost_per_million,
                gpus_for_6m_tokens_min=gpus_for_6m,
                latency_p50_ms=result["latency_p50_ms"],
                latency_p95_ms=result["latency_p95_ms"],
                latency_p99_ms=result["latency_p99_ms"],
            ))

    return cost_results


def format_cost_table(cost_results: list[CostResult], pricing_tier: str = "on_demand") -> str:
    """
    Format cost results as a readable ASCII table.

    Filters to a single pricing tier for readability.
    The full report includes all tiers.

    Args:
        cost_results: List of CostResult objects
        pricing_tier: Which pricing tier to show ("on_demand", "cud_1yr", "cud_3yr")

    Returns:
        Formatted ASCII table string
    """
    # Filter to requested pricing tier
    filtered = [r for r in cost_results if r.pricing_tier == pricing_tier]

    if not filtered:
        return "No results found for this pricing tier."

    # Table header
    tier_labels = {
        "on_demand": "On-Demand",
        "cud_1yr": "1-Year CUD",
        "cud_3yr": "3-Year CUD",
    }

    gpu_label = filtered[0].gpu_label
    hourly_cost = filtered[0].hourly_cost_usd

    lines = []
    lines.append(f"GPU Config: {gpu_label} | Pricing: {tier_labels[pricing_tier]} (${hourly_cost:.3f}/hr)")
    lines.append("")

    # Column headers
    header = (
        f"{'Scenario':<25} {'Conc':>5} {'Tokens/min':>12} {'Tokens/sec':>12} "
        f"{'$/M tokens':>11} {'p50 ms':>8} {'p95 ms':>8} {'GPUs for 6M/min':>16}"
    )
    lines.append(header)
    lines.append("─" * len(header))

    # Data rows
    for r in filtered:
        row = (
            f"{r.scenario_name:<25} {r.concurrency:>5} "
            f"{r.tokens_per_minute:>12,.0f} {r.tokens_per_second:>12,.0f} "
            f"${r.cost_per_million_tokens:>10.4f} "
            f"{r.latency_p50_ms:>8.1f} {r.latency_p95_ms:>8.1f} "
            f"{r.gpus_for_6m_tokens_min:>16.2f}"
        )
        lines.append(row)

    return "\n".join(lines)


def save_cost_csv(cost_results: list[CostResult], output_path: str) -> None:
    """
    Save cost analysis results to a CSV file.

    This CSV is the primary deliverable — the "throughput as a function of cost"
    matrix that the user uses for pricing decisions.

    Columns:
    - scenario, concurrency, gpu_label
    - tokens_per_sec, tokens_per_min, tokens_per_hour
    - pricing_tier, hourly_cost_usd, cost_per_million_tokens
    - gpus_for_6m_tokens_min
    - latency_p50_ms, latency_p95_ms, latency_p99_ms
    """
    headers = [
        "scenario", "concurrency", "gpu_label",
        "tokens_per_sec", "tokens_per_min", "tokens_per_hour",
        "pricing_tier", "hourly_cost_usd", "cost_per_million_tokens",
        "gpus_for_6m_tokens_min",
        "latency_p50_ms", "latency_p95_ms", "latency_p99_ms",
    ]

    with open(output_path, "w") as f:
        f.write(",".join(headers) + "\n")
        for r in cost_results:
            row = [
                r.scenario_name,
                str(r.concurrency),
                r.gpu_label,
                f"{r.tokens_per_second:.1f}",
                f"{r.tokens_per_minute:.1f}",
                f"{r.tokens_per_hour:.1f}",
                r.pricing_tier,
                f"{r.hourly_cost_usd:.3f}",
                f"{r.cost_per_million_tokens:.6f}",
                f"{r.gpus_for_6m_tokens_min:.2f}",
                f"{r.latency_p50_ms:.1f}",
                f"{r.latency_p95_ms:.1f}",
                f"{r.latency_p99_ms:.1f}",
            ]
            f.write(",".join(row) + "\n")


if __name__ == "__main__":
    """
    CLI usage for standalone cost calculation.

    This can be run independently after benchmarks complete:
        python analysis/cost_calculator.py \\
            --results results/benchmark_1x-rtx-pro-6000_20260515_140000.json \\
            --pricing analysis/pricing_data.yaml
    """
    import argparse

    parser = argparse.ArgumentParser(description="Calculate cost per million tokens")
    parser.add_argument("--results", type=str, required=True, help="Path to benchmark JSON results")
    parser.add_argument("--pricing", type=str, default="analysis/pricing_data.yaml",
                        help="Path to pricing YAML")
    parser.add_argument("--output", type=str, default=None,
                        help="Output CSV path (default: auto-generated)")
    args = parser.parse_args()

    # Load data
    benchmark_results = load_benchmark_results(args.results)
    pricing_data = load_pricing(args.pricing)

    # Calculate costs
    cost_results = calculate_costs(benchmark_results, pricing_data)

    # Print tables for all pricing tiers
    for tier in ["on_demand", "cud_1yr", "cud_3yr"]:
        print(f"\n{'=' * 80}")
        print(format_cost_table(cost_results, pricing_tier=tier))
        print()

    # Save CSV
    if args.output:
        csv_path = args.output
    else:
        base = os.path.splitext(args.results)[0]
        csv_path = f"{base}_costs.csv"

    save_cost_csv(cost_results, csv_path)
    print(f"\n💾 Cost analysis saved to: {csv_path}")
