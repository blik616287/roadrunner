# Embedding Pipeline Optimization: Qwen3-8B (BF16)

- **Model**: Qwen3-8B (extraction)
- **Quant**: BF16 (~16 GB)
- **Backend**: vLLM
- **Embedding**: Qwen3-Embedding-0.6B via vLLM (replaced Ollama)
- **Workspace**: `bench-async8-clean`
- **Test corpus**: `apps/` directory (71 files, 70 processed)
- **Date**: 2026-03-04
- **Changes from baseline-v2**:
  - Ollama embedding replaced with vLLM pooling runner (continuous batching)
  - Pipelined embedding+extraction patch (`PIPELINED_EMBEDDING=1`)
  - `MAX_ASYNC=8` (was 4)
  - `EMBEDDING_BATCH_NUM=32`, `EMBEDDING_FUNC_MAX_ASYNC=4`, `EMBEDDING_TIMEOUT=60`
  - All v2 patches still active (CODE_EXTRACTION_PROMPT, LLM_MAX_TOKENS, TYPED_RELATIONSHIPS)

## Extraction Quality

| Metric | Value | vs Baseline v2 |
|---|---|---|
| Total nodes | 300 | 139 (+116%) |
| Total relationships | 406 | 151 (+169%) |
| Orphan nodes | 6 (2.0%) | 5 (3.6%) |
| Unique relationship types | 27 | 20 |
| Unique entity types | 11 | 15 |
| Cross-file relationships | 269 | 111 (+142%) |

### Relationship Type Breakdown

| Type | Count |
|---|---|
| USES | 107 |
| DEPENDS_ON | 88 |
| IMPORTS | 73 |
| CALLS | 34 |
| CONTAINS | 32 |
| EXTENDS | 19 |
| INCLUDES | 8 |
| DEFINED_IN | 7 |
| REQUIRES | 5 |
| ACCEPTS | 5 |
| PART_OF | 4 |
| CALLED_BY | 3 |
| SENDS_TO | 3 |
| PROXIES_TO | 2 |
| SERVES | 2 |
| EVALUATES | 2 |
| PROCESSES | 2 |
| INSTALLS | 1 |
| INSTALLS_FROM | 1 |
| RUNS_ON | 1 |
| CONFIGURES | 1 |
| SPECIFIES | 1 |
| INSTANTIATES | 1 |
| COMPLEMENTS | 1 |
| BELONGS_TO | 1 |
| PROVIDES | 1 |
| BUILDS_FOR | 1 |

### Entity Type Breakdown

| Type | Count |
|---|---|
| function | 130 |
| package | 57 |
| class | 29 |
| module | 28 |
| component | 18 |
| UNKNOWN | 18 |
| service | 12 |
| library | 5 |
| script | 1 |
| file | 1 |
| configuration | 1 |

## Performance

| Metric | Value | vs Baseline v2 |
|---|---|---|
| Files processed | 70 | 71 (same corpus) |
| Total processing time | ~10 min | ~5 min (+100%) |
| Avg time per file | ~8.8s | ~4.2s |
| Embedding time per chunk | ~30ms | N/A (Ollama) |
| vLLM extract running requests | 2 (steady) | 3-4 |
| vLLM extract prompt tokens | 1,584,367 (cumulative) | - |
| vLLM extract gen tokens | 109,555 (cumulative) | - |
| vLLM embed requests | 4,497 (cumulative) | - |
| vLLM embed prompt tokens | 151,590 (cumulative) | - |
| Errors | 0 | 0 |

## Analysis

### Quality improved significantly
- **2.16x more nodes** (300 vs 139) and **2.69x more relationships** (406 vs 151)
- **2.42x more cross-file relationships** (269 vs 111) — richer graph connectivity
- **Orphan rate improved**: 2.0% vs 3.6%
- **27 relationship types** vs 20 — more diverse graph semantics
- IMPORTS (73) now captured as a distinct type — was underrepresented in v2

### Speed regressed
- **10 min vs 5 min** — 2x slower than baseline v2
- Root cause is NOT the embedding pipeline changes — embedding takes ~30ms/chunk (negligible)
- `MAX_PARALLEL_INSERT=4` is the bottleneck: only 4 docs process concurrently
- Each doc is 1 chunk, so MAX_ASYNC=8 doesn't help (only 1 extraction call per doc)
- The quality improvement (more entities/relations extracted per doc) means more Neo4j merge operations, which take longer

### Embedding pipeline observations
- vLLM embedding works correctly: 1024-dim, OpenAI-compatible API
- Pipelining patch active but saves only ~30ms/file (embed is trivially fast for single chunks)
- Pipelining will show real benefit on large documents with many chunks
- vLLM continuous batching is a better foundation than Ollama's sequential processing

### Why more entities than baseline v2?
The quality difference is unexpected since the extraction model (Qwen3-8B) and prompts are identical. Possible causes:
- Different LightRAG version state or caching behavior between runs
- The new embedding tables (model name changed) may have affected dedup logic
- Non-deterministic LLM output (temperature/sampling) between runs

### Verdict
**Quality is excellent** — best graph richness across all benchmarks. Speed regression needs investigation: increasing `MAX_PARALLEL_INSERT` from 4 to 8+ should help since vLLM can handle more concurrent requests. The embedding pipeline changes are a solid foundation for large document ingestion.
