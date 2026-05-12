# 🔍 Comprehensive Audit Report: Embedding Benchmark Repository

**Repository:** https://github.com/MG-Cafe/embedding-benchmark  
**Audit Date:** 2026-05-11  
**Auditor:** Automated Deep Code Review  
**Verdict:** ⚠️ **NOT READY TO SHARE AS-IS** — Multiple critical issues must be fixed before customer deployment

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [CRITICAL Issues — Must Fix Before Sharing](#critical-issues)
3. [HIGH Issues — Should Fix Before Sharing](#high-issues)
4. [MEDIUM Issues — Recommended Fixes](#medium-issues)
5. [LOW Issues — Minor/Cosmetic](#low-issues)
6. [What's Good — No Hallucination/Fabrication in Core Logic](#whats-good)
7. [Alignment with Customer Requirements](#alignment-with-customer-requirements)
8. [Replicability Assessment](#replicability-assessment)
9. [Detailed File-by-File Findings](#detailed-findings)

---

## Executive Summary

The benchmark recipe is **architecturally sound** — the core logic for deploying to Vertex AI, generating load, and computing cost metrics is correct and well-documented. The benchmark results in the JSON/CSV files are **real and internally consistent** (token math checks out, latency patterns are realistic, README numbers match JSON data exactly).

However, there are **critical configuration mismatches** that will cause the code to crash immediately if someone tries to replicate it, **inconsistent GPU specs** that undermine credibility, **fabricated/unverifiable pricing data**, and **dead code paths** (the deploy_vertex.py script cannot work with the provided config.yaml).

### Issues by Severity

| Severity | Count | Summary |
|----------|-------|---------|
| 🔴 CRITICAL | 4 | Config breaks code, pricing fabricated, vLLM flag contradiction, max-context 100% failure |
| 🟠 HIGH | 5 | VRAM inconsistency, missing files, error_rate bug, unused dependencies, version mismatch |
| 🟡 MEDIUM | 4 | No search workload, no L4 baseline, deploy_vertex.py has wrong test curl, missing cleanup in README |
| 🟢 LOW | 3 | Minor doc inconsistencies, cosmetic issues |

---

## CRITICAL Issues

### 🔴 C1: `config.yaml` is massively incomplete — Code will crash immediately

**Impact:** Anyone trying to replicate this will get `KeyError` crashes on **every script**.

The `config.yaml` has only 4 top-level keys (`gcp`, `model`, `gpu`, `benchmark`) with minimal fields. But the Python code expects **20+ config keys** that **do not exist**:

| Script | Missing Config Keys | Crash Point |
|--------|-------------------|-------------|
| `run_benchmark.py` | `benchmark.results_dir` | Line 337 |
| `workload_profiles.py` | `benchmark.batch_size`, `benchmark.token_lengths.default_chunk`, `benchmark.token_lengths.max_context`, `benchmark.concurrency_levels_32k`, `benchmark.duration_seconds`, `benchmark.warmup_seconds` | Lines 244-281 |
| `deploy_vertex.py` | `gcp.artifact_registry.*`, `hardware.single_gpu.*`, `hardware.dual_gpu.*`, `model.hf_model_id`, `model.display_name`, `model.predict_route`, `model.health_route`, `model.serving_port`, `model.max_model_len`, `model.dtype`, `endpoint.*` | Lines 59-209 |
| `cleanup_vertex.py` | `model.display_name` | Line 94 |

**Fix Required:** Expand `config.yaml` to include ALL keys referenced by the code. The correct config should look like:

```yaml
gcp:
  project_id: "YOUR_PROJECT_ID"
  region: "europe-west4"
  artifact_registry:
    repository: "embedding-benchmark"
    image_name: "jina-v5-vllm"
    image_tag: "v0.20.1"

model:
  name: "jinaai/jina-embeddings-v5-text-small"
  hf_model_id: "jinaai/jina-embeddings-v5-text-small"
  display_name: "jina-v5-embedding"
  task: "embed"
  predict_route: "/v1/embeddings"
  health_route: "/health"
  serving_port: 8000
  max_model_len: 32768
  dtype: "bfloat16"

hardware:
  single_gpu:
    machine_type: "g4-standard-48"
    accelerator_type: "NVIDIA_RTX_PRO_6000"
    accelerator_count: 1
    tensor_parallel_size: 1
    display_name_suffix: "1gpu"
  dual_gpu:
    machine_type: "g4-standard-48"
    accelerator_type: "NVIDIA_RTX_PRO_6000"
    accelerator_count: 1
    tensor_parallel_size: 1
    display_name_suffix: "2gpu"

endpoint:
  min_replica_count: 1
  max_replica_count: 1
  traffic_percentage: 100
  deploy_timeout: 1800

benchmark:
  batch_size: 16
  token_lengths:
    default_chunk: 512
    max_context: 32768
  concurrency_levels: [1, 4, 16, 32, 64, 128]
  concurrency_levels_32k: [1, 4, 16, 32]
  duration_seconds: 60
  warmup_seconds: 10
  results_dir: "results"
```

---

### 🔴 C2: G4 pricing data is fabricated/unverifiable

**Impact:** The cost-per-million-tokens calculations — **the primary deliverable** — use fabricated numbers.

In `analysis/pricing_data.yaml`:
- `g4-standard-8` → **Does not exist** as a GCP machine type (README Issues table even acknowledges this!)
- `g4-standard-16` → **Does not exist** as a GCP machine type
- The prices `$3.054/hr` and `$6.108/hr` are tied to these non-existent types
- The actual machine type used is `g4-standard-48` (correctly used in `config.yaml` and README), but its price is NOT in `pricing_data.yaml`

**Fix Required:** Look up the actual `g4-standard-48` on-demand, 1yr-CUD, and 3yr-CUD pricing from the GCP console for `europe-west4` and update `pricing_data.yaml`.

---

### 🔴 C3: `--task embed` flag contradiction — README says it was removed, but Dockerfile still has it

**Impact:** Potential container startup failure depending on vLLM version behavior.

- README Issues table (line 270): *"| `--task embed` flag error | Not available in v0.20.1 CLI | Removed (auto-detected from model) |"*
- But `Dockerfile` (line 92): **Still has `"--task", "embed"`**
- And `deploy_vertex.py` (line 96): **Still has `"--task", "embed"`**
- README Quick Start (line 127): **Does NOT have `--task` in the gcloud args** (consistent with the fix claim)

So the README says the fix was to remove `--task embed`, but the Dockerfile and deploy script still have it. Either:
1. The `--task embed` flag actually works in v0.20.1 (in which case the Issues table is wrong), or
2. The Dockerfile is broken and will fail on startup

**Fix Required:** Test whether `--task embed` works with `vllm/vllm-openai:v0.20.1`. If it does, update the Issues table. If it doesn't, remove it from the Dockerfile and deploy_vertex.py.

---

### 🔴 C4: `ingest-max-context` scenario is fundamentally broken — 100% failure rate

**Impact:** Half the benchmark produces zero useful data. Customer will see this and lose confidence.

All 3 result files show **100% failure** for every `ingest-max-context` test (0 successful out of 58-850 requests per test). The root cause: sending `batch_size=16 × 32,768 tokens = 524,288 tokens per request`, which vastly exceeds `max_num_batched_tokens=65,536`.

This means:
- The `ingest-max-context` scenario as designed **cannot work** with the current vLLM configuration
- The workload profile needs to be redesigned (e.g., `batch_size=1` for 32k context, or `batch_size=2` with `max_num_batched_tokens` raised)
- The failure is **not documented** in the README — the README only shows `ingest-default-chunk` results
- The failure is silently present in the JSON/CSV result files

**Fix Required:** Either fix the max-context scenario (reduce batch_size to 1-2 for 32k, and/or increase `max_num_batched_tokens`), or remove it from the benchmark and document why.

---

## HIGH Issues

### 🟠 H1: VRAM specification inconsistency (48GB vs 96GB)

**Impact:** Undermines technical credibility. Customer will notice.

| File | VRAM Claim | 
|------|-----------|
| README.md (lines 3, 10, 83, 228) | **96GB** |
| config.yaml (line 18) | **96GB** |
| Dockerfile (line 17) | **48GB** |
| pricing_data.yaml (line 65) | **48GB** |

The NVIDIA RTX Pro 6000 (Blackwell, 2025) has 96GB GDDR7. The older RTX 6000 Ada has 48GB. **Verify which GPU is actually on GCP's g4-standard-48** and update all files consistently.

---

### 🟠 H2: Missing files referenced in README

**Impact:** README promises files that don't exist.

The README Repository Structure section (lines 212-214) lists:
- `results/raw_1gpu_terminal_output.log` ❌ **Does not exist**
- `results/raw_1gpu_32k_terminal_output.log` ❌ **Does not exist**  
- `results/raw_2node_forced_terminal_output.log` ❌ **Does not exist**

Also missing: `deploy/deploy_vertex.py` is NOT listed in the README structure tree (only Dockerfile, config.yaml, and cleanup_vertex.py are shown).

**Fix:** Either add the missing log files or remove the references. Add `deploy_vertex.py` to the structure tree.

---

### 🟠 H3: Error rate / all_under_20s bug in compute_aggregates()

**Impact:** Misleading data in result files.

In `load_generator.py`, the `compute_aggregates()` method (line 145) does:
```python
if not successful:
    return  # <-- exits early, leaving error_rate=0.0 and all_under_20s=True as defaults
```

This means when ALL requests fail:
- `error_rate` = 0.0 (should be 1.0)
- `all_under_20s` = True (meaningless when everything failed)

All `ingest-max-context` results in the JSON files show this bug: `failed_requests=58, error_rate=0.0, all_under_20s=true`.

**Fix:** Move the `error_rate` and `all_under_20s` calculations before the early return:
```python
self.error_rate = self.failed_requests / self.total_requests if self.total_requests > 0 else 0.0
if not successful:
    self.all_under_20s = False  # or N/A
    return
```

---

### 🟠 H4: Unused Python dependencies in requirements.txt

**Impact:** Unnecessary install requirements, potential confusion.

`requirements.txt` includes:
- `pandas>=2.0.0` — **Never imported** in any Python file
- `tabulate>=0.9.0` — **Never imported** in any Python file
- `tqdm>=4.65.0` — **Never imported** in any Python file

**Fix:** Remove unused dependencies from `requirements.txt`.

---

### 🟠 H5: vLLM version mismatch in generate_report.py

**Impact:** Generated reports will show wrong version.

`analysis/generate_report.py` (line 372) hardcodes:
```python
lines.append(f"**Serving Framework**: vLLM v0.15.1\n")
```

But the actual version used is **v0.20.1** (as per Dockerfile and README). The POC doc also mentions v0.15.1 as the original target before discovery that Jina V5 wasn't supported.

Similarly, `deploy/Dockerfile` (line 13) comment says:
```
# 4. It's the framework commonly used for serving (vLLM v0.15.1)
```

**Fix:** Update both to v0.20.1.

---

## MEDIUM Issues

### 🟡 M1: No search workload scenario — customer explicitly asked for it

**Impact:** Missing deliverable from POC scope.

The customer POC doc specifies two deployment types:
- **Ingest**: Throughput-focused, 6M tokens/min, 6k RPM ✅ (benchmarked)
- **Search**: Latency-focused, <50ms p50, 2k RPM ❌ (NOT benchmarked)

The customer (Dimitris) said: *"I would also like to leave knowing what I should do if I want latency for another model."*

The benchmark only has `ingest-default-chunk` and `ingest-max-context`. There is no `search-latency` scenario with single-text requests and latency optimization.

**Recommendation:** Add a `search-single-query` scenario: batch_size=1, target_tokens=512, concurrency=[1,4,8,16], measuring p50/p95 latency. Even if it's secondary priority, having the data is valuable.

---

### 🟡 M2: No L4 baseline comparison

**Impact:** Missing the "G2 vs G4 shootout" the customer requested.

The customer POC doc states: *"A core component of this POC is a direct price-to-performance shootout between two GPU types: L4 (G2 instances) vs RTX Pro 6000 (G4 instances)."*

While L4 pricing is in `pricing_data.yaml`, there are **no L4 benchmark results** to compare against. The cost matrix can only show G4 numbers.

**Recommendation:** Run the same benchmark on a G2 instance with L4 GPU, or at minimum document why only G4 was tested and provide estimated L4 numbers from Elastic's existing Cloud Run data.

---

### 🟡 M3: deploy_vertex.py prints wrong test curl endpoint

**Impact:** Copy-paste from script output will fail.

Line 228 in `deploy_vertex.py`:
```python
print(f"     https://{config['gcp']['region']}-aiplatform.googleapis.com/v1/{endpoint.resource_name}:predict")
```

This uses `:predict` but the benchmark uses `:rawPredict`. The user will get a different response format.

**Fix:** Change `:predict` to `:rawPredict`.

---

### 🟡 M4: README Quick Start missing cleanup step

**Impact:** Customer forgets to clean up, gets billed.

The Quick Start has Steps 1-4 but no Step 5 for cleanup. The cleanup script exists (`cleanup_vertex.py`) and is mentioned in run_benchmark.py output, but not in the README Quick Start flow.

**Fix:** Add Step 5: Cleanup with reference to cleanup_vertex.py and the gcloud CLI alternative.

---

## LOW Issues

### 🟢 L1: Three result files for what is really two test configurations

The repo has 3 result files:
- `configA-8192` — 1-GPU, `max-model-len=8192` (early test)
- `configA-32k-1gpu` — 1-GPU, `max-model-len=32768` (same GPU, different config)
- `configA-32k-2node-forced` — 2-node, `max-model-len=32768`

The `configA-8192` and `configA-32k-1gpu` results are extremely similar (within 2.6%) for `ingest-default-chunk` because that scenario only uses ~8k tokens/request anyway. This is expected but may confuse readers about which results are "canonical."

README uses `configA-8192` for the 1-GPU table. **Consider documenting which result file maps to which README table.**

---

### 🟢 L2: The 2-node test label is confusing

The 2-GPU test is actually 2 separate G4 nodes with 1 GPU each, load-balanced by Vertex AI. The label `configA-32k-2node-forced` and README's "2× RTX Pro 6000, 2 G4 nodes, Vertex AI load-balanced" are clear, but the `--gpu-count 2` flag in deploy_vertex.py implies tensor parallelism across 2 GPUs on 1 node, which is different.

---

### 🟢 L3: deploy_vertex.py not listed in README structure

The `deploy/` directory tree in README (line 202-204) shows Dockerfile, config.yaml, cleanup_vertex.py but **omits deploy_vertex.py**.

---

## What's Good — No Hallucination/Fabrication in Core Logic

### ✅ Benchmark Results Are Real and Internally Consistent
- Token math: `successful_requests × 8192 = total_tokens` ✅ checks out perfectly
- README numbers match JSON data exactly (verified all 12 data points)
- Throughput scaling pattern is realistic: linear scaling up to GPU saturation, plateau at C≥64
- Latency increases proportionally with concurrency (queuing theory) ✅
- 2-node scaling is ~2x at high concurrency ✅ (realistic for Vertex AI load balancing)

### ✅ Vertex AI API Usage is Correct
- `aiplatform.init()`, `Model.upload()`, `Endpoint.create()`, `model.deploy()` — all use valid SDK parameters
- `rawPredict` endpoint URL construction is correct
- ADC token authentication approach is correct (with good explanation of why)

### ✅ Load Generator Architecture is Sound
- Async aiohttp with connection pooling ✅
- Warmup period before measurement ✅
- Per-request metrics collection ✅
- Proper latency percentile calculation using numpy ✅

### ✅ Dockerfile is Well-Constructed
- Base image `vllm/vllm-openai:v0.20.1` is correct
- Health check configuration is appropriate (300s start period for model loading)
- ENTRYPOINT/CMD split allows CMD override for multi-GPU

### ✅ Cost Calculator Logic is Mathematically Correct
- Formula: `cost_per_million = (hourly_cost / tokens_per_hour) × 1,000,000` ✅
- Handles all three pricing tiers (on-demand, 1yr CUD, 3yr CUD) ✅
- GPU capacity planning calculation is correct ✅

### ✅ Code Documentation is Excellent
- Every function has detailed docstrings explaining WHY, not just WHAT
- Design decisions are documented inline
- The README explains the architecture and benchmark methodology well

---

## Alignment with Customer Requirements

| Requirement (from scoping call & POC doc) | Status | Notes |
|------------------------------------------|--------|-------|
| Jina Embeddings V5 Text Small model | ✅ | Correctly targets `jinaai/jina-embeddings-v5-text-small` |
| vLLM serving framework | ✅ | v0.20.1 (upgraded from v0.15.1 which didn't support Jina V5) |
| BF16 precision | ✅ | Correctly configured |
| Async batch ingest focus (Priority 1) | ✅ | `ingest-default-chunk` scenario with batch_size=16, 512 tok |
| Max context window test (32k) | ❌ | Scenario exists but 100% failure — needs redesign |
| Throughput-as-function-of-cost matrix | ⚠️ | Logic correct, but pricing data is fabricated |
| G4 vs G2 price-performance comparison | ❌ | No L4 benchmark results for comparison |
| Search latency optimization (Priority 2) | ❌ | No search scenario in benchmark |
| 6M tokens/min target validation | ✅ | Achieved at concurrency=16 (8.3M tok/min) |
| 20-second timeout compliance | ✅ | All successful requests under 20s |
| Vertex AI deployment | ✅ | Correct Vertex AI SDK usage, rawPredict |
| Quantization exploration | ❌ | Only BF16 tested, no quantization variants |
| Multiple regions | ❌ | Only europe-west4 tested (acceptable for POC) |
| Deployable end-to-end recipe | ❌ | config.yaml breaks all scripts |

---

## Replicability Assessment

### Can the customer deploy this end-to-end?

**NO — not without fixing the config.yaml first.**

Here's what happens if someone follows the README Quick Start:

1. **Step 1 (Container Build):** ✅ Will work — Dockerfile is correct, gcloud builds submit commands are valid
2. **Step 2 (Model Upload):** ✅ Will work — gcloud CLI commands are correct  
3. **Step 3 (Deploy):** ✅ Will work — gcloud CLI commands are correct
4. **Step 4 (Run Benchmark):** ❌ **CRASH** — `run_benchmark.py` reads `config["benchmark"]["results_dir"]` → `KeyError`

If someone uses `deploy_vertex.py` instead of the gcloud CLI:
- ❌ **CRASH** — `config["gcp"]["artifact_registry"]` → `KeyError` (very first function call)

**After fixing config.yaml**, the full pipeline would work end-to-end. The README Quick Start approach (using gcloud CLI directly) bypasses the deploy_vertex.py config issues and is the recommended path.

---

## Detailed File-by-File Findings

### deploy/config.yaml (24 lines)
- ❌ Missing ~20 required config keys (see C1)
- ❌ `vram_gb: 96` — inconsistent with Dockerfile/pricing_data (see H1)
- ❌ `measurement_seconds: 60` exists but code expects `duration_seconds` (key name mismatch)

### deploy/Dockerfile (98 lines)
- ✅ Base image correct: `vllm/vllm-openai:v0.20.1`
- ✅ Health check well-configured (300s start period)
- ⚠️ Line 13 comment references v0.15.1
- ⚠️ Line 17 says 48GB VRAM (contradicts README's 96GB)
- ⚠️ Line 92 has `--task embed` which README says was removed (see C3)
- ⚠️ Missing `--trust-remote-code`, `--max-num-seqs=512`, `--gpu-memory-utilization=0.95`, `--enforce-eager`, `--max-num-batched-tokens=65536` which README says are required

### deploy/deploy_vertex.py (289 lines)
- ✅ Vertex AI SDK API usage is correct
- ❌ References 20+ config keys that don't exist in config.yaml (see C1)
- ⚠️ Line 228 uses `:predict` instead of `:rawPredict` (see M3)
- ⚠️ Line 96 has `--task embed` (see C3)

### deploy/cleanup_vertex.py (235 lines)
- ✅ Cleanup logic is correct and well-implemented
- ✅ Dry-run mode is a nice feature
- ❌ References `config["model"]["display_name"]` which doesn't exist in config.yaml

### benchmark/load_generator.py (479 lines)
- ✅ Async load generation architecture is sound
- ✅ Correct Vertex AI rawPredict URL construction
- ✅ Proper ADC authentication with fallback
- ⚠️ `compute_aggregates()` has error_rate/all_under_20s bug for 100% failure cases (see H3)

### benchmark/run_benchmark.py (448 lines)
- ✅ Orchestration logic is correct
- ❌ Line 337: `config["benchmark"]["results_dir"]` doesn't exist in config.yaml
- ✅ CSV/JSON output format matches what analysis scripts expect
- ✅ Good error handling with failed_result fallback

### benchmark/workload_profiles.py (354 lines)
- ✅ Synthetic text generation approach is reasonable
- ✅ BenchmarkScenario dataclass is well-designed
- ❌ References 6 config keys that don't exist (see C1)
- ⚠️ `ingest-max-context` sends 524,288 tokens/request, exceeding `max_num_batched_tokens=65,536` (see C4)
- ✅ Has fallback defaults when config not found (line 333-342)

### analysis/cost_calculator.py (357 lines)
- ✅ Cost calculation formula is mathematically correct
- ✅ GPU label parsing logic works for expected inputs
- ⚠️ Uses fabricated G4 pricing from pricing_data.yaml (see C2)

### analysis/generate_report.py (490 lines)
- ✅ Report generation logic is comprehensive
- ❌ Line 372: Hardcodes "vLLM v0.15.1" (should be v0.20.1) (see H5)
- ✅ Executive summary, cost matrix, capacity planning sections are well-structured

### analysis/pricing_data.yaml (84 lines)
- ✅ G2/L4 pricing looks reasonable (verifiable against GCP pricing page)
- ❌ G4 machine types `g4-standard-8` and `g4-standard-16` don't exist (see C2)
- ❌ G4 pricing numbers are unverifiable/fabricated
- ❌ `gpu_memory_gb: 48` contradicts README's 96GB (see H1)

### results/*.json and *.csv
- ✅ Numbers are internally consistent (token math checks out)
- ✅ README tables match JSON data exactly
- ⚠️ `ingest-max-context` results show 100% failure with error_rate=0.0 (bug, see H3)
- ✅ Throughput patterns are realistic (linear scaling then plateau)

### requirements.txt
- ✅ Core dependencies correct (google-cloud-aiplatform, aiohttp, pyyaml, numpy)
- ⚠️ 3 unused dependencies: pandas, tabulate, tqdm (see H4)

### README.md (279 lines)
- ✅ Benchmark results match JSON data
- ✅ Quick Start gcloud CLI commands are correct
- ✅ Architecture diagram is accurate
- ✅ Issues Encountered table is very helpful
- ⚠️ VRAM inconsistency (96GB in 4 places)
- ⚠️ Missing files referenced in structure tree
- ⚠️ Missing cleanup step in Quick Start

---

## Summary of Required Actions Before Sharing

### Must Do (Blocking):
1. **Fix `config.yaml`** — Add all missing keys so scripts don't crash
2. **Fix G4 pricing** — Update `pricing_data.yaml` with real `g4-standard-48` prices
3. **Resolve `--task embed` contradiction** — Either remove from Dockerfile or update Issues table
4. **Fix or remove `ingest-max-context` scenario** — Either make it work (batch_size=1-2) or remove

### Should Do (High Priority):
5. **Fix VRAM inconsistency** — Verify actual VRAM on GCP's G4 and update all files
6. **Fix error_rate bug** in `compute_aggregates()`
7. **Fix vLLM version** in generate_report.py (v0.15.1 → v0.20.1)
8. **Remove unused dependencies** from requirements.txt
9. **Add missing Dockerfile flags** (`--trust-remote-code`, `--max-num-seqs`, etc.) or reconcile with README

### Nice to Have:
10. Add search-latency scenario
11. Add L4 baseline results for comparison
12. Add cleanup step to README Quick Start
13. Add missing terminal log files or remove references
