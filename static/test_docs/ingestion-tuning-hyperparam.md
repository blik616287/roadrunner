# GraphRAG Ingestion Tuning Guide

System: NVIDIA DGX Spark (GB10), 119 GiB usable unified memory (CPU+GPU shared), ARM64

## Hard Rule

**Never exceed 80% of total system memory (95 GiB) at peak.**

## Memory Baseline (Idle)

| Component | Memory (GiB) | Notes |
|---|---|---|
| vLLM-extract model weights | 18.5 | Qwen3-30B-A3B Q4_K_M GGUF (MoE: 30B total, 3.3B active/token) |
| vLLM CUDA graph capture | 2.0 | One-time at startup |
| Neo4j | 5.0 | 4G heap + 1G pagecache |
| vLLM-embed | 2.0 | Qwen3-Embedding-0.6B (dedicated vLLM pooling runner, 0.15 gpuMemoryUtil) |
| PostgreSQL | 1.0 | pgvector + connection pools |
| All other pods | 1.3 | orchestrator, redis, nats, UI, queue-scaler, mps-fixer |
| Kernel + system | 4.0 | |
| **Idle subtotal (excl. KV cache)** | **~29.5** | Before any KV cache allocation |

## Burst Overhead (During Heavy Ingestion)

These scale with concurrency settings:

| Component | Formula | Notes |
|---|---|---|
| Code-preprocessor (×2) | ~3 GiB fixed | tree-sitter ASTs, 20-file batches |
| LightRAG | ~0.3 × MAX_ASYNC | httpx buffers, doc processing queue |
| Ingest-workers | ~0.5 × replicas | archive decompression, batch payloads |
| Neo4j insert spikes | ~2 GiB fixed | graph write transactions |
| PostgreSQL inserts | ~0.5 GiB fixed | pgvector bulk inserts |
| vLLM-embed burst | ~0.5 GiB fixed | concurrent embedding requests (continuous batching) |

## vLLM KV Cache

On unified memory, `gpuMemoryUtilization` controls how much memory vLLM **pre-allocates at startup** for model weights + KV cache combined.

At 0.30: allocates ~35.7 GiB total. After 18.5 GiB model weights → **~17.2 GiB KV cache**.

**Key observation**: MoE models use KV cache very efficiently. During production ingestion with 4 concurrent requests, KV cache utilization was only **1.9–3.5%**. The KV cache is massively over-provisioned at current settings.

Scales approximately linearly with `gpuMemoryUtilization`.

## Observed Runtime Metrics (Production Baseline)

Measured during ingestion of 71 files (apps/ directory) with current default settings:

| Metric | Value |
|---|---|
| **Model** | Qwen3-30B-A3B Q4_K_M GGUF |
| **Total wall time** | ~9 min |
| **Files processed** | 70 (of 71) |
| **Avg time per file** | ~7.7s |
| **LLM requests** | 147 |
| **Avg latency/request** | 16.2s |
| **Aggregate generation throughput** | ~60 tok/s |
| **Per-request generation rate** | ~13.5 tok/s |
| **Avg prompt tokens/request** | 2,730 |
| **Avg generation tokens/request** | 219 |
| **GPU utilization** | **96% constant** (compute-bound) |
| **KV cache utilization** | 1.9–3.5% |
| **System memory (peak)** | **72 GiB / 119 GiB (60%)** |
| **Power draw (active)** | 31–35W |
| **Concurrent requests** | 3–4 (limited by MAX_PARALLEL_INSERT=4) |
| **Errors / truncations** | 0 |

### Bottleneck Analysis

The system is **compute-bound, not memory-bound**:

1. **GPU at 96%** — MoE expert routing saturates SM121 compute at just 3–4 concurrent requests
2. **KV cache at 1.9–3.5%** — trivially low; memory is not the constraint
3. **47 GiB free system memory** — massive headroom unused
4. **Zero queued requests** — vLLM never has a request backlog; extraction throughput is the bottleneck
5. **MAX_PARALLEL_INSERT=4 is the pipeline limiter** — only 4 docs process concurrently despite MAX_ASYNC=8

## Tuning Sweep Results

Tested on 71 files (apps/ directory). All sweeps produce ~147 LLM requests.

| | Baseline | Sweep 1 | Sweep 2 | Sweep 4a | Sweep 4b |
|---|---|---|---|---|---|
| **MAX_PARALLEL_INSERT** | 4 | **8** | **8** | 4 | 4 |
| **MAX_ASYNC** | 8 | 8 | **12** | 8 | 8 |
| **maxNumSeqs** | 8 | 8 | **12** | 8 | 8 |
| **Workers** | 2 | 2 | **3** | 2 | 2 |
| **MPS thread %** | default | default | default | **80/10/10** | **60/30/10** |
| **Wall time** | ~9 min | ~8 min | ~9 min | ~10 min | ~9 min |
| **Concurrent reqs** | 3–4 | 6–8 | 6–8 | 4 | 3–4 |
| **Peak memory** | 72 GiB | 73 GiB | 74 GiB | 73 GiB | 60 GiB |
| **Nodes** | 322 | 320 | 309 | 309 | — |
| **Relations** | 440 | 424 | 421 | 425 | — |
| **Cross-file** | 302 | 240 | 271 | 259 | — |
| **Rel types** | 43 | 46 | 38 | 44 | — |

### Conclusion

**The system is GPU compute-bound.** No tuning parameter improved wall time:

- **Sweeps 1–2** (pipeline concurrency): Doubled concurrent requests but GPU was already saturated at 96% — more requests just increases per-request latency. Total throughput stays at ~60 tok/s aggregate.
- **Sweeps 4a–4b** (MPS thread caps): `CUDA_MPS_ACTIVE_THREAD_PERCENTAGE` is a **cap**, not a guarantee. Without it, MPS dynamically gives each client up to 100% of SMs when others are idle. Since embed/rerank are mostly idle during extraction, vllm-extract already gets nearly all SMs by default. Setting a cap only **restricts** it — 80% was slower, 60% was comparable.

**Optimal config: baseline settings** (maxNumSeqs=8, MAX_ASYNC=8, MAX_PARALLEL_INSERT=4, workers=2, gpuMemoryUtil=0.30, no MPS thread caps). These saturate the GPU without wasting memory on extra concurrency.

## Where to Change Each Setting

| Setting | File | Location |
|---|---|---|
| `gpuMemoryUtilization` | `charts/graphrag/values.yaml` | `extraction.gpuMemoryUtilization` |
| `maxNumSeqs` | `charts/graphrag/values.yaml` | `extraction.maxNumSeqs` |
| `MAX_ASYNC` | `charts/graphrag/values.yaml` | `lightrag.maxAsync` |
| `MAX_PARALLEL_INSERT` | `charts/graphrag/values.yaml` | `lightrag.maxParallelInsert` |
| `ingestWorker.replicas` | `charts/graphrag/values.yaml` | `ingestWorker.replicas` |
| MPS slice sizes | `/etc/nvidia/mps/partitions.conf` | Requires node reconfig + MPS restart |

## After Changing Values

```bash
# Apply helm changes
helm upgrade --install graphrag charts/graphrag --namespace graphrag

# Restart affected pods (configmap changes need pod restart)
kubectl -n graphrag rollout restart deployment/vllm-extract deployment/lightrag deployment/ingest-worker

# Verify KV cache allocation
kubectl -n graphrag logs deploy/vllm-extract | grep "KV cache"

# Verify system memory
free -h
```

## Monitoring During Ingestion

```bash
# System memory (repeat during ingest)
free -h

# Per-pod memory usage
kubectl -n graphrag top pods

# vLLM metrics (KV cache %, running requests, throughput)
kubectl -n graphrag exec deploy/vllm-extract -- curl -s http://localhost:8000/metrics | \
  grep -E 'kv_cache_usage_perc|num_requests_running|generation_tokens_total|prompt_tokens_total'

# GPU utilization + power
tegrastats --interval 5000 | head -3

# NATS queue depth
curl -s http://localhost:8222/jsz?streams=1 | python3 -c "
import sys,json; d=json.load(sys.stdin)
for a in d.get('account_details',[]):
  for s in a.get('stream_detail',[]):
    print(f\"{s['name']}: {s['state']['messages']} pending\")
"

# Job status counts
curl -s 'http://localhost:31800/v1/jobs?workspace=<WS>&limit=200' | python3 -c "
import sys,json; from collections import Counter
jobs=json.load(sys.stdin)['jobs']; c=Counter(j['status'] for j in jobs)
print(', '.join(f'{s}: {n}' for s,n in sorted(c.items())))
"
```

## Notes

- On GB10, CPU and GPU share the same 128 GiB (119 GiB usable). `gpuMemoryUtilization` controls pre-allocation from this shared pool — setting it too high starves CPU processes.
- vLLM's continuous batching means lowering `maxNumSeqs` doesn't reduce throughput much — requests queue and get processed in order. The main benefit of higher `maxNumSeqs` is latency under concurrent load.
- **MoE efficiency**: Qwen3-30B-A3B has 30B total params but only 3.3B active per token. This means GPU compute saturates at lower concurrency than dense models, but KV cache usage is very low per request.
- `MAX_PARALLEL_INSERT` is the current throughput bottleneck — at 4, it limits pipeline concurrency below what the GPU could handle. This is the highest-priority tuning knob.
- The queue-scaler scales vllm-rerank to 0 during burst ingestion, freeing its GPU memory slice. All profiles assume this is active.
- Supported dtypes: BF16 (native checkpoints) and Q4_K_M GGUF (via `--dtype half`). FP8 CUTLASS kernels crash on SM121. NVFP4 requires custom vLLM image and JIT compilation that OOMs at practical memory limits.
