# Baseline (Patched): Qwen3-8B (BF16)

- **Model**: Qwen3-8B
- **Tag**: `Qwen/Qwen3-8B`
- **Quant**: BF16 (~16 GB)
- **Backend**: vLLM
- **Workspace**: `benchmark-patched-qwen3-8b`
- **Test corpus**: `apps/` directory (70 files, 408K)
- **Date**: 2026-03-04
- **Patches applied**:
  - `CODE_EXTRACTION_PROMPT=1` — 1 code-focused example (vs 3 generic), code entity types
  - `LLM_MAX_TOKENS=2048` — generation cap per extraction call

## Extraction Quality

| Metric | Value | vs Original Baseline |
|---|---|---|
| Total nodes | 231 | 283 (-18%) |
| Total relationships | 314 | 291 (+8%) |
| Orphan nodes | 21 (9%) | 17 (6%) |
| Unique entity types | 19 | 15 (+4) |
| Relationship types | 1 (DIRECTED only) | 1 (same) |
| Cross-file relationships | 0 | 0 (same) |

### Entity Type Breakdown

| Type | Count |
|---|---|
| function | 123 |
| module | 46 |
| package | 38 |
| class | 29 |
| component | 17 |
| service | 9 |
| UNKNOWN | 9 |
| library | 8 |
| file | 4 |
| hook | 3 |
| data | 3 |
| directory | 2 |
| configuration | 2 |
| script | 1 |
| tool | 1 |
| artifact | 1 |
| framework | 1 |
| other | 1 |
| variable | 1 |

## Performance

| Metric | Value | vs Original Baseline |
|---|---|---|
| Files processed | 70 | 70 (same) |
| Total ingestion time | ~5 min | ~17.5 min (-71%) |
| Avg generation throughput | 45 tok/s | 40-51 tok/s (similar) |
| Prefix cache hit rate | 82.7% | 84.6% (similar) |
| KV cache usage | 3.3% | 3.0-4.6% (similar) |
| Running requests (steady) | 4 | 4 (same) |

## Analysis

### Prompt patch effects
- **3.5x faster ingestion**: Fewer examples (1 vs 3) means shorter system prompt, fewer input tokens per call, faster LLM responses
- **More relationships per node**: 314/231 = 1.36 rels/node vs 291/283 = 1.03 rels/node — code example teaches the model to create richer relationship networks
- **Code-relevant entity types**: New types emerged: module (46), package (38), component (17), service (9), configuration (2), hook (3), directory (2), variable (1), script (1), tool (1)
- **Fewer total nodes**: max_tokens=2048 cap may truncate some extractions, or the code example teaches tighter entity extraction
- **Slightly more orphans**: 9% vs 6%, but absolute count similar (21 vs 17)

### Trade-offs
- Fewer total nodes but more meaningful relationships — net positive for graph quality
- `function` type dominates (53% of nodes) — appropriate for code-heavy corpus
- Original generic types like `method` (86→0), `concept` (25→0), `event` (7→0), `location` (7→0) replaced by code types — confirms entity type override is working
- UNKNOWN count reduced from 18 to 9 (50% improvement)

### Verdict
**Patched prompt is a clear improvement for code extraction**: 3.5x faster, denser relationship graph, code-relevant entity types, fewer unknowns. Use as new baseline for model comparison.
