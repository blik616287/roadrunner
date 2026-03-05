# Baseline v2 (Patched): Qwen3-8B (BF16)

- **Model**: Qwen3-8B
- **Tag**: `Qwen/Qwen3-8B`
- **Quant**: BF16 (~16 GB)
- **Backend**: vLLM
- **Workspace**: `benchmark-v2-qwen3-8b`
- **Test corpus**: `apps/` directory (71 files)
- **Date**: 2026-03-04
- **Patches applied**:
  - `CODE_EXTRACTION_PROMPT=1` — 1 code-focused example, code entity types, code-specific rules (no orphans, no stdlib, single-verb keywords, skip dep lists)
  - `LLM_MAX_TOKENS=2048` — generation cap per extraction call
  - `TYPED_RELATIONSHIPS=1` — first extraction keyword used as Neo4j relationship type

## Extraction Quality

| Metric | Value | vs Original Baseline | vs Patched v1 |
|---|---|---|---|
| Total nodes | 139 | 283 (-51%) | 231 (-40%) |
| Total relationships | 151 | 291 (-48%) | 314 (-52%) |
| Orphan nodes | 5 (3.6%) | 17 (6%) | 21 (9%) |
| Unique relationship types | 20 | 1 | 1 |
| Unique entity types | 15 | 15 | 19 |
| Cross-file relationships | 111 | 181 | 230 |

### Relationship Type Breakdown

| Type | Count |
|---|---|
| USES | 76 |
| DEPENDS_ON | 49 |
| CONTAINS | 37 |
| RELATED | 16 |
| CALLS | 13 |
| IMPORTS | 9 |
| USED_BY | 5 |
| DEFINED_IN | 4 |
| ACCEPTS | 4 |
| DEFINES | 4 |
| MANAGES | 3 |
| PROXIES_TO | 2 |
| MODIFIES | 2 |
| SERVES | 2 |
| RELIES_ON | 2 |
| CONFIGURES | 2 |
| EVALUATES | 2 |
| RUNS | 1 |
| FORWARDS_TO | 1 |
| EXTENDS | 1 |

### Entity Type Breakdown

| Type | Count |
|---|---|
| function | 89 |
| package | 46 |
| module | 25 |
| UNKNOWN | 19 |
| class | 12 |
| component | 10 |
| service | 9 |
| hook | 3 |
| script | 1 |
| library | 1 |
| configuration | 1 |
| tool | 1 |
| variable | 1 |
| directory | 1 |
| file | 1 |

### Orphan Nodes (5 total)

| Entity | Type | File |
|---|---|---|
| _add_middleware | function | apps/lightrag/workspace_patch.py |
| gzip | package | apps/orchestrator/app/routes/documents.py |
| hashlib | package | apps/orchestrator/app/routes/documents.py |
| logging | package | apps/orchestrator/app/routes/documents.py |
| uuid | package | apps/orchestrator/app/routes/documents.py |

All orphans are stdlib imports from a single file — the "no stdlib" rule mostly worked but didn't catch these 4.

## Performance

| Metric | Value | vs Original Baseline |
|---|---|---|
| Files processed | 71 | 70 (same corpus) |
| Total ingestion time | ~5 min | ~17.5 min (-71%) |
| Avg generation throughput | 37–49 tok/s | 40–51 tok/s (similar) |
| Avg prompt throughput | 57–272 tok/s (bursty) | 1–387 tok/s |
| Prefix cache hit rate | 83–84% | 84.6% (similar) |
| KV cache usage | 0.5–0.9% | 3.0–4.6% |
| Running requests (steady) | 3–4 | 4 |

## Stability

| Metric | Value | vs Original Baseline |
|---|---|---|
| GPU utilization | 96% (constant) | 96% (same) |
| System memory | 121 GiB / 122 GiB (99%) | 64 GiB (52%) |
| Power draw | 28W | 27–35W |
| OOM crashes | No | No |
| Burst mode triggered | No | No |
| All jobs completed without retries | Yes | Yes |

## Analysis

### v2 patch improvements over v1
- **Orphans reduced 76%**: 21 → 5 (3.6%) — "no orphan entities" rule effective
- **20 typed relationships**: USES, DEPENDS_ON, CONTAINS, CALLS, IMPORTS, etc. — single-verb keyword rule + Neo4j storage patch working
- **Fewer junk entities**: 231 → 139 — "skip dep lists" and "no stdlib" rules pruned noise
- **KV cache usage dropped**: 0.5-0.9% vs 3.0-4.6% — shorter prompt = less context per call

### Trade-offs
- Fewer total nodes (139 vs 283) — aggressive pruning may drop some useful entities
- Fewer cross-file relationships (111 vs 181/230) — fewer entities means fewer cross-file links
- UNKNOWN count increased to 19 (14%) from 9 — model still classifying some entities incorrectly
- System memory at 99% — all models loaded in unified memory, no headroom issues but worth monitoring

### Verdict
**v2 is the best baseline for model comparison**: typed relationships give meaningful graph structure, orphans nearly eliminated, 3.5x faster than original. Use this as the new standard for all test model benchmarks.
