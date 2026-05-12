# 🔍 Detailed Audit Report: Embedding Benchmark Repository

**Repository:** https://github.com/MG-Cafe/embedding-benchmark  
**Audit Date:** 2026-05-11  
**Verdict:** ⚠️ **NOT READY TO SHARE AS-IS** — Multiple critical issues must be fixed before customer deployment

---

## Issue Tracker — Every Finding with Full Details

---

## 🔴 CRITICAL ISSUES (4 Total)

These will cause immediate failures or produce incorrect/misleading output.

---

### 🔴 C1: `config.yaml` is massively incomplete — Every Python script will crash

**Severity:** CRITICAL — Blocking  
**Affected Files:** `deploy/config.yaml`, `deploy/deploy_vertex.py`, `deploy/cleanup_vertex.py`, `benchmark/run_benchmark.py`, `benchmark/workload_profiles.py`  
**Type:** Missing code / Incomplete implementation

#### What's Wrong

The `deploy/config.yaml` file has only 24 lines with 4 top-level keys:

```yaml
# CURRENT config.yaml — INCOMPLETE
gcp:
  project_id: "YOUR_PROJECT_ID"
  region: "europe-west4"

model:
  name: "jinaai/jina-embeddings-v5-text-small"
  task: "embed"

gpu:
  type: "nvidia-rtx-pro-6000"
  machine_type: "g4-standard-48"
  vram_gb: 96
  count: 1

benchmark:
  warmup_seconds: 10
  measurement_seconds: 60
  concurrency_levels: [1, 4, 16, 32, 64, 128]
```

But every Python script in the repo expects config keys that **do not exist** in this file. Here is the exhaustive list of every missing key, traced to the exact line of code that will crash:

#### Missing Keys for `benchmark/run_benchmark.py`

| Missing Key | Code Location | Line | What Happens |
|---|---|---|---|
| `config["benchmark"]["results_dir"]` | `run_benchmark.py` | Line 337 | `KeyError: 'results_dir'` — script can't save results |

#### Missing Keys for `benchmark/workload_profiles.py`

| Missing Key | Code Location | Line | What Happens |
|---|---|---|---|
| `config["benchmark"]["batch_size"]` | `workload_profiles.py` | Line 244, 278 | `KeyError: 'batch_size'` — can't create any benchmark scenario |
| `config["benchmark"]["token_lengths"]` | `workload_profiles.py` | Line 245, 279 | `KeyError: 'token_lengths'` — entire dict missing |
| `config["benchmark"]["token_lengths"]["default_chunk"]` | `workload_profiles.py` | Line 245 | Would crash even if `token_lengths` existed |
| `config["benchmark"]["token_lengths"]["max_context"]` | `workload_profiles.py` | Line 279 | Would crash even if `token_lengths` existed |
| `config["benchmark"]["concurrency_levels_32k"]` | `workload_profiles.py` | Line 279 | `KeyError: 'concurrency_levels_32k'` |
| `config["benchmark"]["duration_seconds"]` | `workload_profiles.py` | Line 247, 280 | `KeyError: 'duration_seconds'` — note: config has `measurement_seconds` instead (key name mismatch!) |
| `config["benchmark"]["warmup_seconds"]` | `workload_profiles.py` | Line 248, 281 | This one actually EXISTS in config ✅ |

**Key Name Mismatch Detail:** The config has `measurement_seconds: 60` but the code reads `duration_seconds`. These are different keys! The code will crash with `KeyError: 'duration_seconds'`.

#### Missing Keys for `deploy/deploy_vertex.py`

| Missing Key | Code Location | Line | What Happens |
|---|---|---|---|
| `config["gcp"]["artifact_registry"]` | `deploy_vertex.py` | Line 59 | `KeyError: 'artifact_registry'` — very first function call |
| `config["gcp"]["artifact_registry"]["repository"]` | `deploy_vertex.py` | Line 63 | Nested under missing parent |
| `config["gcp"]["artifact_registry"]["image_name"]` | `deploy_vertex.py` | Line 64 | Nested under missing parent |
| `config["gcp"]["artifact_registry"]["image_tag"]` | `deploy_vertex.py` | Line 64 | Nested under missing parent |
| `config["hardware"]` | `deploy_vertex.py` | Line 75-76 | `KeyError: 'hardware'` — entire section missing |
| `config["hardware"]["single_gpu"]` | `deploy_vertex.py` | Line 75 | Nested under missing parent |
| `config["hardware"]["dual_gpu"]` | `deploy_vertex.py` | Line 77 | Nested under missing parent |
| `config["hardware"]["single_gpu"]["tensor_parallel_size"]` | `deploy_vertex.py` | Line 101 | Nested under missing parent |
| `config["hardware"]["single_gpu"]["machine_type"]` | `deploy_vertex.py` | Line 197 | Nested under missing parent |
| `config["hardware"]["single_gpu"]["accelerator_type"]` | `deploy_vertex.py` | Line 197 | Nested under missing parent |
| `config["hardware"]["single_gpu"]["accelerator_count"]` | `deploy_vertex.py` | Line 197 | Nested under missing parent |
| `config["hardware"]["single_gpu"]["display_name_suffix"]` | `deploy_vertex.py` | Line 125 | Nested under missing parent |
| `config["model"]["hf_model_id"]` | `deploy_vertex.py` | Line 95 | `KeyError: 'hf_model_id'` — config has `name` instead |
| `config["model"]["display_name"]` | `deploy_vertex.py` | Line 125 | `KeyError: 'display_name'` |
| `config["model"]["predict_route"]` | `deploy_vertex.py` | Line 130, 137 | `KeyError: 'predict_route'` |
| `config["model"]["health_route"]` | `deploy_vertex.py` | Line 131, 138 | `KeyError: 'health_route'` |
| `config["model"]["serving_port"]` | `deploy_vertex.py` | Line 98, 139 | `KeyError: 'serving_port'` |
| `config["model"]["max_model_len"]` | `deploy_vertex.py` | Line 99 | `KeyError: 'max_model_len'` |
| `config["model"]["dtype"]` | `deploy_vertex.py` | Line 100 | `KeyError: 'dtype'` |
| `config["endpoint"]` | `deploy_vertex.py` | Line 193 | `KeyError: 'endpoint'` — entire section missing |
| `config["endpoint"]["min_replica_count"]` | `deploy_vertex.py` | Line 198, 206 | Nested under missing parent |
| `config["endpoint"]["max_replica_count"]` | `deploy_vertex.py` | Line 207 | Nested under missing parent |
| `config["endpoint"]["traffic_percentage"]` | `deploy_vertex.py` | Line 208 | Nested under missing parent |
| `config["endpoint"]["deploy_timeout"]` | `deploy_vertex.py` | Line 209 | Nested under missing parent |

#### Missing Keys for `deploy/cleanup_vertex.py`

| Missing Key | Code Location | Line | What Happens |
|---|---|---|---|
| `config["model"]["display_name"]` | `cleanup_vertex.py` | Line 94, 194 | `KeyError: 'display_name'` — can't search for models/endpoints to clean up |

#### Impact on Customer

If a customer clones the repo and runs:
```bash
python benchmark/run_benchmark.py --config deploy/config.yaml --endpoint-id 12345 --gpu-label "1x-rtx"
```
They will get:
```
Traceback (most recent call last):
  File "benchmark/run_benchmark.py", line 337, in main
    results_dir = config["benchmark"]["results_dir"]
KeyError: 'results_dir'
```

If they try the deployment script:
```bash
python deploy/deploy_vertex.py --config deploy/config.yaml --gpu-count 1
```
They will get:
```
Traceback (most recent call last):
  File "deploy/deploy_vertex.py", line 59, in get_container_image_uri
    ar = gcp["artifact_registry"]
KeyError: 'artifact_registry'
```

#### Required Fix

Replace `deploy/config.yaml` with the complete version that includes all keys:

```yaml
# =============================================================================
# Benchmark Configuration — COMPLETE
# =============================================================================
# Update these values for your GCP project before running.
# =============================================================================

gcp:
  project_id: "YOUR_PROJECT_ID"
  region: "europe-west4"  # RTX Pro 6000 regions: us-central1, us-east4, europe-west4
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
    accelerator_count: 1  # 1 GPU per node, 2 replicas for scaling
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
  duration_seconds: 60    # NOTE: was 'measurement_seconds' before — code reads 'duration_seconds'
  warmup_seconds: 10
  results_dir: "results"
```

---

### 🔴 C2: G4 GPU pricing data is fabricated/unverifiable

**Severity:** CRITICAL — Core deliverable is compromised  
**Affected Files:** `analysis/pricing_data.yaml`, `analysis/cost_calculator.py`, `analysis/generate_report.py`  
**Type:** Fabricated data

#### What's Wrong

The `analysis/pricing_data.yaml` file contains G4 (RTX Pro 6000) pricing tied to GCP machine types that **do not exist**:

```yaml
# FROM pricing_data.yaml — PROBLEMS HIGHLIGHTED
g4:
  gpu_name: "NVIDIA RTX Pro 6000"
  gpu_memory_gb: 48                    # ❌ Says 48GB but README says 96GB

  single_gpu:
    machine_type: "g4-standard-8"      # ❌ DOES NOT EXIST IN GCP
    accelerator_count: 1
    on_demand_hourly_usd: 3.054        # ❌ UNVERIFIABLE — tied to non-existent machine type
    cud_1yr_hourly_usd: 1.924          # ❌ UNVERIFIABLE
    cud_3yr_hourly_usd: 1.374          # ❌ UNVERIFIABLE

  dual_gpu:
    machine_type: "g4-standard-16"     # ❌ DOES NOT EXIST IN GCP
    accelerator_count: 2
    on_demand_hourly_usd: 6.108        # ❌ UNVERIFIABLE — exactly 2× single (suspiciously round)
    cud_1yr_hourly_usd: 3.848          # ❌ UNVERIFIABLE
    cud_3yr_hourly_usd: 2.749          # ❌ UNVERIFIABLE
```

#### Evidence of Fabrication

1. **The README itself documents this bug** in the Issues table (line 272):
   ```
   | g4-standard-8 doesn't exist | Smallest G4 is g4-standard-48 | Used g4-standard-48 |
   ```
   This means the author KNEW `g4-standard-8` doesn't exist but never updated `pricing_data.yaml`.

2. **The `config.yaml` correctly uses `g4-standard-48`** — showing the deployment config was fixed, but the pricing file was forgotten.

3. **The dual_gpu price is exactly 2× the single_gpu price** ($6.108 = 2 × $3.054). In reality, larger GCP machine types do NOT scale linearly in price due to the higher vCPU/RAM allocation.

4. **GCP G4 machine types** (as of 2026): The smallest G4 instance is `g4-standard-48` (48 vCPU, 192GB RAM, 1× RTX Pro 6000). There is no `g4-standard-8` or `g4-standard-16`.

#### Impact on Customer

The cost-per-million-tokens matrix is **the primary deliverable** of this POC. Per Max's words in the scoping call:

> *"I'm interested in the function of how much money do we pay for what throughput so that we can also plan for the users getting the throughput that we promised them."*

If the pricing is wrong, the entire cost matrix is wrong, and Elastic cannot use it for pricing decisions.

#### Required Fix

1. Look up the actual `g4-standard-48` pricing from the GCP console or pricing calculator for `europe-west4`
2. Update `pricing_data.yaml`:
   ```yaml
   g4:
     gpu_name: "NVIDIA RTX Pro 6000"
     gpu_memory_gb: 96  # Verify: 48 or 96?

     single_gpu:
       machine_type: "g4-standard-48"
       accelerator_count: 1
       on_demand_hourly_usd: X.XXX  # FROM GCP CONSOLE
       cud_1yr_hourly_usd: X.XXX    # FROM GCP CONSOLE
       cud_3yr_hourly_usd: X.XXX    # FROM GCP CONSOLE

     dual_gpu:  # This is 2 separate nodes, not 1 node with 2 GPUs
       machine_type: "g4-standard-48"
       accelerator_count: 1  # Per node
       # Price = 2× single_gpu (since it's 2 separate VMs)
       on_demand_hourly_usd: Y.YYY
       cud_1yr_hourly_usd: Y.YYY
       cud_3yr_hourly_usd: Y.YYY
   ```

---

### 🔴 C3: `--task embed` flag contradiction — Dockerfile vs README

**Severity:** CRITICAL — Potential container startup failure  
**Affected Files:** `deploy/Dockerfile`, `deploy/deploy_vertex.py`, `README.md`  
**Type:** Contradiction / potentially broken deployment

#### What's Wrong

The README Issues table (line 270) documents this problem and its fix:

```
| `--task embed` flag error | Not available in v0.20.1 CLI | Removed (auto-detected from model) |
```

This says `--task embed` was **removed** because it's "not available in v0.20.1 CLI". But the fix was **never applied**:

**Dockerfile (line 91-92)** — STILL HAS `--task embed`:
```dockerfile
CMD ["--model", "jinaai/jina-embeddings-v5-text-small", \
     "--task", "embed", \           # ← STILL HERE despite README saying it was removed
     "--host", "0.0.0.0", \
     "--port", "8000", \
```

**deploy_vertex.py (lines 95-96)** — STILL HAS `--task embed`:
```python
return [
    "--model", model_config["hf_model_id"],
    "--task", "embed",              # ← STILL HERE
    "--host", "0.0.0.0",
```

**README Quick Start gcloud CLI (line 127)** — Does NOT have `--task`:
```bash
--container-args="--model,jinaai/jina-embeddings-v5-text-small,--host,0.0.0.0,--port,8000,--max-model-len,32768,..."
# No --task flag here — consistent with the "fix" claim
```

#### Which is Correct?

There are two possibilities:

**Possibility A:** `--task embed` actually works in vLLM v0.20.1 for the Python API server entry point, just not as a standalone CLI flag. In that case:
- The Dockerfile is correct ✅
- The README Issues table is misleading (should say "works in container but not CLI")
- The Quick Start gcloud CLI is inconsistent (should include `--task,embed`)

**Possibility B:** `--task embed` truly doesn't work in v0.20.1. In that case:
- The Dockerfile is broken ❌
- The container will fail to start
- But the benchmark results exist... which means the Dockerfile must have worked at some point

Given that real benchmark results exist (timestamps show May 8-10, 2026), the container clearly ran successfully. This means either `--task embed` works (Possibility A) or the actual deployed container had different arguments than what's in the Dockerfile.

#### Required Fix

1. Test `docker run vllm/vllm-openai:v0.20.1 --model jinaai/jina-embeddings-v5-text-small --task embed` to verify
2. If `--task embed` works: Update README Issues table to clarify it works in the API server, remove the misleading row
3. If `--task embed` doesn't work: Remove it from Dockerfile and deploy_vertex.py
4. Either way: Make the Dockerfile, deploy_vertex.py, and README Quick Start consistent

#### Additional Dockerfile Issue: Missing Flags

The README (line 127) shows the gcloud CLI deployment with these flags that are **NOT in the Dockerfile**:

| Flag | In README gcloud CLI | In Dockerfile CMD | Status |
|------|---------------------|-------------------|--------|
| `--trust-remote-code` | ✅ Yes | ❌ No | **MISSING from Dockerfile** |
| `--max-num-seqs 512` | ✅ Yes | ❌ No | **MISSING from Dockerfile** |
| `--gpu-memory-utilization 0.95` | ✅ Yes | ❌ No | **MISSING from Dockerfile** |
| `--enforce-eager` | ✅ Yes | ❌ No | **MISSING from Dockerfile** |
| `--max-num-batched-tokens 65536` | ✅ Yes | ❌ No | **MISSING from Dockerfile** |
| `--disable-log-stats` | ✅ Yes | ❌ No (has `--disable-log-requests` instead) | Different flag name! |

This means if someone builds the container from the Dockerfile and runs it, they get different behavior than the README documents. Specifically:
- Without `--trust-remote-code`, Jina V5 model loading will **fail** (the model uses custom HuggingFace code)
- Without `--max-num-seqs 512`, default is 256 (different from what's documented)
- Without `--gpu-memory-utilization 0.95`, default is 0.9 (different batching behavior)

---

### 🔴 C4: `ingest-max-context` scenario has 100% failure rate — Fundamentally broken

**Severity:** CRITICAL — Half the benchmark produces zero useful data  
**Affected Files:** `benchmark/workload_profiles.py`, all `results/*.json` files  
**Type:** Design flaw / broken test scenario

#### What's Wrong

Every single `ingest-max-context` test across all 3 result files shows **100% failure**:

**From `benchmark_configA-8192_20260508_103305.json`:**
```json
{"scenario_name": "ingest-max-context", "concurrency": 1, "total_requests": 62, "successful_requests": 0, "failed_requests": 62}
{"scenario_name": "ingest-max-context", "concurrency": 4, "total_requests": 230, "successful_requests": 0, "failed_requests": 230}
{"scenario_name": "ingest-max-context", "concurrency": 16, "total_requests": 785, "successful_requests": 0, "failed_requests": 785}
{"scenario_name": "ingest-max-context", "concurrency": 32, "total_requests": 839, "successful_requests": 0, "failed_requests": 839}
```

Same pattern in `configA-32k-1gpu` and `configA-32k-2node-forced` — **0 successful requests** across **1,914+1,914+1,902 = 5,730 total failed requests**.

#### Root Cause

The `ingest-max-context` scenario in `workload_profiles.py` (line 269-282) sends:
- `batch_size = 16` texts per request
- `target_tokens_per_text = 32,768` tokens per text
- **Total tokens per request = 16 × 32,768 = 524,288 tokens**

But the vLLM server is configured with:
- `--max-num-batched-tokens 65,536` (from README line 230)
- `--max-model-len 32,768` (from Dockerfile line 95)

A single request sending 524,288 tokens is **8× larger** than what vLLM allows in a single batch (65,536). vLLM rejects these requests immediately.

Even if `max_num_batched_tokens` were removed, a single request with 16 texts of 32k tokens each would require processing 524,288 tokens simultaneously — far exceeding GPU memory capacity.

#### What the Results Look Like

```
scenario,concurrency,tokens_per_sec,tokens_per_min,requests_per_min,...,error_rate,all_under_20s
ingest-max-context,1,0.0,0.0,0.0,...,0.0000,True    # ← All zeros, error_rate=0.0 (BUG!)
ingest-max-context,4,0.0,0.0,0.0,...,0.0000,True     # ← Same
ingest-max-context,16,0.0,0.0,0.0,...,0.0000,True    # ← Same
ingest-max-context,32,0.0,0.0,0.0,...,0.0000,True    # ← Same
```

Note the `error_rate=0.0` despite 100% failures — this is the H3 bug (see below).

#### Impact

- **Customer trust**: If Elastic reviews the results, they'll see half the tests produced zero data
- **Missing deliverable**: The 32k max-context throughput data was a specific ask from the scoping call (Akbar and Dimitris discussed users who send full 32k documents)
- **Wasted benchmark time**: Each concurrency level ran for 70 seconds of failures

#### Required Fix

**Option A (Recommended): Reduce batch_size for max-context**
```python
BenchmarkScenario(
    name="ingest-max-context",
    batch_size=1,  # Changed from 16 to 1
    target_tokens_per_text=32768,
    # Now tokens_per_request = 1 × 32,768 = 32,768 (fits within max_num_batched_tokens)
    concurrency_levels=[1, 4, 16, 32],
    ...
)
```

**Option B: Increase max_num_batched_tokens**
```
# In Dockerfile CMD or gcloud deploy args:
--max-num-batched-tokens 1048576  # 1M tokens (16 × 32k × 2 for safety)
```
But this may cause OOM on the GPU.

**Option C: Remove the scenario**
If max-context testing is out of scope, remove it from the benchmark and document why.

---

## 🟠 HIGH ISSUES (5 Total)

These won't crash the code but produce incorrect output or undermine credibility.

---

### 🟠 H1: VRAM specification inconsistency — 48GB vs 96GB

**Severity:** HIGH — Undermines technical credibility  
**Affected Files:** `README.md`, `deploy/config.yaml`, `deploy/Dockerfile`, `analysis/pricing_data.yaml`  
**Type:** Inconsistent data

#### What's Wrong

The repository contradicts itself on how much VRAM the RTX Pro 6000 GPU has:

| File | Location | VRAM Claim |
|------|----------|-----------|
| `README.md` | Line 3 | "NVIDIA RTX Pro 6000 **(96GB VRAM)**" |
| `README.md` | Line 10 | "NVIDIA RTX Pro 6000 **(96GB VRAM)**" |
| `README.md` | Line 83 | "NVIDIA RTX Pro 6000 **(96GB VRAM)**" |
| `README.md` | Line 228 | "Use **91.2GB of 96GB** for batching" |
| `config.yaml` | Line 18 | `vram_gb: **96**` |
| `Dockerfile` | Line 17 | "single RTX Pro 6000 **(48GB VRAM)**" |
| `pricing_data.yaml` | Line 56 | "RTX Pro 6000 has **48GB** VRAM (2× L4's 24GB)" |
| `pricing_data.yaml` | Line 65 | `gpu_memory_gb: **48**` |

#### Context

- **NVIDIA RTX Pro 6000 (Blackwell, 2025+):** 96GB GDDR7 — this is the newer GPU
- **NVIDIA RTX 6000 Ada (Lovelace, 2023):** 48GB GDDR6 — this is the older GPU
- GCP's G4 instances use the Blackwell-era RTX Pro 6000

The Dockerfile comment and pricing_data.yaml appear to have been written with the older RTX 6000 Ada specs in mind, while the README was updated with the correct Blackwell specs.

#### Impact

- If customer copies the `--gpu-memory-utilization 0.95` setting and the GPU actually has 48GB, the calculation "91.2GB of 96GB" is wrong
- The pricing comparison logic in `pricing_data.yaml` says "48GB VRAM (2× L4's 24GB)" — this is wrong if it's actually 96GB (which would be 4× L4's 24GB)

#### Required Fix

1. **Verify** the actual VRAM by running `nvidia-smi` on a deployed G4 instance or checking the GCP console
2. Update ALL files to use the correct number consistently
3. If 96GB: Fix Dockerfile line 17 and pricing_data.yaml lines 56, 65
4. If 48GB: Fix README lines 3, 10, 83, 228 and config.yaml line 18

---

### 🟠 H2: Missing files referenced in README

**Severity:** HIGH — Broken documentation  
**Affected Files:** `README.md`  
**Type:** Missing files

#### What's Wrong

The README's Repository Structure tree (lines 209-215) lists these files:

```
results/
├── benchmark_configA-8192_*.json          # ✅ EXISTS
├── benchmark_configA-32k-1gpu_*.json      # ✅ EXISTS
├── benchmark_configA-32k-2node-forced_*.json  # ✅ EXISTS
├── raw_1gpu_terminal_output.log           # ❌ DOES NOT EXIST
├── raw_1gpu_32k_terminal_output.log       # ❌ DOES NOT EXIST
└── raw_2node_forced_terminal_output.log   # ❌ DOES NOT EXIST
```

Verified with `ls -la results/raw_*` → "No such file or directory"

#### Additional Missing Reference

The README structure tree for `deploy/` (lines 202-204):
```
deploy/
├── Dockerfile                # ✅ EXISTS
├── config.yaml               # ✅ EXISTS
└── cleanup_vertex.py         # ✅ EXISTS
```

**`deploy_vertex.py` is not listed** — but it exists and is a major file (289 lines).

#### Required Fix

Either:
- Add the 3 missing log files to the repo (they may have been in the git history but not committed)
- Remove references to non-existent files from the README tree
- Add `deploy_vertex.py` to the tree

---

### 🟠 H3: `error_rate` and `all_under_20s` bug when all requests fail

**Severity:** HIGH — Misleading metrics  
**Affected Files:** `benchmark/load_generator.py`  
**Type:** Logic bug

#### What's Wrong

In `load_generator.py`, the `compute_aggregates()` method at line 132-171:

```python
def compute_aggregates(self) -> None:
    self.total_requests = len(self.requests)
    successful = [r for r in self.requests if r.is_success]
    self.successful_requests = len(successful)
    self.failed_requests = self.total_requests - self.successful_requests

    if not successful:
        return  # ← EXITS HERE when 0 successful requests
    
    # ... error_rate and all_under_20s calculations happen AFTER this return
    # They never execute, so they keep their default values:
    # error_rate = 0.0 (wrong! should be 1.0)
    # all_under_20s = True (meaningless! all requests failed)
```

#### Proof from Result Data

Every `ingest-max-context` entry in the JSON results shows this bug:

```json
{
    "scenario_name": "ingest-max-context",
    "concurrency": 1,
    "total_requests": 58,
    "successful_requests": 0,
    "failed_requests": 58,     // ← 58 failed
    "error_rate": 0.0,         // ← BUG: says 0% errors but ALL 58 failed
    "all_under_20s": true      // ← BUG: says all under 20s but none succeeded
}
```

This pattern repeats for ALL `ingest-max-context` tests across all 3 result files (12 entries total, all showing `error_rate: 0.0` despite 100% failure).

#### Required Fix

```python
def compute_aggregates(self) -> None:
    self.total_requests = len(self.requests)
    successful = [r for r in self.requests if r.is_success]
    self.successful_requests = len(successful)
    self.failed_requests = self.total_requests - self.successful_requests
    
    # Calculate error_rate BEFORE the early return
    self.error_rate = self.failed_requests / self.total_requests if self.total_requests > 0 else 0.0
    
    if not successful:
        self.all_under_20s = False  # No successful requests = can't claim all under 20s
        return
    
    # ... rest of the method for successful requests
    self.all_under_20s = all(r.latency_ms < 20000 for r in successful)
```

---

### 🟠 H4: Unused Python dependencies in requirements.txt

**Severity:** HIGH — Confusion for customer, unnecessary installs  
**Affected Files:** `requirements.txt`  
**Type:** Unused code

#### What's Wrong

`requirements.txt` lists 7 dependencies. 3 of them are **never imported** in any Python file:

| Dependency | Used in Code? | Verification |
|------------|--------------|-------------|
| `google-cloud-aiplatform>=1.60.0` | ✅ Yes | `deploy/deploy_vertex.py`, `deploy/cleanup_vertex.py` |
| `aiohttp>=3.9.0` | ✅ Yes | `benchmark/load_generator.py`, `benchmark/run_benchmark.py` |
| `pyyaml>=6.0` | ✅ Yes | Multiple files import `yaml` |
| `numpy>=1.24.0` | ✅ Yes | `benchmark/load_generator.py` |
| `pandas>=2.0.0` | ❌ **NEVER** | `grep -rn "pandas" benchmark/ analysis/` returns empty |
| `tabulate>=0.9.0` | ❌ **NEVER** | `grep -rn "tabulate" benchmark/ analysis/` returns empty |
| `tqdm>=4.65.0` | ❌ **NEVER** | `grep -rn "tqdm" benchmark/ analysis/` returns empty |

#### Impact

- `pandas` is a large package (~50MB) — unnecessary to install for this benchmark
- Customer may wonder why these are required if they look at the code
- Creates confusion about whether there's missing code that uses these libraries

#### Required Fix

Remove the 3 unused dependencies from `requirements.txt`:

```diff
- # Data analysis and tabulation for benchmark results
- pandas>=2.0.0
- tabulate>=0.9.0
- 
- # Progress bars for long-running benchmark scenarios
- tqdm>=4.65.0
```

---

### 🟠 H5: vLLM version hardcoded as v0.15.1 in report generator

**Severity:** HIGH — Generated reports will show wrong version  
**Affected Files:** `analysis/generate_report.py`, `deploy/Dockerfile` (comment)  
**Type:** Stale data / wrong version

#### What's Wrong

**File 1: `analysis/generate_report.py` (line 372):**
```python
lines.append(f"**Serving Framework**: vLLM v0.15.1\n")
```
This is the old version. The actual version used is **v0.20.1** (per Dockerfile base image and README).

The generated `BENCHMARK_REPORT.md` will tell the customer:
> **Serving Framework**: vLLM v0.15.1

Which is wrong and contradicts every other reference in the repo.

**File 2: `deploy/Dockerfile` (line 13-14):**
```dockerfile
# 4. It's the framework commonly used for serving (vLLM v0.15.1)
```
This comment references the old version. The actual base image on line 29 is correct: `FROM vllm/vllm-openai:v0.20.1`

#### Context

The POC doc originally specified vLLM v0.15.1. The README Issues table documents why it was upgraded:
```
| vLLM v0.15.1 crash | `JinaEmbeddingsV5Model` not supported | Upgraded to vLLM v0.20.1 |
```

The version was updated in the Dockerfile base image and README, but these two references were missed.

#### Required Fix

```python
# generate_report.py line 372
lines.append(f"**Serving Framework**: vLLM v0.20.1\n")
```

```dockerfile
# Dockerfile line 13-14
# 4. It's the framework commonly used for serving (vLLM v0.20.1)
```

---

## 🟡 MEDIUM ISSUES (4 Total)

Missing deliverables or minor functional issues.

---

### 🟡 M1: No search workload scenario

**Severity:** MEDIUM — Missing customer deliverable  
**Affected Files:** `benchmark/workload_profiles.py`  
**Type:** Missing feature

#### What the Customer Asked For

From the scoping call and POC doc:

**POC Doc — Two deployment types:**
> Search: Latency: < 50ms / Peak traffic: 2k RPM  
> Ingest: Throughput: capped at 6M tokens/minute per user / Peak traffic: 6k RPM

**Dimitris (scoping call):**
> "I would also like to leave knowing what I should do if I want latency for another model."

**Max (scoping call):**
> "For the online case they do run on separate endpoints... we can play with those parameters separately"

#### What the Benchmark Has

Only ingestion scenarios:
- `ingest-default-chunk` (batch_size=16, 512 tokens/text)
- `ingest-max-context` (batch_size=16, 32768 tokens/text — broken anyway)

**No search/latency scenario exists.**

#### Impact

The customer explicitly said search is Priority 2 but "valuable to know." Having zero search data means they get no guidance on:
- Single-query latency under load
- Whether the 50ms p50 target is achievable
- What concurrency settings to use for search vs ingest

#### Recommended Fix

Add a third scenario in `workload_profiles.py`:

```python
BenchmarkScenario(
    name="search-single-query",
    description=(
        "Online search workload — single query at a time. "
        "1 text × ~512 tokens = ~512 tokens/request. "
        "Latency-sensitive: target < 50ms p50. "
        "Tests the real-time search use case."
    ),
    batch_size=1,
    target_tokens_per_text=512,
    concurrency_levels=[1, 2, 4, 8, 16],
    duration_seconds=60,
    warmup_seconds=10,
),
```

---

### 🟡 M2: No L4 baseline comparison — Missing the G2 vs G4 shootout

**Severity:** MEDIUM — Missing customer deliverable  
**Affected Files:** N/A (no L4 benchmark results exist)  
**Type:** Missing data

#### What the Customer Asked For

From the POC doc:
> **3. Hardware Evaluation: G2 vs. G4**  
> A core component of this POC is a direct price-to-performance shootout between two GPU types:  
> L4 (G2 instances): Their current baseline.  
> RTX Pro 6000 (G4 instances): Elastic noted that the Jina team previously saw better price/performance with the RTX 6000 on Jina V3.

#### What the Benchmark Has

- G4 (RTX Pro 6000) results: ✅ Yes, 3 result files
- G2 (L4) results: ❌ None

The `pricing_data.yaml` includes L4 pricing for reference, but without actual L4 benchmark throughput numbers, no comparison is possible.

#### Impact

The customer cannot answer: "Is RTX Pro 6000 better $/tok than our current L4 setup?"

#### Recommended Fix

**Option A:** Run the same benchmark on a `g2-standard-8` with 1× L4 GPU and add results  
**Option B:** Use Elastic's existing Cloud Run L4 throughput data to estimate L4 $/M-tokens  
**Option C:** Document in the report that L4 testing was deferred and provide the pricing framework so they can plug in L4 numbers later

---

### 🟡 M3: deploy_vertex.py prints wrong test curl endpoint

**Severity:** MEDIUM — Confusing for users  
**Affected Files:** `deploy/deploy_vertex.py`  
**Type:** Bug

#### What's Wrong

After successful deployment, `deploy_vertex.py` prints a test curl command (line 226-228):

```python
print(f"     https://{config['gcp']['region']}-aiplatform.googleapis.com/v1/{endpoint.resource_name}:predict")
```

This uses `:predict` but the entire benchmark uses `:rawPredict`. 

The difference:
- `:predict` — Vertex AI wraps the request/response in its own format
- `:rawPredict` — Passes the request directly to the container as-is

If a user copies this curl command, they'll get a Vertex AI-wrapped response format that looks different from what the benchmark produces. They may think the endpoint is broken.

#### Required Fix

```python
print(f"     https://{config['gcp']['region']}-aiplatform.googleapis.com/v1/{endpoint.resource_name}:rawPredict")
```

---

### 🟡 M4: README Quick Start missing cleanup step

**Severity:** MEDIUM — Cost risk for customer  
**Affected Files:** `README.md`  
**Type:** Missing documentation

#### What's Wrong

The README Quick Start has 4 steps:
1. Build and Push Container ✅
2. Upload Model to Vertex AI ✅
3. Create Endpoint and Deploy ✅
4. Run the Benchmark ✅
5. **Clean up** ❌ MISSING

The `cleanup_vertex.py` script exists and is well-implemented with a dry-run mode. The `run_benchmark.py` output even mentions cleanup as a next step. But the README doesn't include it in the Quick Start flow.

#### Impact

A single G4 instance with RTX Pro 6000 costs ~$2-4/hour. If a customer runs the benchmark and forgets to clean up, they're paying for an idle GPU endpoint 24/7.

#### Required Fix

Add Step 5 to the Quick Start:

```markdown
### Step 5: Clean Up Resources

**Important:** Deployed endpoints incur GPU costs even when idle.

```bash
# Option A: Use the cleanup script
python deploy/cleanup_vertex.py --config deploy/config.yaml --dry-run  # Preview
python deploy/cleanup_vertex.py --config deploy/config.yaml            # Actually delete

# Option B: Use gcloud CLI
gcloud ai endpoints undeploy-model $ENDPOINT_ID \
  --region=YOUR_REGION --project=YOUR_PROJECT_ID \
  --deployed-model-id=$(gcloud ai endpoints describe $ENDPOINT_ID --region=YOUR_REGION --format="value(deployedModels[0].id)")

gcloud ai endpoints delete $ENDPOINT_ID --region=YOUR_REGION --project=YOUR_PROJECT_ID
```
```

---

## 🟢 LOW ISSUES (3 Total)

Minor/cosmetic issues that don't affect functionality.

---

### 🟢 L1: Three result files — unclear which is "canonical"

**Severity:** LOW  
**Affected Files:** `results/` directory, `README.md`  
**Type:** Documentation clarity

#### What's Wrong

The repo has 3 result file pairs:

| File | Config | GPU | max-model-len | Date |
|------|--------|-----|---------------|------|
| `configA-8192` | 1-GPU | RTX Pro 6000 | 8192 | May 8, 10:33 |
| `configA-32k-1gpu` | 1-GPU | RTX Pro 6000 | 32768 | May 8, 11:18 |
| `configA-32k-2node-forced` | 2-node | RTX Pro 6000 | 32768 | May 10, 22:38 |

The first two are both 1-GPU tests on the same day, ~45 minutes apart. They differ only in `max-model-len` (8192 vs 32768). For the `ingest-default-chunk` scenario (which only uses ~8k tokens/request), the results are nearly identical (within 2.6%).

The README uses `configA-8192` numbers for the 1-GPU results table but doesn't explain why there are two 1-GPU result files or which is canonical.

#### Recommended Fix

Add a note in the README or results directory explaining:
- `configA-8192`: Early test with `max-model-len=8192` (model couldn't accept 32k context)
- `configA-32k-1gpu`: Final 1-GPU test with `max-model-len=32768` (correct configuration)
- `configA-32k-2node-forced`: 2-node scaling test

---

### 🟢 L2: 2-node test labeling confusion

**Severity:** LOW  
**Affected Files:** `deploy/deploy_vertex.py`, `README.md`  
**Type:** Documentation clarity

#### What's Wrong

The "2-GPU" test is actually **2 separate G4 nodes** with 1 GPU each, load-balanced by Vertex AI (min-replica-count=2). This is correctly described in the README (line 41: "2 G4 nodes, Vertex AI load-balanced").

However, `deploy_vertex.py` uses `--gpu-count 2` which implies tensor parallelism on a single node with 2 GPUs. The `get_hardware_config()` function returns `config["hardware"]["dual_gpu"]` which could be misread as 2 GPUs in 1 machine.

The actual deployment in the README Quick Start (lines 159-169) is clearer:
```bash
--accelerator=type=nvidia-rtx-pro-6000,count=1  # 1 GPU per node
--min-replica-count=2                             # 2 nodes
--max-replica-count=2
```

This distinction matters because:
- 2 GPUs on 1 node = tensor parallelism, shared memory, no network overhead
- 2 separate nodes = load balancing, independent GPUs, network overhead

---

### 🟢 L3: deploy_vertex.py not in README structure tree

**Severity:** LOW  
**Affected Files:** `README.md`  
**Type:** Missing documentation

The README repository structure (lines 200-204) shows:
```
├── deploy/
│   ├── Dockerfile
│   ├── config.yaml
│   └── cleanup_vertex.py
```

Missing: `deploy_vertex.py` (289 lines, the deployment script)

Add it:
```
├── deploy/
│   ├── Dockerfile
│   ├── config.yaml
│   ├── deploy_vertex.py          # Vertex AI model upload & deployment
│   └── cleanup_vertex.py
```

---

## Summary Matrix — All 16 Issues

| # | Severity | Issue | File(s) | Type | Can Crash? |
|---|----------|-------|---------|------|-----------|
| C1 | 🔴 CRITICAL | config.yaml missing 20+ keys | config.yaml + all .py | Missing code | ✅ YES |
| C2 | 🔴 CRITICAL | G4 pricing is fabricated | pricing_data.yaml | Fabricated data | No |
| C3 | 🔴 CRITICAL | `--task embed` contradiction | Dockerfile, deploy_vertex.py, README | Contradiction | Maybe |
| C4 | 🔴 CRITICAL | max-context 100% failure | workload_profiles.py, results/ | Design flaw | No |
| H1 | 🟠 HIGH | VRAM 48GB vs 96GB | README, config, Dockerfile, pricing | Inconsistency | No |
| H2 | 🟠 HIGH | 3 missing log files | README | Missing files | No |
| H3 | 🟠 HIGH | error_rate bug (0% on 100% failure) | load_generator.py | Logic bug | No |
| H4 | 🟠 HIGH | 3 unused pip dependencies | requirements.txt | Unused code | No |
| H5 | 🟠 HIGH | vLLM v0.15.1 hardcoded | generate_report.py, Dockerfile | Wrong version | No |
| M1 | 🟡 MEDIUM | No search workload scenario | workload_profiles.py | Missing feature | No |
| M2 | 🟡 MEDIUM | No L4 baseline comparison | N/A | Missing data | No |
| M3 | 🟡 MEDIUM | Wrong `:predict` in curl output | deploy_vertex.py | Bug | No |
| M4 | 🟡 MEDIUM | No cleanup step in Quick Start | README | Missing docs | No |
| L1 | 🟢 LOW | 3 result files, unclear canonical | results/ | Clarity | No |
| L2 | 🟢 LOW | 2-node vs 2-GPU labeling | deploy_vertex.py | Clarity | No |
| L3 | 🟢 LOW | deploy_vertex.py not in tree | README | Missing docs | No |
