#!/usr/bin/env python3
"""
=============================================================================
Workload Profile Definitions for the target application Embedding Benchmark
=============================================================================

This module defines the exact workload scenarios to benchmark, based on
the target requirements for batch embedding workloads.

the target Async Batch Ingest Use Case:
    - the target applicationsearch receives a bulk of documents from a user
    - Documents are chunked (default: ~250 words ≈ 512 tokens, max: 32k tokens)
    - Chunks are batched (default batch size: 16) and sent as HTTP requests
      to the the target application Inference Service
    - The inference service calls the embedding model endpoint
    - Results are returned asynchronously — user doesn't wait in real-time

What We Test:
    Scenario 1: Default chunk size (512 tokens) — the most common case
    Scenario 2: Maximum chunk size (32k tokens) — worst case, some users send this

    For each scenario, we ramp concurrency from 1 to 128 to find:
    - The throughput ceiling (tokens/sec at saturation)
    - The concurrency sweet spot (where adding more clients doesn't help)
    - Whether requests stay under the 20s timeout at max load

Synthetic Text Generation:
    We generate synthetic text of specific token lengths using the Jina V5
    tokenizer vocabulary. The exact content doesn't matter for throughput
    benchmarking — what matters is the token count, which determines GPU
    compute per request.
=============================================================================
"""

import random
import string
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Synthetic text generation
# ---------------------------------------------------------------------------
# We need to generate text that tokenizes to approximately a target number
# of tokens. For most subword tokenizers (including Jina V5's), English words
# average ~1.3 tokens per word. We use a simple approach:
# - Generate random words of 4-8 characters
# - Each word ≈ 1 token (short words are usually single tokens)
# - Add 10% extra words as buffer, since some words may split into subtokens
#
# This is sufficiently accurate for throughput benchmarking. The GPU compute
# cost scales with token count, not with the semantic content of the text.
# ---------------------------------------------------------------------------

def generate_synthetic_text(target_tokens: int, seed: int = 42) -> str:
    """
    Generate synthetic English-like text that tokenizes to approximately
    the target number of tokens.

    Args:
        target_tokens: Approximate number of tokens desired
        seed: Random seed for reproducibility across benchmark runs

    Returns:
        A string of synthetic text

    Note:
        We use simple random words rather than real text to avoid any
        caching effects in the model or tokenizer. Each generated text
        is unique but deterministic (same seed = same text).
    """
    rng = random.Random(seed)

    # Common English words that are typically single tokens in most tokenizers
    # Using real-ish words gives more realistic tokenization than random chars
    common_words = [
        "the", "be", "to", "of", "and", "a", "in", "that", "have", "it",
        "for", "not", "on", "with", "he", "as", "you", "do", "at", "this",
        "but", "his", "by", "from", "they", "we", "say", "her", "she", "or",
        "an", "will", "my", "one", "all", "would", "there", "their", "what",
        "so", "up", "out", "if", "about", "who", "get", "which", "go", "me",
        "when", "make", "can", "like", "time", "no", "just", "him", "know",
        "take", "people", "into", "year", "your", "good", "some", "could",
        "them", "see", "other", "than", "then", "now", "look", "only", "come",
        "its", "over", "think", "also", "back", "after", "use", "two", "how",
        "our", "work", "first", "well", "way", "even", "new", "want", "day",
        "data", "system", "search", "index", "query", "document", "field",
        "value", "type", "name", "text", "model", "vector", "embedding",
        "cluster", "node", "shard", "replica", "mapping", "filter", "score",
        "result", "request", "response", "error", "status", "config", "setting",
    ]

    # Generate approximately target_tokens words
    # Most common English words tokenize to 1 token, so word count ≈ token count
    # Add 5% buffer for multi-token words
    word_count = int(target_tokens * 1.05)

    words = [rng.choice(common_words) for _ in range(word_count)]
    return " ".join(words)


def generate_batch(
    batch_size: int,
    target_tokens_per_text: int,
    batch_index: int = 0,
) -> list[str]:
    """
    Generate a batch of synthetic texts for a single API request.

    Each text in the batch has approximately the same token length,
    matching the target pattern where chunked documents in a batch
    are roughly similar in size.

    Args:
        batch_size: Number of texts per request (the target application default: 16)
        target_tokens_per_text: Token length per text (512 or 32768)
        batch_index: Used as seed offset so different requests get different text

    Returns:
        List of synthetic text strings
    """
    return [
        generate_synthetic_text(
            target_tokens=target_tokens_per_text,
            seed=batch_index * batch_size + i,
        )
        for i in range(batch_size)
    ]


# ---------------------------------------------------------------------------
# Workload Scenario Definitions
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkScenario:
    """
    Defines a single benchmark test scenario.

    Each scenario specifies:
    - What payload to send (batch size, token length)
    - What concurrency levels to test
    - What we're measuring and why
    """

    # Human-readable name for this scenario
    name: str

    # Description of what this scenario tests and why
    description: str

    # Number of texts per API request
    # the target default for ingest is 16
    batch_size: int

    # Approximate token count per text in the batch
    # 512 = default chunk size (~250 words)
    # 32768 = maximum model context window
    target_tokens_per_text: int

    # Concurrency levels to test (number of simultaneous in-flight requests)
    # We ramp up to find the saturation point where adding more concurrency
    # doesn't increase throughput
    concurrency_levels: list[int]

    # How long to run each concurrency level (seconds)
    duration_seconds: int

    # Warmup period before measurement starts (seconds)
    warmup_seconds: int

    @property
    def tokens_per_request(self) -> int:
        """Total tokens per API request = batch_size × tokens_per_text."""
        return self.batch_size * self.target_tokens_per_text

    def get_request_payload(self, batch_index: int = 0) -> dict:
        """
        Generate the JSON payload for a single /v1/embeddings request.

        This matches the OpenAI embeddings API format that vLLM expects:
        {
            "input": ["text1", "text2", ...],
            "model": "jinaai/jina-embeddings-v5-text-small"
        }

        Args:
            batch_index: Varies the text content between requests

        Returns:
            Dict ready to be JSON-serialized and sent to the endpoint
        """
        texts = generate_batch(
            batch_size=self.batch_size,
            target_tokens_per_text=self.target_tokens_per_text,
            batch_index=batch_index,
        )
        return {
            "input": texts,
            "model": "jinaai/jina-embeddings-v5-text-small",
        }


def get_benchmark_scenarios(config: dict) -> list[BenchmarkScenario]:
    """
    Create the benchmark scenarios from configuration.

    Returns two scenarios matching the target ingest workload:
    1. Default chunk (512 tokens) — most common real-world case
    2. Max context (32k tokens) — worst case that some users trigger

    Args:
        config: The loaded config.yaml dictionary

    Returns:
        List of BenchmarkScenario objects to execute
    """
    bench_config = config["benchmark"]

    scenarios = [
        # -----------------------------------------------------------------
        # Scenario 1: Default Chunk Size (512 tokens)
        # -----------------------------------------------------------------
        # This is the most common case in production. the target default
        # chunking strategy splits documents into ~250 word chunks, which
        # is roughly 512 tokens.
        #
        # With batch_size=16 and 512 tokens each, each request contains
        # ~8,192 tokens total. This is a relatively light request that
        # should allow high concurrency and throughput.
        #
        # We ramp concurrency from 1 to 128 to find the saturation point.
        # At some concurrency level, the GPU becomes fully utilized and
        # adding more concurrent requests just increases queue depth
        # without improving throughput.
        # -----------------------------------------------------------------
        BenchmarkScenario(
            name="ingest-default-chunk",
            description=(
                "Async batch ingest with default the target applicationsearch chunk size. "
                "Batch of 16 texts × ~512 tokens each = ~8,192 tokens/request. "
                "This is the most common production workload. "
                "Target: exceed 6M tokens/min (the target per-user rate limit)."
            ),
            batch_size=bench_config["batch_size"],
            target_tokens_per_text=bench_config["token_lengths"]["default_chunk"],
            concurrency_levels=bench_config["concurrency_levels"],
            duration_seconds=bench_config["duration_seconds"],
            warmup_seconds=bench_config["warmup_seconds"],
        ),

        # -----------------------------------------------------------------
        # Scenario 2: Maximum Context Window (32k tokens)
        # -----------------------------------------------------------------
        # Some the target application users send very large documents without chunking,
        # or use large chunk sizes. The model supports up to 32k tokens.
        #
        # With batch_size=16 and 32,768 tokens each, each request contains
        # ~524,288 tokens total. This is an extremely heavy request that
        # will stress GPU memory and compute.
        #
        # We test fewer concurrency levels (1-32) because:
        # - Very high concurrency with 32k inputs may cause OOM
        # - Each request takes much longer, so fewer concurrent requests
        #   are needed to saturate the GPU
        #
        # This scenario helps the target application understand the worst-case throughput
        # and cost when users send maximum-length inputs.
        # -----------------------------------------------------------------
        BenchmarkScenario(
            name="ingest-max-context",
            description=(
                "Async batch ingest with maximum context window. "
                "Batch of 16 texts × ~32,768 tokens each = ~524,288 tokens/request. "
                "Worst case scenario when users send very large documents. "
                "Lower concurrency tested to avoid OOM."
            ),
            batch_size=bench_config["batch_size"],
            target_tokens_per_text=bench_config["token_lengths"]["max_context"],
            concurrency_levels=bench_config["concurrency_levels_32k"],
            duration_seconds=bench_config["duration_seconds"],
            warmup_seconds=bench_config["warmup_seconds"],
        ),
    ]

    return scenarios


# ---------------------------------------------------------------------------
# Utility: Print scenario summary
# ---------------------------------------------------------------------------

def print_scenarios(scenarios: list[BenchmarkScenario]) -> None:
    """Print a formatted summary of all benchmark scenarios."""
    print("\n" + "=" * 70)
    print("BENCHMARK SCENARIOS")
    print("=" * 70)

    for i, scenario in enumerate(scenarios, 1):
        print(f"\n{'─' * 70}")
        print(f"Scenario {i}: {scenario.name}")
        print(f"{'─' * 70}")
        print(f"  Description:    {scenario.description}")
        print(f"  Batch size:     {scenario.batch_size} texts/request")
        print(f"  Tokens/text:    {scenario.target_tokens_per_text:,}")
        print(f"  Tokens/request: {scenario.tokens_per_request:,}")
        print(f"  Concurrency:    {scenario.concurrency_levels}")
        print(f"  Duration:       {scenario.duration_seconds}s per level "
              f"(+ {scenario.warmup_seconds}s warmup)")

    total_tests = sum(len(s.concurrency_levels) for s in scenarios)
    total_time = sum(
        len(s.concurrency_levels) * (s.duration_seconds + s.warmup_seconds)
        for s in scenarios
    )
    print(f"\n{'=' * 70}")
    print(f"Total: {len(scenarios)} scenarios, {total_tests} concurrency tests")
    print(f"Estimated time: {total_time // 60}m {total_time % 60}s")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    """Preview the scenarios when run directly."""
    import yaml

    # Load config to show real scenario definitions
    try:
        with open("deploy/config.yaml") as f:
            config = yaml.safe_load(f)
        scenarios = get_benchmark_scenarios(config)
    except FileNotFoundError:
        # Use defaults if config not found
        print("Note: config.yaml not found, using default values\n")
        config = {
            "benchmark": {
                "batch_size": 16,
                "token_lengths": {"default_chunk": 512, "max_context": 32768},
                "concurrency_levels": [1, 4, 16, 32, 64, 128],
                "concurrency_levels_32k": [1, 4, 16, 32],
                "duration_seconds": 60,
                "warmup_seconds": 10,
            }
        }
        scenarios = get_benchmark_scenarios(config)

    print_scenarios(scenarios)

    # Show a sample payload
    print("\nSample request payload (Scenario 1, first 100 chars of each text):")
    payload = scenarios[0].get_request_payload(batch_index=0)
    print(f"  Model: {payload['model']}")
    print(f"  Batch size: {len(payload['input'])} texts")
    for i, text in enumerate(payload["input"][:3]):
        print(f"  Text {i}: {text[:100]}...")
    print(f"  ... ({len(payload['input']) - 3} more texts)")
