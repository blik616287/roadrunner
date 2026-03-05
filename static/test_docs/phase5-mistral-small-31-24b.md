# Phase 5: Mistral Small 3.1 24B (Q4_K_M GGUF)

- **Model**: Mistral-Small-3.1-24B-Instruct-2503
- **GGUF**: `mistralai_Mistral-Small-3.1-24B-Instruct-2503-Q4_K_M.gguf`
- **Quant**: Q4_K_M
- **Backend**: vLLM (--dtype half)
- **Architecture**: Dense 24B
- **Embedding**: Qwen3-Embedding-0.6B via vLLM
- **Workspace**: `phase5-mistral-small`
- **Test corpus**: `apps/` directory (71 files, 70 processed)
- **Date**: 2026-03-04
- **Patches**: CODE_EXTRACTION_PROMPT=1, LLM_MAX_TOKENS=2048, TYPED_RELATIONSHIPS=1, PIPELINED_EMBEDDING=1
- **MAX_ASYNC**: 8, **LLM_TIMEOUT**: 600

## Extraction Quality

| Metric | Value | vs Baseline v2 (Qwen3-8B) | vs Phase 4 (Qwen3-30B-A3B) |
|---|---|---|---|
| Total nodes | 390 | 139 (+181%) | 326 (+20%) |
| Total relationships | 365 | 151 (+142%) | 439 (-17%) |
| Orphan nodes | 46 (11.8%) | 5 (3.6%) | 15 (4.6%) |
| Unique relationship types | 46 | 20 | 43 |
| Unique entity types | 18 | 15 | 17 |
| Cross-file relationships | 197 | 111 (+78%) | 256 (-23%) |

### Relationship Type Breakdown

| Type | Count |
|---|---|
| CONTAINS | 89 |
| IMPORTS | 64 |
| DEPENDS_ON | 44 |
| CALLS | 35 |
| USES | 26 |
| EXTENDS | 26 |
| DEFINES | 14 |
| DEFINED_IN | 8 |
| CONFIGURES | 6 |
| IMPLEMENTS | 6 |
| INSTANTIATES | 3 |
| RETURNS | 3 |
| ACCEPTS | 2 |
| TAKES_AS_INPUT | 2 |
| REQUIRES | 2 |
| DECLARES | 2 |
| PUBLISHES_TO | 2 |
| PROXY_PASS | 2 |
| ADJUSTS | 2 |
| INITIALIZES_WITH | 1 |
| RESIDES_IN | 1 |
| RUNS | 1 |
| LINKS | 1 |
| REMOVES | 1 |
| REPLACES | 1 |
| LOADS | 1 |
| COMMUNICATES_WITH | 1 |
| DEFINED | 1 |
| BELONGS_TO | 1 |
| POLL | 1 |
| WRAPS | 1 |
| DISPLAYS | 1 |
| RESTRICTS_NON_RATIONAL_VERTICES | 1 |
| FALLBACK | 1 |
| CACHES | 1 |
| INITIALIZES | 1 |
| LOGS | 1 |
| DEFINED_BY | 1 |
| IMPORT | 1 |
| PROCS | 1 |
| BUILDS_ON | 1 |
| RUNS_WITH | 1 |
| COPIES | 1 |
| SPECIFIES | 1 |
| INHERITS | 1 |
| USES_IN_MEMORY | 1 |

### Entity Type Breakdown

| Type | Count |
|---|---|
| function | 134 |
| UNKNOWN | 67 |
| module | 48 |
| class | 36 |
| package | 35 |
| service | 18 |
| artifact | 11 |
| configuration | 9 |
| component | 8 |
| data | 6 |
| variable | 5 |
| api | 5 |
| service. | 3 |
| concept | 1 |
| hook | 1 |
| language | 1 |
| configuration. | 1 |
| interface. | 1 |

## Performance

| Metric | Value | vs Baseline v2 |
|---|---|---|
| Files processed | 70 | 71 |
| Total processing time | ~40 min | ~5 min (8x slower) |
| Avg time per file | ~34s | ~4.2s |
| Total LLM requests | 142 | ~120 |
| Avg latency per request | 121.5s | ~5-6s |
| Total prompt tokens | 436,014 | - |
| Total generation tokens | 43,191 | - |
| Avg gen tokens/request | ~304 | ~500 |
| Errors | 0 | 0 |
| finished_reason=length | 0 | 0 |
| Ingest worker poll timeout | Yes | No |

## Stability

| Metric | Value |
|---|---|
| OOM crashes | No |
| MPS contention on startup | No (sequential start from prior phase) |
| All finished_reason=stop | Yes (142/142) |
| Ingest worker timeout | Yes (poll timed out before LightRAG finished) |
| Entity extraction warnings | Yes (invalid entity type format: trailing periods) |

## Issues Encountered

1. **Extremely slow inference**: Avg 121.5s per LLM request — 20x slower than Qwen3-8B BF16 and 1.3x slower than Qwen2.5-Coder-32B. The dense 24B architecture at Q4_K_M quantization is very slow on a single MPS slice.

2. **Ingest worker poll timeout**: The job took so long (~40 min) that the ingest-worker's 600s ack timeout fired. LightRAG continued processing in the background after the worker marked the job as "completed anyway". All 70 files did eventually complete.

3. **Invalid entity type format**: Some entity types have trailing periods (`service.`, `configuration.`, `interface.`) — Mistral's output formatting occasionally appends punctuation to type labels. 67 UNKNOWN entities (17.2%) suggests the model frequently fails to classify entities into the expected types.

4. **High CONTAINS ratio**: 89 CONTAINS relationships (24.4% of all rels) is the highest of any model. This suggests Mistral favors generic containment relationships over more specific semantic ones (CALLS, USES, etc.).

## Analysis

### High node count, mediocre graph connectivity

- **390 nodes** — highest of any benchmark, but 46 orphans (11.8%) means many extracted entities have no relationships
- **365 relationships** — lower than Phase 4 (439) despite more nodes, giving a poor nodes-to-rels ratio of 1.07 (vs Phase 4's 1.35)
- **197 cross-file rels** — significantly less cross-file linking than Phase 4 (256) and baseline (269 after pipelining)

### Relationship quality concerns

- **CONTAINS dominates** (89, 24.4%) — generic containment is the most common relationship, suggesting the model defaults to hierarchical relationships rather than semantic ones
- **CALLS only 35** (9.6%) — compared to Phase 4's 79 (18%), Mistral struggles to trace function call chains
- **46 unique rel types** — most diverse, but many are noise (RESTRICTS_NON_RATIONAL_VERTICES, PROCS, USES_IN_MEMORY) or duplicates (IMPORT vs IMPORTS, DEFINED vs DEFINED_IN vs DEFINED_BY)

### Speed is the dealbreaker

- **~40 min total** — 8x slower than baseline, 4x slower than Phase 4
- **121.5s avg per request** — with MAX_ASYNC=8, only ~4 requests complete per minute
- Dense 24B Q4_K_M on a single MPS slice is severely compute-bound
- The ingest worker poll timeout means this model exceeds the pipeline's designed processing window

### Verdict

**Not recommended.** While Mistral Small 3.1 24B produces the most nodes (390), the graph quality is poor: high orphan rate (11.8%), low relationship density (1.07 rels/node), excessive CONTAINS relationships, weak cross-file linking, and many UNKNOWN entities (17.2%). Combined with extremely slow inference (8x baseline, 121.5s/request), this model offers worse quality than Phase 4 (Qwen3-30B-A3B) at 4x the time cost. The dense 24B architecture is a poor fit for single MPS slice deployment on GB10.
