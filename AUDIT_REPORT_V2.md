# 🔍 Audit Report V2: Post-Fix Re-Investigation

**Repository:** https://github.com/MG-Cafe/embedding-benchmark  
**Commit:** `8b651bf` — "Fix all audit issues"  
**Audit Date:** 2026-05-11  
**Method:** Multi-agent deep dive + programmatic config verification

---

## Fix Verification: Original 16 Issues

### ✅ FIXED (9 of 16 original issues resolved)

| # | Original Issue | Status | Evidence |
|---|---------------|--------|----------|
| C1 | config.yaml missing 20+ keys | ✅ **FIXED** | All 32 config keys verified programmatically — `ALL CONFIG KEYS PRESENT ✅` |
| C3 | `--task embed` contradiction | ✅ **FIXED** | Removed from Dockerfile (line 91-97 no longer has `--task`), removed from deploy_vertex.py (line 95-101), README Issues table consistent |
| C4 | max-context 100% failure (batch_size=16) | ✅ **FIXED** | workload_profiles.py line 282: `batch_size=bench_config.get("batch_size_max_context", 1)`, config has `batch_size_max_context: 1`, so 1×32768=32768 fits within max_num_batched_tokens=65536 |
| H1 | VRAM 48GB vs 96GB inconsistency | ✅ **FIXED** | README (lines 3,10,83,226), config.yaml, Dockerfile (line 17), pricing_data.yaml (line 65) — ALL now say 96GB consistently |
| H2 | Missing log files in README tree | ✅ **FIXED** | README structure tree (lines 209-213) no longer references raw_*_terminal_output.log files. deploy_vertex.py now listed (line 203) |
| H3 | error_rate bug (0% on 100% failure) | ✅ **FIXED** | load_generator.py lines 145-149: early return now sets `error_rate = 1.0` and `all_under_20s = False` |
| H4 | Unused pip dependencies | ✅ **FIXED** | requirements.txt reduced to 4 deps: google-cloud-aiplatform, aiohttp, pyyaml, numpy. pandas/tabulate/tqdm removed |
| H5 | vLLM v0.15.1 hardcoded | ✅ **FIXED** | generate_report.py line 372: `vLLM v0.20.1`. Dockerfile line 13: `vLLM v0.20.1` |
| L3 | deploy_vertex.py not in README tree | ✅ **FIXED** | README line 203: `deploy_vertex.py` now listed |

---

### ⚠️ PARTIALLY FIXED (2 of 16)

| # | Original Issue | Status | What's Left |
|---|---------------|--------|-------------|
| C2 | G4 pricing fabricated | ⚠️ **PARTIAL** | Machine types fixed to `g4-standard-48` ✅, VRAM fixed to 96GB ✅, BUT prices ($3.054/hr) still have `# TODO: Verify pricing from GCP console` comments — prices are still unverified estimates |
| L2 | 2-node vs 2-GPU labeling | ⚠️ **PARTIAL** | README correctly documents "2 G4 nodes, Vertex AI load-balanced" ✅, BUT config.yaml `dual_gpu` section now has `accelerator_count: 2, tensor_parallel_size: 2` which describes a DIFFERENT architecture (see NEW issue below) |

---

### ❌ NOT FIXED (5 of 16)

| # | Original Issue | Status | Details |
|---|---------------|--------|---------|
| M1 | No search workload scenario | ❌ **NOT FIXED** | Still only ingest-default-chunk and ingest-max-context. No search-latency scenario |
| M2 | No L4 baseline comparison | ❌ **NOT FIXED** | Still no L4 benchmark results. G2-vs-G4 shootout not possible |
| M3 | deploy_vertex.py `:predict` vs `:rawPredict` | ❌ **NOT FIXED** | Line 227 still uses `:predict`. Benchmark uses `:rawPredict` |
| M4 | No cleanup step in README | ❌ **NOT FIXED** | README Quick Start still has only Steps 1-4, no Step 5 for cleanup |
| L1 | Three result files unclear canonical | ❌ **NOT FIXED** | No documentation explaining which result file maps to which table |

---

## 🆕 NEW Issues Found in V2 Investigation

### 🔴 NEW-1: CRITICAL — Dockerfile and deploy_vertex.py missing 6 essential vLLM flags

**Severity:** CRITICAL — Container deployed via Dockerfile or deploy_vertex.py will behave differently than what was benchmarked  
**Files:** `deploy/Dockerfile` (lines 91-97), `deploy/deploy_vertex.py` (lines 94-101)

The README documents these as required vLLM parameters (line 127 gcloud CLI, lines 220-229 table). These are the flags that were actually used during benchmarking. But NEITHER the Dockerfile nor deploy_vertex.py includes them:

| Flag | In README gcloud CLI | In Dockerfile CMD | In deploy_vertex.py | Impact if Missing |
|------|---------------------|-------------------|---------------------|-------------------|
| `--trust-remote-code` | ✅ | ❌ **MISSING** | ❌ **MISSING** | **MODEL LOAD FAILS** — Jina V5 uses custom HF code |
| `--max-num-seqs 512` | ✅ | ❌ **MISSING** | ❌ **MISSING** | Default=256 — different batching behavior |
| `--gpu-memory-utilization 0.95` | ✅ | ❌ **MISSING** | ❌ **MISSING** | Default=0.9 — less memory for batching |
| `--enforce-eager` | ✅ | ❌ **MISSING** | ❌ **MISSING** | CUDA graphs enabled — different performance profile |
| `--max-num-batched-tokens 65536` | ✅ | ❌ **MISSING** | ❌ **MISSING** | Default varies — different throughput |
| `--disable-log-stats` | ✅ | ❌ has `--disable-log-requests` | ❌ has `--disable-log-requests` | Different flag — `--disable-log-stats` suppresses periodic stats, `--disable-log-requests` suppresses per-request logs |

**The most critical missing flag is `--trust-remote-code`**. Without it, vLLM will refuse to load the Jina V5 model because it uses custom Python code from HuggingFace. The container will fail to start.

**Current Dockerfile CMD (lines 91-97):**
```dockerfile
CMD ["--model", "jinaai/jina-embeddings-v5-text-small", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--max-model-len", "32768", \
     "--dtype", "bfloat16", \
     "--tensor-parallel-size", "1", \
     "--disable-log-requests"]
```

**Should be:**
```dockerfile
CMD ["--model", "jinaai/jina-embeddings-v5-text-small", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--max-model-len", "32768", \
     "--dtype", "bfloat16", \
     "--tensor-parallel-size", "1", \
     "--trust-remote-code", \
     "--max-num-seqs", "512", \
     "--gpu-memory-utilization", "0.95", \
     "--enforce-eager", \
     "--max-num-batched-tokens", "65536", \
     "--disable-log-requests", \
     "--disable-log-stats"]
```

**Same fix needed for deploy_vertex.py `build_container_args()` (lines 94-101).**

---

### 🟠 NEW-2: HIGH — dual_gpu config describes wrong architecture (2 GPUs on 1 node vs 2 separate nodes)

**Severity:** HIGH — deploy_vertex.py with `--gpu-count 2` will create a fundamentally different deployment than what was benchmarked  
**Files:** `deploy/config.yaml` (lines 50-55), `deploy/deploy_vertex.py`, `README.md` (lines 159-169)

**What the benchmark actually tested:**
- 2 separate `g4-standard-48` nodes, each with 1× RTX Pro 6000
- Vertex AI load-balances between them (`min-replica-count=2`)
- Each node runs the model independently (tensor_parallel_size=1)
- README correctly shows this at lines 159-169

**What config.yaml says (lines 50-55):**
```yaml
dual_gpu:
    machine_type: "g4-standard-48"
    accelerator_type: "NVIDIA_RTX_PRO_6000"
    accelerator_count: 2          # ← 2 GPUs on ONE node
    tensor_parallel_size: 2       # ← Split model across 2 GPUs
    display_name_suffix: "2gpu"
```

**What deploy_vertex.py would actually deploy:**
- 1 node with 2× RTX Pro 6000 GPUs
- Model split via tensor parallelism (tensor_parallel_size=2)
- This is fundamentally different — tensor parallelism has GPU-to-GPU communication overhead
- The benchmark results showing "perfect 2× scaling" are from load-balanced independent nodes, NOT tensor parallelism

**Impact:** If someone uses `python deploy_vertex.py --config config.yaml --gpu-count 2`, they'll get a different architecture than what was benchmarked. The results won't match.

**Fix:** Either:
1. Change config to match what was actually benchmarked:
   ```yaml
   dual_gpu:
       machine_type: "g4-standard-48"
       accelerator_type: "NVIDIA_RTX_PRO_6000"
       accelerator_count: 1          # 1 GPU per node
       tensor_parallel_size: 1       # No tensor parallelism
       display_name_suffix: "2node"
   ```
   And modify deploy_vertex.py to set `min_replica_count=2` for the dual config.

2. OR document that `--gpu-count 2` in deploy_vertex.py does tensor parallelism, which is different from the 2-node benchmark.

---

### 🟡 NEW-3: MEDIUM — Old result files contain buggy metrics (error_rate=0.0 on 100% failure)

**Severity:** MEDIUM — Misleading data in checked-in files  
**Files:** All 6 files in `results/`

The code fix for error_rate is correct (H3 ✅), but the existing result files were not regenerated. The `ingest-max-context` entries in all JSON and CSV files still show:
- `error_rate: 0.0` (should be `1.0`)
- `all_under_20s: true` (should be `false`)

This affects 12 result entries across 3 JSON files and 3 CSV files.

Since these files are historical benchmark results, they arguably shouldn't be regenerated (you can't re-run old benchmarks). But a note should be added explaining the discrepancy, or the files should be patched to show the correct error_rate/all_under_20s values.

---

### 🟡 NEW-4: MEDIUM — pricing_data.yaml dual_gpu architecture mismatch

**Severity:** MEDIUM — Cost calculations will be wrong if architecture changes  
**Files:** `analysis/pricing_data.yaml` (lines 76-83)

```yaml
# g4-standard-48 with 2× RTX Pro 6000
dual_gpu:
    machine_type: "g4-standard-48"
    accelerator_count: 2
```

This describes 1 node with 2 GPUs. But the actual benchmark used 2 separate nodes (2 × g4-standard-48 with 1 GPU each). The cost is coincidentally the same ($6.108 = 2 × $3.054), but the architecture description is wrong.

If the pricing for a g4-standard-48 with 2 GPUs is different from 2 × g4-standard-48 with 1 GPU (which it likely is — more GPUs per node may have different pricing), then the cost calculation would be incorrect.

---

## Updated Summary Matrix — All Remaining Issues

| # | Severity | Issue | Status | Type |
|---|----------|-------|--------|------|
| **NEW-1** | 🔴 **CRITICAL** | Dockerfile + deploy_vertex.py missing 6 essential vLLM flags (--trust-remote-code will cause model load failure) | NEW | Missing code |
| **NEW-2** | 🟠 **HIGH** | dual_gpu config = 2 GPUs/1 node, but benchmark = 2 nodes/1 GPU each | NEW | Architecture mismatch |
| C2 (partial) | 🟠 **HIGH** | G4 pricing still unverified (TODO comments remain) | PARTIAL | Unverified data |
| M3 | 🟡 **MEDIUM** | deploy_vertex.py `:predict` vs `:rawPredict` | NOT FIXED | Bug |
| M4 | 🟡 **MEDIUM** | No cleanup step in README | NOT FIXED | Missing docs |
| **NEW-3** | 🟡 **MEDIUM** | Old result files have buggy error_rate=0.0 on 100% failures | NEW | Stale data |
| **NEW-4** | 🟡 **MEDIUM** | pricing_data dual_gpu architecture mismatch (1 node vs 2 nodes) | NEW | Wrong architecture |
| M1 | 🟡 **MEDIUM** | No search workload scenario | NOT FIXED | Missing feature |
| M2 | 🟡 **MEDIUM** | No L4 baseline comparison | NOT FIXED | Missing data |
| L1 | 🟢 **LOW** | Three result files unclear canonical | NOT FIXED | Clarity |

---

## Priority Action Items

### Must Fix Before Sharing (Blocking):

1. **Add missing vLLM flags to Dockerfile CMD and deploy_vertex.py** (NEW-1)
   - Especially `--trust-remote-code` — without it the container WILL NOT START
   - Also: `--max-num-seqs 512`, `--gpu-memory-utilization 0.95`, `--enforce-eager`, `--max-num-batched-tokens 65536`, `--disable-log-stats`

2. **Fix dual_gpu config architecture** (NEW-2)
   - Change `accelerator_count: 1` and `tensor_parallel_size: 1` in dual_gpu
   - Have deploy_vertex.py set `min_replica_count=2` for the 2-node scaling test
   - OR document clearly that deploy_vertex.py `--gpu-count 2` does something different from the benchmark

3. **Fix `:predict` → `:rawPredict`** in deploy_vertex.py line 227 (M3)

### Should Fix:

4. **Verify G4 pricing** from GCP console and remove TODO comments (C2)
5. **Add cleanup Step 5** to README Quick Start (M4)
6. **Fix pricing_data.yaml dual_gpu** to reflect 2-node architecture (NEW-4)
7. **Add note or patch** old result files re: error_rate bug (NEW-3)

### Nice to Have:

8. Add search-latency scenario (M1)
9. Add L4 baseline benchmark (M2)
10. Document which result file is canonical (L1)

---

## What's Good — Confirmed Working

| Area | Verdict |
|------|---------|
| **Config completeness** | ✅ All 32 config keys present and verified |
| **--task embed removed** | ✅ Correctly removed from Dockerfile and deploy_vertex.py |
| **error_rate bug fixed in code** | ✅ compute_aggregates() now correctly handles 100% failure |
| **max-context batch_size reduced** | ✅ Now uses batch_size=1 for 32k context (fits within limits) |
| **VRAM consistent** | ✅ All files say 96GB |
| **vLLM version consistent** | ✅ All references now say v0.20.1 |
| **Unused deps removed** | ✅ Only 4 needed packages in requirements.txt |
| **README structure tree** | ✅ Accurate, includes deploy_vertex.py, no phantom files |
| **Benchmark results integrity** | ✅ All README numbers match JSON data exactly |
| **Vertex AI API usage** | ✅ SDK calls, rawPredict URLs, ADC auth all correct |
| **Cost calculation math** | ✅ Formula, percentiles, capacity planning all correct |
| **Async load generator** | ✅ Sound architecture, proper warmup, metrics collection |
