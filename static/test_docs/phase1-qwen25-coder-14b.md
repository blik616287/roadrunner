# Phase 1: Qwen2.5-Coder-14B (Q4_K_M GGUF)

- **Model**: Qwen2.5-Coder-14B-Instruct
- **Tag**: `Qwen/Qwen2.5-Coder-14B-Instruct`
- **GGUF**: `bartowski/Qwen2.5-Coder-14B-Instruct-GGUF` → `Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf`
- **Quant**: Q4_K_M (~8.58 GiB loaded)
- **Backend**: vLLM (--dtype half)
- **Test corpus**: `apps/` directory (71 files)

## Run 3 — Embedding Pipeline + MAX_ASYNC=8 (2026-03-04)

- **Workspace**: `phase1-qwen25-coder-14b`
- **Patches**: CODE_EXTRACTION_PROMPT=1, LLM_MAX_TOKENS=2048, TYPED_RELATIONSHIPS=1, PIPELINED_EMBEDDING=1
- **Embedding**: Qwen3-Embedding-0.6B via vLLM (replaced Ollama)
- **MAX_ASYNC**: 8

### Extraction Quality

| Metric | Value | vs Baseline v2 (Qwen3-8B BF16) |
|---|---|---|
| Total nodes | 262 | 139 (+89%) |
| Total relationships | 271 | 151 (+79%) |
| Orphan nodes | 13 (5.0%) | 5 (3.6%) |
| Unique relationship types | 24 | 20 |
| Unique entity types | 18 | 15 |
| Cross-file relationships | 139 | 111 (+25%) |

#### Relationship Type Breakdown

| Type | Count |
|---|---|
| IMPORTS | 96 |
| CONTAINS | 55 |
| EXTENDS | 24 |
| USES | 23 |
| DEPENDS_ON | 20 |
| CALLS | 15 |
| DEFINES | 7 |
| CONTAINED_IN | 5 |
| PATCHES | 4 |
| TAKES | 4 |
| RETURNS | 3 |
| MANAGES | 3 |
| PROXIES_TO | 2 |
| CACHES | 1 |
| INGESTS | 1 |
| QUEUES | 1 |
| HANDLES | 1 |
| INJECTS | 1 |
| ADDS | 1 |
| OVERLAPS | 1 |
| CREATES | 1 |
| UTILIZES | 1 |
| INSTANTIATES | 1 |
| MODIFIES | 1 |

#### Entity Type Breakdown

| Type | Count |
|---|---|
| UNKNOWN | 60 |
| function | 59 |
| module | 46 |
| class | 34 |
| package | 18 |
| service | 9 |
| component | 8 |
| library | 7 |
| page | 6 |
| concept | 4 |
| phase1-qwen25-coder-14b | 2 |
| data | 2 |
| variable | 2 |
| artifact | 1 |
| tool | 1 |
| hook | 1 |
| api | 1 |
| configuration | 1 |

### Performance

| Metric | Value | vs Baseline v2 |
|---|---|---|
| Files processed | 71 | 71 (same) |
| Total LLM requests | 143 | ~120 (similar) |
| Total prompt tokens | 392,536 | - |
| Total generation tokens | 19,276 | - |
| Avg generation tokens/request | ~135 | ~500 (lower) |
| Errors | 0 | 0 |
| Job wall time (orchestrator) | ~5 min | ~5 min (same) |

### Stability

| Metric | Value |
|---|---|
| OOM crashes | No |
| Errors | 0 |
| All finished_reason=stop | Yes (143/143) |
| finished_reason=length | 0 |

---

## Run 2 — v2 Patches (2026-03-04)

- **Workspace**: `benchmark-v2-qwen25-coder-14b`
- **Patches**: CODE_EXTRACTION_PROMPT=1, LLM_MAX_TOKENS=2048, TYPED_RELATIONSHIPS=1

### Extraction Quality

| Metric | Value | vs Baseline v2 (Qwen3-8B BF16) |
|---|---|---|
| Total nodes | 20 | 139 (-86%) |
| Total relationships | 30 | 151 (-80%) |
| Orphan nodes | 1 (5%) | 5 (3.6%) |
| Unique relationship types | 4 | 20 (-80%) |
| Unique entity types | 10 | 15 (-33%) |
| Cross-file relationships | 6 | 111 (-95%) |

#### Relationship Type Breakdown

| Type | Count |
|---|---|
| IMPORTS | 26 |
| USES | 4 |
| CALLS | 2 |
| CONTAINS | 2 |

#### Entity Type Breakdown

| Type | Count |
|---|---|
| UNKNOWN | 5 |
| package | 3 |
| function | 3 |
| hook | 3 |
| component | 3 |
| artifact | 2 |
| service | 1 |
| library | 1 |
| class | 1 |
| module | 1 |

### Performance

| Metric | Value | vs Baseline v2 |
|---|---|---|
| Files processed | 71 | 71 (same) |
| Total LLM requests | 30 | ~120+ (much fewer) |
| Total prompt tokens | 89,302 | similar |
| Total generation tokens | 2,408 | ~60K+ (-96%) |
| Avg generation tokens/request | ~80 | ~500+ (-84%) |
| Prefix cache hit rate | 86.6% | 83-84% (similar) |
| System memory | 61 GiB / 119 GiB (51%) | 61 GiB (same) |

---

## Run 1 — Pre-v2 Patches (2026-03-03)

- **Workspace**: `benchmark-qwen25-coder-14b`
- **Patches**: None (original baseline config, all rels DIRECTED)

### Extraction Quality

| Metric | Value | vs Original Baseline |
|---|---|---|
| Total nodes | 151 | 283 (-47%) |
| Total relationships | 81 | 291 (-72%) |
| Orphan nodes | 68 (45%) | 17 (6%) |
| Unique entity types | 15+ | 15 (same) |
| Relationship types | 1 (DIRECTED only) | 1 (same) |
| Cross-file relationships | 0 | 0 (same) |

### Performance

| Metric | Value | vs Original Baseline |
|---|---|---|
| Total ingestion time | ~33 min | ~17.5 min (+89%) |
| Avg generation throughput | 3–22 tok/s | 40–51 tok/s |
| Model load size | 8.58 GiB | 15.3 GiB |

---

## Analysis

### Run 3 is a massive improvement over Run 2

Run 2 (v2 patches only): 20 nodes, 30 rels — model barely generated output (~80 tok/req).
Run 3 (embedding pipeline + MAX_ASYNC=8): 262 nodes, 271 rels, 139 cross-file — competitive with baseline.

The difference is likely due to the LightRAG instance state (fresh restart, new embedding tables) rather than the embedding pipeline itself, since extraction is the same LLM. The model now generates ~135 tokens/request — still below baseline (~500) but enough for meaningful extraction.

### Quality vs Baseline v2

- **89% more nodes** (262 vs 139) and **79% more relationships** (271 vs 151)
- **25% more cross-file relationships** (139 vs 111)
- **24 relationship types** vs 20 — good diversity
- **IMPORTS dominant** (96) — code-specialist bias toward import tracking
- **UNKNOWN entities high** (60, 23%) vs baseline (19, 14%) — weaker entity typing
- **Workspace label leak**: 2 entities typed as `phase1-qwen25-coder-14b` — model confused workspace name with entity type
- **Orphan rate higher**: 5.0% vs 3.6% — more entities created without connecting them

### Verdict

**COMPETITIVE** — Run 3 produces a richer graph than baseline v2 in raw counts. However:
- High UNKNOWN rate (23%) suggests weaker instruction following for entity typing
- Lower tokens/request (135 vs 500) means less detailed extraction per file
- Workspace label contamination is a model-specific bug
- 8.58 GiB model footprint (~half of baseline) is a significant memory advantage
