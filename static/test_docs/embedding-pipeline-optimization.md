# Embedding Pipeline Optimization Plan

## Context

During model benchmarking, we found that the ingestion pipeline has two bottlenecks in the embedding stage:
1. **Suboptimal config**: Default batch size (10) and concurrency (8) waste HTTP round-trips to Ollama
2. **Sequential barrier**: LightRAG embeds ALL chunks before starting ANY extraction — but extraction doesn't need embeddings (it only needs chunk text). On the slow 32B model, this wastes 10-15s per document

Additionally, the user asked about **replacing Ollama with vLLM for embedding** — Qwen3-Embedding-0.6B is [supported by vLLM](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) (>=0.8.5) with `--runner pooling`, which gives continuous batching and better throughput.

## Changes

### Part A: Replace Ollama with vLLM for Embedding

Replace the `ollama-embed` deployment with a dedicated `vllm-embed` deployment serving `Qwen/Qwen3-Embedding-0.6B` via vLLM's pooling runner.

**Why**: vLLM has continuous batching (dynamic, not fixed-size), lower per-request overhead, and already runs on our stack. Ollama processes requests sequentially internally — vLLM pipelines them.

**Files to modify:**

1. **`charts/graphrag/templates/ollama-embed-deployment.yaml`** → rename to **`vllm-embed-deployment.yaml`**
   - Replace Ollama container with `vllm/vllm-openai:nightly-aarch64`
   - Args: `Qwen/Qwen3-Embedding-0.6B --runner pooling --dtype half --host 0.0.0.0 --port 8000 --max-model-len 8192 --gpu-memory-utilization 0.15 --trust-remote-code`
   - Mount existing embedding model PVC (download the HF model instead of Ollama format)
   - Switch service port from 11434 to 8000
   - Startup probe: `/health` HTTP GET (same as vllm-extract)

2. **`charts/graphrag/templates/lightrag-configmap.yaml`**
   - Change `EMBEDDING_BINDING` from `ollama` to `openai`
   - Change `EMBEDDING_BINDING_HOST` from `http://ollama-embed:11434` to `http://vllm-embed:8000/v1`
   - Add tuning env vars:
     ```yaml
     EMBEDDING_BATCH_NUM: "32"
     EMBEDDING_FUNC_MAX_ASYNC: "4"
     EMBEDDING_TIMEOUT: "60"
     ```

3. **`charts/graphrag/values.yaml`**
   - Update embedding section: change image to vLLM, change port, add vLLM-specific args
   - Add `embeddingBatchNum`, `embeddingFuncMaxAsync`, `embeddingTimeout` settings

4. **`group_vars/k8s.yml`** — Change embedding model definition:
   ```yaml
   # Before:
   embed:
     name: "qwen3-embedding"
     tag: "qwen3-embedding:0.6b"      # Ollama tag
     source: ollama
     namespace: graphrag
     pvc: ollama-embed-data
     size: 5Gi
     mode: "dedicated"

   # After:
   embed:
     name: "qwen3-embedding"
     tag: "Qwen/Qwen3-Embedding-0.6B" # HuggingFace repo
     source: huggingface               # triggers HF download block
     namespace: graphrag
     pvc: vllm-embed-data              # new PVC name to match vllm-embed deployment
     size: 5Gi
     mode: "dedicated"
   ```
   The `download-models.yml` playbook is fully parameterized — it automatically routes `source: huggingface` models through the `snapshot_download()` path (lines 121-169). No playbook changes needed.

5. **`download-models.yml`** — No changes needed (parameterized). Just re-run:
   ```bash
   ansible-playbook -i inventory.ini download-models.yml
   ```
   This creates the `vllm-embed-data` PVC and downloads `Qwen/Qwen3-Embedding-0.6B` HF weights into it.

**LightRAG compatibility**: LightRAG's `openai_embed` function uses the standard `/v1/embeddings` endpoint, which vLLM serves natively. No code patches needed — just config change.

### Part B: Pipeline Embedding + Extraction (monkey-patch)

Add `_patch_pipelined_embedding()` to `workspace_patch.py` to overlap embedding and extraction.

**How it works:**

```
BEFORE (sequential):
  [embed ALL chunks] ──await──→ [extract ALL chunks] ──→ [merge]

AFTER (pipelined):
  [embed ALL chunks] ──────────────────→ (completes in background)
  [extract ALL chunks] ──────────────→ (starts immediately)
  ──── both awaited together ────────→ [merge]
```

**Two monkey-patches:**

1. **Patch `PGVectorStorage.upsert`** (chunks namespace only):
   - Instead of blocking until all embeddings are done and stored, create an `asyncio.Task` for the work and return immediately
   - Store the task in `self._embedding_futures[chunk_key]` keyed by `frozenset(data.keys())` (chunk IDs are content hashes, unique per document)
   - Non-chunks namespaces (entities, relationships) behave normally

2. **Patch `LightRAG._process_extract_entities`**:
   - Look up the deferred embedding task from `self.chunks_vdb._embedding_futures`
   - Run extraction AND the deferred embedding concurrently via `asyncio.gather(extract_task, embedding_future)`
   - Return extraction results; embedding completes alongside it

**Gated by**: `PIPELINED_EMBEDDING=1` env var (default off).

**Files to modify:**

1. **`apps/lightrag/workspace_patch.py`** — Add `_patch_pipelined_embedding()` function, call it from `main()`
2. **`charts/graphrag/templates/lightrag-configmap.yaml`** — Add `PIPELINED_EMBEDDING` env var
3. **`charts/graphrag/values.yaml`** — Add `pipelinedEmbedding: "1"` setting

**Error handling:**
- If embedding fails: `asyncio.gather` raises, both tasks cancelled, document marked FAILED (correct — incomplete without embeddings)
- If extraction fails: embedding still completes (data stored), document marked FAILED, retry will find embeddings via `ON CONFLICT DO NOTHING`
- Race condition between documents: prevented by keying futures on `frozenset(chunk_ids)` — each document has unique chunk hashes

**Expected speedup:** ~10-15% per document (saves the embedding time that currently blocks extraction). Bigger win on documents with many chunks or when embedding is slow.

## Implementation Order

1. Update `group_vars/k8s.yml` embed model definition (ollama → huggingface)
2. Run `download-models.yml` to download HF weights to new `vllm-embed-data` PVC
3. Replace `ollama-embed-deployment.yaml` with `vllm-embed-deployment.yaml` (Part A)
4. Update configmap + values.yaml (embedding binding, tuning params, pipelining env var)
5. Add `_patch_pipelined_embedding()` to `workspace_patch.py` (Part B)
6. Rebuild LightRAG image (needed for Part B)
7. Helm upgrade
8. Test with a small ingestion, verify embeddings + extraction both complete
9. Re-run benchmark to measure improvement

## Verification

```bash
# After deploy, verify vllm-embed is serving:
kubectl -n graphrag exec deploy/vllm-embed -- curl -s http://localhost:8000/v1/embeddings \
  -d '{"model":"Qwen/Qwen3-Embedding-0.6B","input":"test"}' | python3 -m json.tool

# Verify LightRAG can embed through it:
curl -s http://localhost:31436/health | python3 -c "import sys,json; print(json.load(sys.stdin)['configuration']['embedding_binding'])"
# Should print: openai

# Ingest a small doc and check:
# 1. Neo4j has entities (extraction worked)
# 2. pgvector has embeddings (embedding worked)
# 3. Pipeline logs show "[pipeline] Starting pipelined extraction" (Part B working)

# Compare timing: ingest the benchmark corpus and compare total time vs previous runs
```

## Critical Files

| File | Change |
|------|--------|
| `group_vars/k8s.yml` | Change embed model: `source: huggingface`, `tag: Qwen/Qwen3-Embedding-0.6B`, `pvc: vllm-embed-data` |
| `charts/graphrag/templates/ollama-embed-deployment.yaml` | Replace with vLLM-based `vllm-embed` deployment |
| `charts/graphrag/templates/lightrag-configmap.yaml` | Switch to openai binding, add tuning + pipelining env vars |
| `charts/graphrag/values.yaml` | Update embedding config, add new tuning values |
| `apps/lightrag/workspace_patch.py` | Add `_patch_pipelined_embedding()` |
