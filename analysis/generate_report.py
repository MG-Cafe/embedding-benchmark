#!/usr/bin/env python3
"""
=============================================================================
Report Generator — Markdown + CSV Throughput-vs-Cost Matrix
=============================================================================

This script generates the final deliverable report from benchmark results.
It produces a comprehensive Markdown document that can be shared directly
with the user's team and included in the GitHub repository.

The report includes:
1. Executive Summary — Key findings and recommendations
2. Throughput-vs-Cost Matrix — The core deliverable for the user's pricing decisions
3. Scaling Analysis — 1-GPU vs 2-GPU efficiency comparison (if both results exist)
4. Success Criteria Evaluation — Did we hit the user's targets?
5. Detailed Results — Per-scenario, per-concurrency breakdown
6. Capacity Planning — How many GPUs needed for different user counts

Usage:
    python analysis/generate_report.py --results-dir results/

    # With custom pricing file
    python analysis/generate_report.py \\
        --results-dir results/ \\
        --pricing analysis/pricing_data.yaml

Output:
    results/BENCHMARK_REPORT.md     — Full Markdown report
    results/cost_matrix.csv         — Combined cost data from all GPU configs
=============================================================================
"""

import argparse
import glob
import json
import os
from datetime import datetime

import yaml

from analysis.cost_calculator import (
    load_pricing,
    load_benchmark_results,
    calculate_costs,
    format_cost_table,
    save_cost_csv,
    CostResult,
)


def find_result_files(results_dir: str) -> list[str]:
    """
    Find all benchmark JSON result files in the results directory.

    Returns paths sorted by GPU label for consistent report ordering:
    1x-GPU results first, then 2x-GPU results.
    """
    pattern = os.path.join(results_dir, "benchmark_*.json")
    files = glob.glob(pattern)
    return sorted(files)


def load_all_results(result_files: list[str]) -> list[dict]:
    """Load all benchmark result files."""
    results = []
    for path in result_files:
        with open(path, "r") as f:
            results.append(json.load(f))
    return results


def generate_executive_summary(
    all_cost_results: list[CostResult],
    all_benchmark_data: list[dict],
) -> str:
    """
    Generate the executive summary section of the report.

    Highlights:
    - Best throughput achieved
    - Lowest cost per million tokens
    - Whether 6M tokens/min target was met
    - 1-GPU vs 2-GPU scaling efficiency
    """
    lines = []
    lines.append("## Executive Summary\n")

    # Find best results across all configs (on-demand pricing)
    on_demand = [r for r in all_cost_results if r.pricing_tier == "on_demand"]

    if not on_demand:
        lines.append("No benchmark results found.\n")
        return "\n".join(lines)

    # Best throughput (default chunk scenario)
    default_chunk = [r for r in on_demand if "default-chunk" in r.scenario_name]
    max_context = [r for r in on_demand if "max-context" in r.scenario_name]

    if default_chunk:
        best_throughput = max(default_chunk, key=lambda r: r.tokens_per_minute)
        lines.append(f"### Peak Performance (Default Chunk ~512 tokens)\n")
        lines.append(f"- **Best throughput**: {best_throughput.tokens_per_minute:,.0f} tokens/min "
                      f"({best_throughput.tokens_per_second:,.0f} tokens/sec)")
        lines.append(f"- **GPU config**: {best_throughput.gpu_label} at concurrency={best_throughput.concurrency}")
        lines.append(f"- **Cost**: ${best_throughput.cost_per_million_tokens:.4f} per million tokens (on-demand)")

        # Check 6M target
        if best_throughput.tokens_per_minute >= 6_000_000:
            lines.append(f"- **6M tokens/min target**: ✅ **ACHIEVED** "
                          f"({best_throughput.tokens_per_minute / 6_000_000:.1f}× target)")
        else:
            lines.append(f"- **6M tokens/min target**: ❌ Not reached "
                          f"({best_throughput.tokens_per_minute / 6_000_000:.0%} of target)")
            lines.append(f"  - GPUs needed: {best_throughput.gpus_for_6m_tokens_min:.1f} instances "
                          f"of {best_throughput.gpu_label}")
        lines.append("")

    if max_context:
        best_max = max(max_context, key=lambda r: r.tokens_per_minute)
        lines.append(f"### Peak Performance (Max Context ~32k tokens)\n")
        lines.append(f"- **Best throughput**: {best_max.tokens_per_minute:,.0f} tokens/min")
        lines.append(f"- **GPU config**: {best_max.gpu_label} at concurrency={best_max.concurrency}")
        lines.append(f"- **Cost**: ${best_max.cost_per_million_tokens:.4f} per million tokens (on-demand)")
        lines.append("")

    # Cost savings with CUD
    if default_chunk:
        best_on_demand = min(default_chunk, key=lambda r: r.cost_per_million_tokens)
        # Find the same scenario/concurrency in CUD pricing
        cud_3yr = [r for r in all_cost_results
                    if r.pricing_tier == "cud_3yr"
                    and r.scenario_name == best_on_demand.scenario_name
                    and r.concurrency == best_on_demand.concurrency
                    and r.gpu_label == best_on_demand.gpu_label]
        if cud_3yr:
            savings = (1 - cud_3yr[0].cost_per_million_tokens / best_on_demand.cost_per_million_tokens) * 100
            lines.append(f"### Cost Optimization\n")
            lines.append(f"- **Lowest on-demand cost**: ${best_on_demand.cost_per_million_tokens:.4f}/M tokens")
            lines.append(f"- **With 3-year CUD**: ${cud_3yr[0].cost_per_million_tokens:.4f}/M tokens "
                          f"(**{savings:.0f}% savings**)")
            lines.append("")

    # Scaling efficiency (if we have both 1-GPU and 2-GPU results)
    gpu_labels = list(set(r.gpu_label for r in default_chunk)) if default_chunk else []
    if len(gpu_labels) >= 2:
        lines.append(f"### Scaling Efficiency\n")
        for label in sorted(gpu_labels):
            label_results = [r for r in default_chunk if r.gpu_label == label]
            best = max(label_results, key=lambda r: r.tokens_per_minute)
            lines.append(f"- **{label}**: {best.tokens_per_minute:,.0f} tokens/min peak")

        # Calculate scaling ratio
        single_results = [r for r in default_chunk if "1x" in r.gpu_label.lower()]
        dual_results = [r for r in default_chunk if "2x" in r.gpu_label.lower()]
        if single_results and dual_results:
            best_single = max(single_results, key=lambda r: r.tokens_per_minute)
            best_dual = max(dual_results, key=lambda r: r.tokens_per_minute)
            ratio = best_dual.tokens_per_minute / best_single.tokens_per_minute
            lines.append(f"- **Scaling ratio**: {ratio:.2f}× (ideal = 2.0×)")
            if ratio >= 1.8:
                lines.append(f"  - ✅ Near-linear scaling — 2-GPU config is cost-efficient")
            elif ratio >= 1.5:
                lines.append(f"  - ⚠️ Sublinear scaling — some overhead, but still worthwhile")
            else:
                lines.append(f"  - ❌ Poor scaling — consider using 2× single-GPU instead")
        lines.append("")

    return "\n".join(lines)


def generate_cost_matrix_section(
    all_cost_results: list[CostResult],
) -> str:
    """
    Generate the throughput-vs-cost matrix section.

    This is THE core deliverable. Formatted as Markdown tables.
    """
    lines = []
    lines.append("## Throughput-vs-Cost Matrix\n")
    lines.append("This is the key deliverable: throughput as a function of cost.\n")
    lines.append("Use this matrix to determine pricing and rate limits for users.\n")

    # Group by GPU label
    gpu_labels = sorted(set(r.gpu_label for r in all_cost_results))

    for gpu_label in gpu_labels:
        label_results = [r for r in all_cost_results if r.gpu_label == gpu_label]

        for tier in ["on_demand", "cud_1yr", "cud_3yr"]:
            tier_results = [r for r in label_results if r.pricing_tier == tier]
            if not tier_results:
                continue

            tier_labels = {
                "on_demand": "On-Demand",
                "cud_1yr": "1-Year CUD",
                "cud_3yr": "3-Year CUD",
            }

            hourly = tier_results[0].hourly_cost_usd
            lines.append(f"### {gpu_label} — {tier_labels[tier]} (${hourly:.3f}/hr)\n")

            # Markdown table
            lines.append("| Scenario | Concurrency | Tokens/min | Tokens/sec | $/M Tokens | p50 (ms) | p95 (ms) | GPUs for 6M/min |")
            lines.append("|----------|------------|------------|------------|-----------|----------|----------|----------------|")

            for r in tier_results:
                lines.append(
                    f"| {r.scenario_name} | {r.concurrency} | "
                    f"{r.tokens_per_minute:,.0f} | {r.tokens_per_second:,.0f} | "
                    f"${r.cost_per_million_tokens:.4f} | "
                    f"{r.latency_p50_ms:.1f} | {r.latency_p95_ms:.1f} | "
                    f"{r.gpus_for_6m_tokens_min:.2f} |"
                )

            lines.append("")

    return "\n".join(lines)


def generate_success_criteria_section(
    all_cost_results: list[CostResult],
    all_benchmark_data: list[dict],
) -> str:
    """
    Evaluate benchmark results against the user's success criteria.
    """
    lines = []
    lines.append("## Success Criteria Evaluation\n")
    lines.append("Based on the user's requirements from the scoping call:\n")

    on_demand = [r for r in all_cost_results if r.pricing_tier == "on_demand"]
    default_chunk = [r for r in on_demand if "default-chunk" in r.scenario_name]

    # Criterion 1: 6M tokens/min
    lines.append("### 1. Can the GPU handle 6M tokens/min?\n")
    if default_chunk:
        best = max(default_chunk, key=lambda r: r.tokens_per_minute)
        if best.tokens_per_minute >= 6_000_000:
            lines.append(f"✅ **YES** — Achieved {best.tokens_per_minute:,.0f} tokens/min "
                          f"({best.tokens_per_minute / 6_000_000:.1f}× target) "
                          f"with {best.gpu_label} at concurrency={best.concurrency}")
        else:
            lines.append(f"❌ **NO** — Peak was {best.tokens_per_minute:,.0f} tokens/min "
                          f"({best.tokens_per_minute / 6_000_000:.0%} of target)")
            lines.append(f"   Need {best.gpus_for_6m_tokens_min:.1f} instances of "
                          f"{best.gpu_label} to reach 6M tokens/min")
    lines.append("")

    # Criterion 2: Throughput ceiling
    lines.append("### 2. What is the absolute throughput ceiling?\n")
    if default_chunk:
        for gpu_label in sorted(set(r.gpu_label for r in default_chunk)):
            label_results = [r for r in default_chunk if r.gpu_label == gpu_label]
            best = max(label_results, key=lambda r: r.tokens_per_minute)
            lines.append(f"- **{gpu_label}**: {best.tokens_per_minute:,.0f} tokens/min "
                          f"(at concurrency={best.concurrency})")
    lines.append("")

    # Criterion 3: Cost matrix delivered
    lines.append("### 3. Throughput-vs-cost matrix\n")
    lines.append("✅ **Delivered** — See the full matrix in the section above.\n")

    # Criterion 4: Scaling efficiency
    gpu_labels = sorted(set(r.gpu_label for r in default_chunk)) if default_chunk else []
    if len(gpu_labels) >= 2:
        lines.append("### 4. 1→2 GPU scaling efficiency\n")
        single = [r for r in default_chunk if "1x" in r.gpu_label.lower()]
        dual = [r for r in default_chunk if "2x" in r.gpu_label.lower()]
        if single and dual:
            best_s = max(single, key=lambda r: r.tokens_per_minute)
            best_d = max(dual, key=lambda r: r.tokens_per_minute)
            ratio = best_d.tokens_per_minute / best_s.tokens_per_minute
            lines.append(f"- 1-GPU peak: {best_s.tokens_per_minute:,.0f} tokens/min")
            lines.append(f"- 2-GPU peak: {best_d.tokens_per_minute:,.0f} tokens/min")
            lines.append(f"- **Scaling ratio: {ratio:.2f}×** (ideal = 2.0×)")
        lines.append("")

    # Criterion 5: Under 20s timeout
    lines.append("### 5. All requests under 20s timeout\n")
    all_under = True
    for data in all_benchmark_data:
        for result in data["results"]:
            if not result.get("all_under_20s", True):
                all_under = False
                lines.append(f"❌ Some requests exceeded 20s in "
                              f"{result['scenario_name']} at concurrency={result['concurrency']}")

    if all_under:
        lines.append("✅ **All requests completed within 20s across all test scenarios.**\n")
    lines.append("")

    return "\n".join(lines)


def generate_capacity_planning_section(
    all_cost_results: list[CostResult],
) -> str:
    """
    Generate capacity planning recommendations.

    Shows how many GPU instances the user needs for different user counts.
    """
    lines = []
    lines.append("## Capacity Planning\n")
    lines.append("Based on the user's rate limit of 6M tokens/min per user, "
                  "here's how many GPU instances are needed:\n")

    on_demand_default = [
        r for r in all_cost_results
        if r.pricing_tier == "on_demand" and "default-chunk" in r.scenario_name
    ]

    if not on_demand_default:
        lines.append("No default chunk results available for capacity planning.\n")
        return "\n".join(lines)

    # Find optimal concurrency (best throughput) per GPU label
    gpu_labels = sorted(set(r.gpu_label for r in on_demand_default))

    for gpu_label in gpu_labels:
        label_results = [r for r in on_demand_default if r.gpu_label == gpu_label]
        best = max(label_results, key=lambda r: r.tokens_per_minute)

        lines.append(f"### {gpu_label} (optimal concurrency={best.concurrency})\n")
        lines.append(f"Peak throughput per instance: **{best.tokens_per_minute:,.0f} tokens/min**\n")

        lines.append("| Concurrent Users | Required Tokens/min | GPU Instances | Monthly Cost (on-demand) | Monthly Cost (3yr CUD) |")
        lines.append("|-----------------|--------------------|--------------:|------------------------:|----------------------:|")

        for num_users in [1, 5, 10, 25, 50, 100]:
            required_tokens = 6_000_000 * num_users
            instances = required_tokens / best.tokens_per_minute
            import math
            instances_ceil = math.ceil(instances)

            monthly_on_demand = instances_ceil * best.hourly_cost_usd * 24 * 30
            # Get 3yr CUD cost
            cud_result = [r for r in all_cost_results
                           if r.pricing_tier == "cud_3yr"
                           and r.scenario_name == best.scenario_name
                           and r.concurrency == best.concurrency
                           and r.gpu_label == best.gpu_label]
            monthly_cud = instances_ceil * cud_result[0].hourly_cost_usd * 24 * 30 if cud_result else 0

            lines.append(
                f"| {num_users} | {required_tokens:,} | {instances_ceil} | "
                f"${monthly_on_demand:,.0f} | ${monthly_cud:,.0f} |"
            )

        lines.append("")

    return "\n".join(lines)


def generate_full_report(
    all_cost_results: list[CostResult],
    all_benchmark_data: list[dict],
    results_dir: str,
) -> str:
    """
    Generate the complete Markdown report.
    """
    lines = []

    # Title
    lines.append("# the user Embedding Benchmark Report")
    lines.append(f"## Jina Embeddings V5 Text Small on Vertex AI\n")
    lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"**Model**: `jinaai/jina-embeddings-v5-text-small`\n")
    lines.append(f"**Serving Framework**: vLLM v0.15.1\n")
    lines.append(f"**Platform**: Google Cloud Vertex AI\n")

    # GPU configs tested
    gpu_labels = sorted(set(r.gpu_label for r in all_cost_results))
    lines.append(f"**GPU Configurations Tested**: {', '.join(gpu_labels)}\n")
    lines.append("---\n")

    # Sections
    lines.append(generate_executive_summary(all_cost_results, all_benchmark_data))
    lines.append("---\n")
    lines.append(generate_cost_matrix_section(all_cost_results))
    lines.append("---\n")
    lines.append(generate_success_criteria_section(all_cost_results, all_benchmark_data))
    lines.append("---\n")
    lines.append(generate_capacity_planning_section(all_cost_results))
    lines.append("---\n")

    # Methodology
    lines.append("## Methodology\n")
    lines.append("### Test Configuration\n")
    lines.append("- **Batch size**: 16 texts per request (the user's default ingest batch size)")
    lines.append("- **Token lengths**: 512 (default chunk) and 32,768 (max context window)")
    lines.append("- **Concurrency ramp**: 1 → 4 → 16 → 32 → 64 → 128")
    lines.append("- **Duration**: 60 seconds per concurrency level + 10 seconds warmup")
    lines.append("- **Replicas**: 1 (fixed — no autoscaling, measuring raw GPU performance)")
    lines.append("- **Precision**: BF16 (model default)")
    lines.append("")
    lines.append("### Architecture\n")
    lines.append("```")
    lines.append("Load Generator (async Python)  →  Vertex AI Endpoint  →  vLLM Container")
    lines.append("   N concurrent workers              (rawPredict)         (GPU inference)")
    lines.append("   batch of 16 texts each                                  Jina V5 model")
    lines.append("```\n")
    lines.append("### Metrics Collected\n")
    lines.append("- **Throughput**: tokens/sec, tokens/min, requests/min")
    lines.append("- **Latency**: p50, p95, p99 (milliseconds)")
    lines.append("- **Cost**: $/million tokens at on-demand, 1yr CUD, 3yr CUD pricing")
    lines.append("- **Reliability**: error rate, % requests under 20s timeout")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate benchmark report from results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analysis/generate_report.py --results-dir results/
  python analysis/generate_report.py --results-dir results/ --pricing analysis/pricing_data.yaml
        """,
    )
    parser.add_argument(
        "--results-dir",
        type=str,
        required=True,
        help="Directory containing benchmark JSON result files",
    )
    parser.add_argument(
        "--pricing",
        type=str,
        default="analysis/pricing_data.yaml",
        help="Path to pricing data YAML",
    )

    args = parser.parse_args()

    # Find and load all result files
    result_files = find_result_files(args.results_dir)

    if not result_files:
        print(f"❌ No benchmark result files found in {args.results_dir}")
        print(f"   Expected files matching: benchmark_*.json")
        return

    print(f"📊 Found {len(result_files)} result file(s):")
    for f in result_files:
        print(f"   {f}")

    # Load data
    all_benchmark_data = load_all_results(result_files)
    pricing_data = load_pricing(args.pricing)

    # Calculate costs for all results
    all_cost_results = []
    for data in all_benchmark_data:
        costs = calculate_costs(data, pricing_data)
        all_cost_results.extend(costs)

    # Generate report
    print(f"\n📝 Generating report...")
    report = generate_full_report(all_cost_results, all_benchmark_data, args.results_dir)

    # Save report
    report_path = os.path.join(args.results_dir, "BENCHMARK_REPORT.md")
    with open(report_path, "w") as f:
        f.write(report)
    print(f"   ✅ Report saved: {report_path}")

    # Save combined cost CSV
    cost_csv_path = os.path.join(args.results_dir, "cost_matrix.csv")
    save_cost_csv(all_cost_results, cost_csv_path)
    print(f"   ✅ Cost matrix saved: {cost_csv_path}")

    # Print cost tables to console
    print(f"\n{'=' * 80}")
    print(f"COST ANALYSIS SUMMARY (On-Demand Pricing)")
    print(f"{'=' * 80}")
    print(format_cost_table(all_cost_results, pricing_tier="on_demand"))

    print(f"\n{'=' * 80}")
    print(f"Done! Share the report at: {report_path}")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    main()
