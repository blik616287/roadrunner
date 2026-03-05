# Production Baseline: Qwen3-30B-A3B Q4_K_M (Pre-Tuning)

- **Model**: Qwen3-30B-A3B-Instruct-2507
- **GGUF**: `unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF` → `Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf`
- **Quant**: Q4_K_M (~18.5 GiB loaded)
- **Architecture**: MoE (30.5B total, 3.3B active per token)
- **Backend**: vLLM (--dtype half, --max-num-seqs 8, --gpu-memory-utilization 0.30)
- **Embedding**: Qwen3-Embedding-0.6B via vLLM (dedicated mode, 1024-dim)
- **Reranker**: BGE-reranker-v2-m3 via vLLM
- **GPU sharing**: NVIDIA MPS (3 slices: extract, embed, rerank)
- **Platform**: DGX Spark (ARM64, GB10 SM121, 128GB unified memory)
- **Chat template**: `qwen3-no-think.jinja` (no `<think>` block injection)
- **Workspace**: `default-30b-test`
- **Test corpus**: `apps/` directory (71 files, 70 processed)
- **Date**: 2026-03-04
- **Pipeline patches**: CODE_EXTRACTION_PROMPT=1, LLM_MAX_TOKENS=2048, TYPED_RELATIONSHIPS=1, PIPELINED_EMBEDDING=1
- **MAX_ASYNC**: 8, **MAX_PARALLEL_INSERT**: 4, **LLM_TIMEOUT**: 600

---

## Extraction Quality

| Metric | Value |
|---|---|
| Total nodes | 322 |
| Total relationships | 440 |
| Cross-file relationships | 302 |
| Orphan nodes | 15 (4.7%) |
| UNKNOWN entities | 29 (9.0%) |

### Top Relationship Types

| Type | Count | % of Total |
|---|---|---|
| IMPORTS | 81 | 18.4% |
| USES | 75 | 17.0% |
| CALLS | 52 | 11.8% |
| CONTAINS | 50 | 11.4% |
| DEPENDS_ON | 38 | 8.6% |
| DEFINES | 30 | 6.8% |
| RENDERS | 12 | 2.7% |
| EXTENDS | 10 | 2.3% |
| RETURNS | 7 | 1.6% |
| ROUTES_TO | 6 | 1.4% |
| Other (33 types) | 79 | 18.0% |
| **Total unique types** | **43** | |

### Relationship Distribution Analysis

- **Code structure** (IMPORTS, CONTAINS, DEFINES, EXTENDS): 171 (38.9%) — captures module hierarchy
- **Runtime behavior** (CALLS, USES, DEPENDS_ON, RETURNS): 172 (39.1%) — traces execution paths
- **Domain-specific** (RENDERS, ROUTES_TO, SUBSCRIBES_TO, EXPOSES): 25 (5.7%) — captures React, API, and event patterns
- **Long tail** (33 additional types with 1-5 occurrences): 72 (16.4%) — high semantic diversity

---

## Runtime Performance

### Wall Time

| Metric | Value |
|---|---|
| Total wall time | ~9 min |
| Files processed | 71 (70 with content) |
| Avg time per file | ~7.7s |
| Total LLM requests | 147 |
| Avg latency per request | 16.2s |
| Errors | 0 |
| finished_reason=length | 0 |

### Token Throughput

| Metric | Value |
|---|---|
| Total prompt tokens | 401,258 |
| Total generation tokens | 32,231 |
| Avg prompt tokens/request | 2,730 |
| Avg generation tokens/request | 219 |
| Effective generation throughput | ~60 tok/s (across all concurrent requests) |
| Per-request generation rate | ~13.5 tok/s |

### GPU Utilization (sampled every 60s during ingestion)

| Sample | Files Done | GPU % | Power (W) | KV Cache % | Running Reqs |
|---|---|---|---|---|---|
| 1 | 6/70 | 96% | 31.8 | 2.9% | 4 |
| 2 | 12/70 | 96% | 33.1 | 2.6% | 4 |
| 3 | 21/70 | 96% | 34.1 | 1.9% | 3 |
| 4 | 30/70 | 96% | 32.2 | 1.9% | 3 |
| 5 | 38/70 | 96% | 34.6 | 3.5% | 4 |
| 6 | 44/70 | 96% | 34.8 | 3.4% | 4 |
| 7 | 50/70 | 96% | 32.9 | 2.5% | 4 |
| 8 | 57/70 | 96% | 33.9 | 2.1% | 4 |
| 9 | 65/70 | 96% | 34.8 | 2.2% | 4 |
| 10 | 71/70 | 0% | 12.0 | 0.0% | 0 |

### Memory Utilization

| Metric | Value |
|---|---|
| System memory (during ingestion) | 72 GiB / 119 GiB (60%) — stable throughout |
| Model weight memory (GPU) | 18.5 GiB |
| GPU memory utilization setting | 30% (of 119 GiB = ~35.7 GiB allocated) |
| KV cache usage | 1.9–3.5% of allocated GPU memory |
| Power draw (active) | 31–35W |
| Power draw (idle) | 12W |

---

## Observations

### GPU is compute-bound, not memory-bound

- GPU utilization is a constant **96%** across all samples — the MoE expert routing saturates compute
- KV cache usage is trivially low (**1.9–3.5%**) — model context is not a bottleneck
- Only 3–4 concurrent requests running at any time, limited by `--max-num-seqs 8` and `MAX_ASYNC=8`
- Zero requests waiting in queue — extraction throughput is the bottleneck, not batching capacity

### Memory is underutilized

- System memory stable at **60%** — 47 GiB free headroom
- GPU memory utilization set to only **30%** — could be increased to cache more KV entries
- Model weights are 18.5 GiB but only 3.3B params active per token (MoE sparsity)

### Throughput profile

- **7.9 files/min** sustained processing rate
- **~60 tok/s** aggregate generation throughput (across concurrent requests)
- Each request averages **2,730 prompt tokens → 219 generation tokens** (8:1 ratio)
- Prefix cache should be highly effective given the shared system prompt across all extraction calls

### Consistency with benchmark

Results are very consistent with the Phase 4 benchmark run:

| Metric | Phase 4 (benchmark) | This run (production) |
|---|---|---|
| Nodes | 326 | 322 |
| Relationships | 439 | 440 |
| Cross-file rels | 256 | 302 |
| Rel types | 43 | 43 |
| LLM requests | 149 | 147 |
| Gen tokens | 32,727 | 32,231 |
| Wall time | ~10 min | ~9 min |

Cross-file relationships improved from 256 → 302 (+18%), possibly due to a cleaner LightRAG state or slight non-determinism in extraction.

---

## Tuning Opportunities

### Compute-bound bottlenecks
1. **`MAX_PARALLEL_INSERT=4`** — only 4 documents process concurrently. Since each doc is 1 chunk, this limits pipeline parallelism. Increasing to 8 would better match `--max-num-seqs 8`.
2. **`--max-num-seqs 8`** — could be increased if `MAX_PARALLEL_INSERT` is also raised, but may increase per-request latency due to shared GPU compute.
3. **`--gpu-memory-utilization 0.30`** — only 30% of GPU memory allocated. Increasing would allow more KV cache entries and potentially more concurrent requests.

### Memory headroom
4. **System memory at 60%** — 47 GiB free. Could increase vLLM GPU memory utilization or run additional services.
5. **MPS slice allocation** — currently 3 equal slices. Extract could benefit from a larger share since it's the bottleneck.

### Pipeline efficiency
6. **Prefix caching** — enabled but effectiveness not measured. The shared extraction system prompt (~2K tokens) should cache well across requests.
7. **Chunked prefill** — enabled by default but batch size could be tuned.
8. **Embedding pipeline** — pipelined embedding adds ~30ms/file overhead (negligible for single-chunk files, significant for multi-chunk documents).

---

## Configuration Reference

```yaml
# charts/graphrag/values.yaml (extraction section)
extraction:
  image: vllm/vllm-openai:nightly-aarch64
  model: "Qwen3-30B-A3B-Instruct-2507"
  modelPath: "/data/Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf"
  tokenizer: "/data/tokenizer"
  dtype: "half"
  servedModelName: "qwen3-30b-a3b-extract"
  pvc: "model-qwen3-30b-a3b"
  maxModelLen: "8192"
  maxNumSeqs: "8"
  gpuMemoryUtilization: "0.30"

# LightRAG settings (lightrag-configmap.yaml)
MAX_ASYNC: "8"
MAX_PARALLEL_INSERT: "4"
LLM_TIMEOUT: "600"
CODE_EXTRACTION_PROMPT: "1"
LLM_MAX_TOKENS: "2048"
TYPED_RELATIONSHIPS: "1"
PIPELINED_EMBEDDING: "1"
```
