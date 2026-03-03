# GraphRAG-Only Deployment Implementation Plan

## Context

The project currently serves dual purposes: general LLM serving (Qwen coder + DeepSeek reasoning) and a GraphRAG pipeline. The goal is to strip out the LLM serving layer and refocus entirely on maximum document ingestion throughput. This frees GPU/memory for scaling extraction replicas (the primary ingestion bottleneck), switches GPU sharing from time-slicing to MPS for proportional allocation, and adds a NATS queue-depth auto-scaler for burst mode.

Key targets from the architectural discussion:
- 4x Qwen3-8B extraction replicas (Q4_K_M), 8192 ctx, 8 concurrent seqs = 32 parallel extractions
- MPS with 10 slices (2 per extraction replica = 8, 1 reranker, 1 spare/burst)
- Memory at ~74% of 128GB (94.7GB) in normal mode, ~80% in burst
- NATS queue-depth auto-scaler with hysteresis for burst mode (5th replica, reranker scales to 0)
- `/v1/data/query` endpoint for raw graph subgraph queries
- Query-aware burst blocking via Redis TTL

---

## Phase 1: Infrastructure — GPU MPS Switch

**File: `install-k8s.yml` (lines 312–380)**

1. Rename ConfigMap from `time-slicing-config` to `mps-config`
2. Change sharing strategy from `timeSlicing` to `mps`, replicas from `5` to `10`
3. Update Helm `--set devicePlugin.config.name=mps-config`
4. Update task names and debug messages (cosmetic)
5. GPU test remains the same (2 pods, same verification logic — MPS is transparent to pods)

---

## Phase 2: Remove Coding/Reasoning Models

### `group_vars/k8s.yml`
- Delete `models.coding` and `models.reasoning` blocks entirely
- Add to `models.extract`: `num_parallel: "8"`, `replicas: 4`, `burst_replicas: 5`
- Add to `models.embed`: `mode: "dedicated"` (toggle for CPU vs unified GPU)
- Add top-level `graphrag.ingest_worker_replicas: 4`, `graphrag.code_preprocessor_replicas: 2`

### Playbooks to guard/disable
- **`deploy-models.yml`**: Add `meta: end_play` when `models.coding is not defined`
- **`install-opencode.yml`**: Same guard
- **`remove-models.yml`**: Already no-ops when release doesn't exist
- **`charts/llm-serving/`**: Leave intact, just never deployed

### `deploy-graphrag.yml`
- Remove `--set orchestrator.backends.qwen=...` and `--set orchestrator.backends.deepseek=...`
- Add `--set extraction.replicas=`, `--set extraction.numParallel=`, `--set extraction.burstReplicas=`
- Add `--set embedding.mode=`, `--set ingestWorker.replicas=`, `--set codePreprocessor.replicas=`
- Add queue-scaler image build task (same nerdctl pattern as other apps)
- Update extraction verification to use `kubectl get pod -l app=ollama-extract | head -1` instead of hardcoded deploy name

---

## Phase 3: Helm Chart — Multi-Replica Extraction + Scaling

### `charts/graphrag/values.yaml`
- **extraction**: `replicas: 4`, `burstReplicas: 5`, `numParallel: "8"`, `numCtx: "8192"`, resources `nvidia.com/gpu: "2"` (2 MPS slices per replica), memory limit `24Gi`
- **embedding**: Add `mode: "dedicated"`, add separate `gpuResources` block for unified mode
- **orchestrator**: Remove `backends.qwen`/`backends.deepseek`, add `rerankerUrl`, `queryActivityKey`, `queryActivityTtl`
- **ingestWorker**: `replicas: 4`
- **codePreprocessor**: Add `replicas: 2`
- **New section `queueScaler`**: image, poll interval, thresholds, hysteresis counts, burst/normal replica counts

### Template changes

**`templates/pvcs.yaml`**
- Rename `ollama-extract-data` PVC to `ollama-extract-weights` (shared weights, RWO — single-node allows multiple read-only mounts)

**`templates/ollama-extract-deployment.yaml`** — Major rewrite
- `replicas: {{ .Values.extraction.replicas }}`
- Init container that symlinks blobs from shared `ollama-extract-weights` PVC (read-only mount) into a writable `emptyDir`
- Main container mounts emptyDir at `/root/.ollama`
- `OLLAMA_NUM_PARALLEL={{ .Values.extraction.numParallel }}`
- `nvidia.com/gpu: "2"` (2 MPS slices per replica)
- postStart creates the `-extract` Modelfile variant with `num_ctx` override (same as current)

**`templates/ollama-embed-deployment.yaml`**
- Conditional `runtimeClassName: nvidia` only when `embedding.mode == "unified"`
- Conditional resource block: CPU resources (no GPU) for `dedicated`, GPU resources for `unified`

**`templates/vllm-rerank-deployment.yaml`**
- Add missing `runtimeClassName: nvidia`

**`templates/code-preprocessor-deployment.yaml`**
- `replicas: {{ .Values.codePreprocessor.replicas | default 1 }}`

**`templates/orchestrator-configmap.yaml`**
- Remove `QWEN_BACKEND_URL` and `DEEPSEEK_BACKEND_URL`
- Add conditional `EMBED_URL`/`EMBED_MODEL`/`EMBED_DIM` based on `embedding.mode` (dedicated → ollama-embed/0.6b/1024, unified → ollama-extract/qwen3:8b/4096)
- Add `RERANKER_URL`, `QUERY_ACTIVITY_KEY`, `QUERY_ACTIVITY_TTL`

**New templates:**
- `templates/queue-scaler-deployment.yaml` — Deployment with `serviceAccountName: queue-scaler`, init waits for NATS + Redis
- `templates/queue-scaler-configmap.yaml` — NATS monitor URL, thresholds, replica counts
- `templates/queue-scaler-rbac.yaml` — ServiceAccount + Role (get/patch on deployments/scale for ollama-extract + vllm-rerank) + RoleBinding

---

## Phase 4: Orchestrator Application Changes

### `apps/orchestrator/app/config.py`
- Remove `qwen_backend_url`, `deepseek_backend_url`
- Add: `reranker_url: str`, `query_activity_key: str`, `query_activity_ttl: int = 120`, `embedding_mode: str = "dedicated"`

### `apps/orchestrator/app/services/router.py`
- Gut to a stub: `init_routes()` → no-op, `resolve()` → raises ValueError pointing to `/v1/data/query`, `list_models()` → returns `[]`

### `apps/orchestrator/app/routes/chat.py`
- Replace endpoint body with 410 Gone: "Chat completions disabled. Use /v1/data/query for graph queries."
- Remove all memory augmentation logic, `init_chat()`, helper functions

### `apps/orchestrator/app/services/ollama_proxy.py`
- Leave as dead code (no callers), or delete — either is fine

### New: `apps/orchestrator/app/services/query_tracker.py`
- `init_tracker(redis_client)` — stores reference to the existing Redis client from `working_memory`
- `mark_active(key, ttl)` — `SET key timestamp EX ttl`
- `get_activity(key)` → `{"active": bool, "last_query_at": str|None, "ttl_remaining": int}`

### New: `apps/orchestrator/app/routes/data_query.py`
- `POST /v1/data/query` — accepts `{query, workspace, mode}`
- Probes reranker health (`GET reranker_url/health`); 503 if down (burst mode)
- Calls `mark_active()` to set Redis TTL key
- Calls `archival_memory.query()` for raw graph data
- Returns OpenAI-compatible wrapper with `graph` extension field containing `{entities, relations, chunks}`

### New: `apps/orchestrator/app/routes/internal.py`
- `GET /internal/query-activity` — calls `query_tracker.get_activity()`, returns JSON for queue-scaler polling

### `apps/orchestrator/app/models.py`
- Add `DataQueryRequest(query, workspace, mode)`
- Add `GraphSubgraph(entities, relations, chunks)`
- Add `DataQueryResponse` extending ChatCompletionResponse with optional `graph: GraphSubgraph`

### `apps/orchestrator/app/db.py`
- Parameterize `vector(1024)` in SCHEMA_SQL to use `settings.embed_dim`
- Add dimension migration: detect mismatch via `pg_attribute.atttypmod`, drop+recreate column if changed

### `apps/orchestrator/app/main.py`
- Import and register new routes: `data_query`, `internal`
- Initialize `query_tracker` with `working_memory._client` (or add `get_client()` to working_memory)
- Initialize `data_query.init_data_query(settings, _http_client)`
- Update app title to "GraphRAG Orchestrator", version to "0.2.0"

---

## Phase 5: Queue-Scaler Application (new)

### `apps/queue-scaler/`
```
app/__init__.py
app/config.py    — pydantic-settings: NATS monitor URL, orchestrator URL, K8s namespace,
                   deployment names, thresholds, hysteresis counts, poll interval
app/scaler.py    — get_pending_count() via NATS HTTP monitoring API (/jsz),
                   check_query_activity() via orchestrator /internal/query-activity,
                   scale_deployment() via kubernetes python client
app/main.py      — asyncio loop: poll → state machine (NORMAL/BURST) with hysteresis →
                   enter_burst (scale reranker→0, wait, scale extraction→5) /
                   exit_burst (scale extraction→4, wait, sleep 10s, scale reranker→1)
requirements.txt — httpx, pydantic-settings, kubernetes
Dockerfile       — python:3.12-slim
```

State machine:
- **NORMAL→BURST**: N consecutive polls with pending > threshold AND no active queries (Redis check)
- **BURST→NORMAL**: M consecutive polls with pending < threshold
- Enter burst: scale reranker to 0 → wait for termination → scale extraction to burst_replicas
- Exit burst: scale extraction to normal_replicas → wait for excess pod deletion → sleep 10s → scale reranker to 1

---

## Phase 6: Documentation

- Update `CLAUDE.md` to reflect new architecture
- Update `README.md` deployment sequence (skip `deploy-models.yml`, `install-opencode.yml`)

---

## Implementation Order

1. `group_vars/k8s.yml` — foundation config (everything else references this)
2. `install-k8s.yml` — MPS switch (must happen before redeploying GPU pods)
3. `charts/graphrag/values.yaml` — central Helm values
4. `charts/graphrag/templates/` — pvcs → extract deployment → embed deployment → reranker → preprocessor → orchestrator configmap → queue-scaler templates
5. `apps/orchestrator/` — config → query_tracker → internal route → data_query route → main.py wiring → gut chat/router → db.py dimension
6. `apps/queue-scaler/` — new app (entirely independent)
7. `deploy-graphrag.yml` — updated Helm install command + queue-scaler build
8. `deploy-models.yml` + `install-opencode.yml` — add skip guards
9. `CLAUDE.md` — documentation

---

## Verification

1. **Helm template validation**: `helm template graphrag charts/graphrag` — verify all templates render correctly with new values
2. **Image builds**: `nerdctl --namespace k8s.io build` for orchestrator (changed) and queue-scaler (new)
3. **GPU MPS**: After `install-k8s.yml`, verify `kubectl describe node | grep nvidia.com/gpu` shows `10` allocatable
4. **Extraction replicas**: `kubectl -n graphrag get pods -l app=ollama-extract` should show 4 Running pods
5. **Data API**: `curl -X POST http://localhost:31800/v1/data/query -d '{"query":"test","workspace":"default"}'`
6. **Query activity**: `curl http://localhost:31800/internal/query-activity` — should show `{"active": true, ...}` after a query
7. **Burst mode**: Ingest a large corpus, monitor `kubectl -n graphrag logs deploy/queue-scaler` for state transitions
8. **Chat disabled**: `curl -X POST http://localhost:31800/v1/chat/completions` should return 410

---

## Risk Areas

| Risk | Impact | Mitigation |
|------|--------|------------|
| Longhorn RWO shared across 4 pods | Breaks on multi-node | Single-node only; document assumption. All pods mount with `readOnly: true` |
| MPS + Ollama compatibility | Extraction pods may fail | Verify CUDA MPS daemon doesn't conflict with Ollama's CUDA env vars |
| Burst mode GPU overcommit | OOM if reranker not fully terminated | Queue-scaler waits for 0 ready pods before scaling extraction up |
| Query/burst race condition | Reranker scaled down mid-query | 120s Redis TTL provides generous buffer; scaler checks activity before entering burst |
| NATS monitoring API format | Scaler can't read pending count | Verify `/jsz` response structure against NATS 2-alpine; handle missing fields gracefully |
| Vector dimension migration (1024→4096) | Existing embeddings lost | Acceptable for GraphRAG-only pivot; log warning, auto-recreate column |
| vLLM on ARM64/GB10 | May not build cleanly | Fallback: keep Ollama with `OLLAMA_NUM_PARALLEL=4` per replica |
