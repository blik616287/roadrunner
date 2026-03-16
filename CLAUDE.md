# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Roadrunner is a self-hosted GraphRAG pipeline that ingests documents and codebases, builds a knowledge graph (Neo4j + pgvector), and exposes a structured data query API. It targets a single NVIDIA DGX Spark (ARM64/GB10) with GPU sharing via MPS. Deployment is fully automated via Ansible playbooks and a Helm chart.

## Deployment Commands

```bash
# Full setup (run in order)
ansible-playbook -i inventory.ini install-k8s.yml      # k8s + MPS + Longhorn
ansible-playbook -i inventory.ini download-models.yml   # populate model PVCs
ansible-playbook -i inventory.ini deploy-graphrag.yml   # build images + helm install

# Teardown
ansible-playbook -i inventory.ini remove-graphrag.yml   # uninstall pipeline
ansible-playbook -i inventory.ini remove-k8s.yml        # remove k8s entirely

# Download test/benchmark models
ansible-playbook -i inventory.ini download-models.yml -e download_test_models=true
```

There is no local test suite or linting setup — the apps run inside Kubernetes pods.

## Architecture Overview

Eight microservices deployed in the `graphrag` Kubernetes namespace:

1. **Orchestrator** (`apps/orchestrator/`) — FastAPI API gateway (port 31800). Receives uploads, stores gzipped blobs in PostgreSQL, publishes NATS messages, and serves the data query API. Routes are split across `app/routes/` (auth, documents, jobs, workspaces, sessions, data_query, graph, chat, internal, models_list). Services in `app/services/` handle NATS, Redis working memory, embedding, reconciliation, etc.

2. **Ingest Worker** (`apps/ingest-worker/`) — NATS JetStream pull consumer. Fetches blobs from PostgreSQL, sends files in batches to the code preprocessor, then polls LightRAG until indexing completes. Runs as 4 replicas by default.

3. **Code Preprocessor** (`apps/code-preprocessor/`) — FastAPI service (port 31490). Parses code via tree-sitter into natural-language Markdown, splits PDFs into 50-page chunks via pdfplumber, and tags all content with `<!-- filetype:xxx -->` markers. Runs as 2 replicas.

4. **LightRAG** (`apps/lightrag/`) — Patched upstream `lightrag-hku` with `workspace_patch.py` as the entrypoint. The patch adds: contextvar-based multi-workspace isolation, per-filetype extraction prompts/entity types/examples, max_tokens injection, typed Neo4j relationships (keyword-based instead of DIRECTED), and pipelined embedding+extraction. All patches are env-var gated.

5. **Ingestion UI** (`apps/ingestion-ui/`) — React 19 / Vite / Tailwind SPA served via nginx (port 31300). Dashboard, file upload, job tracker, document manager, graph explorer, and multi-mode query interface. Includes auth flow (login page, account page with API key management).

6. **Queue Scaler** (`apps/queue-scaler/`) — Monitors NATS queue depth and toggles burst mode (scales reranker replicas to 0) to free GPU memory during heavy ingestion.

7. **CPU Query** (`apps/cpu-query/`) — CPU-based query inference fallback (no GPU required).

8. **CPU Rerank** (`apps/cpu-rerank/`) — CPU-based reranker using `sentence-transformers` CrossEncoder, serves a Cohere-compatible `/rerank` endpoint. Fallback when GPU reranker is scaled down.

### Data Flow

Upload → Orchestrator (gzip to PostgreSQL + NATS publish) → Ingest Worker (decompress, batch files) → Code Preprocessor (tree-sitter/PDF/passthrough + filetype tag) → LightRAG (embed via vLLM + extract entities via vLLM → pgvector + Neo4j)

### GPU Layer (4 MPS slices)

| Service | Model | Purpose |
|---|---|---|
| vllm-extract | Qwen3-30B-A3B Q4_K_M GGUF | Entity/relation extraction |
| vllm-query | Qwen3-30B-A3B Q4_K_M GGUF | Explain/synthesis |
| vllm-rerank | bge-reranker-v2-m3 | Query reranking |
| vllm-embed | Qwen3-Embedding-0.6B | 1024-dim embedding |

### Storage

PostgreSQL+pgvector (blobs, jobs, vectors, KV), Neo4j (knowledge graph), Redis (session memory, query tracking, auth sessions), NATS JetStream (ingestion queue).

## Key Configuration Files

- **`group_vars/k8s.yml`** — Single source of truth for model definitions, replica counts, and queue scaler settings. Playbooks and Helm derive from this.
- **`charts/graphrag/values.yaml`** — Helm values for resource limits, storage sizes, ports, and all service configuration.
- **`inventory.ini`** — Ansible inventory (localhost only).

## Python Services

All Python services use Python 3.12, FastAPI + uvicorn, and asyncpg for PostgreSQL. The ingest worker uses `nats-py`. No shared library — each app has its own `requirements.txt` and `Dockerfile`.

## Workspace Multi-Tenancy

Workspaces provide full data isolation. Resolved from: `workspace` in request body > `X-Workspace` header > `"default"`. Each workspace gets its own Neo4j graph namespace, pgvector partition, and PostgreSQL records.

## Authentication System (`apps/orchestrator/app/auth.py`)

Optional auth layer (disabled by default, `auth_enabled=False` in config). When enabled:
- **Google OIDC** login flow via `apps/orchestrator/app/routes/auth.py`
- **Session cookies** (`graphrag_session`) stored in Redis with configurable TTL
- **API keys** (`grk_` prefix) stored as SHA-256 hashes in PostgreSQL (`auth_users`, `auth_api_keys` tables), with optional rotation/expiry
- Auth dependency `get_current_user` checks cookie → `Bearer` header → returns anonymous if auth disabled
- Domain restriction via `auth_allowed_domain` setting
- UI has login page (`LoginPage.jsx`) and account page (`AccountPage.jsx`) with API key management

## LightRAG Patch System (`apps/lightrag/workspace_patch.py`)

The patch modifies upstream LightRAG behavior through monkey-patching, controlled by env vars:
- `FILETYPE_PROMPTS=1` — per-filetype extraction (code/yaml/config/json/bash/text)
- `LLM_MAX_TOKENS=N` — caps generation length in OpenAI LLM calls
- `TYPED_RELATIONSHIPS=1` — uses extraction keywords as Neo4j relationship types
- `PIPELINED_EMBEDDING=1` — overlaps chunk embedding with entity extraction

## Graph API (`apps/orchestrator/app/routes/graph.py`)

Direct Neo4j queries for the graph explorer UI. `/v1/graph/top` returns top N nodes by relationship count with edges, using workspace as a Neo4j label. Workspace names are sanitized via regex (`^[a-zA-Z0-9_-]+$`) before label interpolation.
