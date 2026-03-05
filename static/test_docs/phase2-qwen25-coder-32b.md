# Phase 2: Qwen2.5-Coder-32B (Q4_K_M GGUF)

- **Model**: Qwen2.5-Coder-32B-Instruct
- **Tag**: `Qwen/Qwen2.5-Coder-32B-Instruct`
- **GGUF**: `bartowski/Qwen2.5-Coder-32B-Instruct-GGUF` → `Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf`
- **Quant**: Q4_K_M (~18.75 GiB loaded)
- **Backend**: vLLM (--dtype half)
- **Embedding**: Qwen3-Embedding-0.6B via vLLM
- **Workspace**: `phase2-qwen25-coder-32b`
- **Test corpus**: `apps/` directory (71 files)
- **Date**: 2026-03-04
- **Patches**: CODE_EXTRACTION_PROMPT=1, LLM_MAX_TOKENS=2048, TYPED_RELATIONSHIPS=1, PIPELINED_EMBEDDING=1
- **MAX_ASYNC**: 8, **LLM_TIMEOUT**: 600

## Status: PARTIAL — Needs full re-run

Ingestion stopped at 24/70 files (~34%) due to slow processing speed (~80-90s/file). Full run estimated at ~100 min. Results below are partial.

### Partial Extraction Quality (24/70 files)

| Metric | Value (partial) | Projected (70 files) |
|---|---|---|
| Total nodes | 131 | ~380 |
| Total relationships | 105 | ~305 |
| LLM requests | 45 | ~130 |
| Prompt tokens | 138,847 | ~405K |
| Generation tokens | 11,295 | ~33K |
| Avg gen tokens/request | ~251 | - |
| Errors | 0 | - |

### Performance (partial)

| Metric | Value |
|---|---|
| Files processed | 24/70 (34%) |
| Elapsed time | ~33 min |
| Avg time per file | ~80-90s |
| Estimated total time | ~100 min |
| Model load size | 18.75 GiB |
| KV cache available | 14.93 GiB |
| Max concurrency | 7.46x at 8K context |
| All finished_reason=stop | Yes (45/45) |
| finished_reason=length | 0 |

### Observations

- **Generation quality is good**: 251 tokens/request — better than Phase 1 (135) but below baseline (500)
- **Speed is the bottleneck**: ~80-90s/file vs 5-8s for Qwen3-8B baseline — roughly 10-15x slower
- **No errors**: 0 aborts, 0 errors, 0 length-truncated — model is stable
- **Projected graph**: extrapolating from 34%, expect ~380 nodes / ~305 rels — competitive with baseline
- **Memory**: 18.75 GiB model + 14.93 GiB KV cache uses most of the 0.30 GPU memory allocation

### TODO

- [ ] Re-run full 70-file ingestion (allow ~100 min)
- [ ] Collect complete Neo4j metrics (nodes, rels, orphans, cross-file, entity/rel type breakdowns)
- [ ] Record final vLLM throughput metrics
- [ ] Compare against Phase 1 and baseline v2

### Previous Run (pre-embedding-pipeline, 2026-03-03)

The previous full run (workspace `benchmark-v2-qwen25-coder-32b`) completed in ~60 min with excellent results:
- 350 nodes, 734 rels, 31 orphans, 400 cross-file rels
- Required LLM_TIMEOUT increase from 180→600 to avoid worker timeouts
- Best results across all benchmarks at the time
