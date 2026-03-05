# Baseline: Qwen3-8B (BF16)

- **Model**: Qwen3-8B
- **Tag**: `Qwen/Qwen3-8B`
- **Quant**: BF16 (~16 GB)
- **Backend**: vLLM
- **Workspace**: `benchmark-qwen3-8b`
- **Test corpus**: `apps/` directory (70 files, 408K)
- **Date**: 2026-03-03

## Extraction Quality

| Metric | Value |
|---|---|
| Total nodes | 283 |
| Total relationships | 291 |
| Orphan nodes | 17 (6%) |
| Unique entity types | 15 |
| Unique label combinations | 42 |
| Relationship types | 1 (DIRECTED only) |
| Cross-file relationships | 0 |

### Entity Type Breakdown

| Type | Count |
|---|---|
| method | 86 |
| function | 64 |
| data | 41 |
| artifact | 34 |
| concept | 25 |
| class | 20 |
| UNKNOWN | 18 |
| library | 10 |
| event | 7 |
| location | 7 |
| page | 6 |
| content | 4 |
| organization | 3 |
| system | 2 |
| software | 2 |

## Performance

| Metric | Value |
|---|---|
| Files processed | 70 |
| Total ingestion time | ~17.5 min |
| Wall-clock per file (avg) | ~15s |
| Avg generation throughput | 40–51 tok/s |
| Avg prompt throughput | 1–387 tok/s (bursty, prefix cache) |
| Prefix cache hit rate | 84.6% |
| KV cache usage | 3.0–4.6% |
| Running requests (steady) | 4 |

## Stability

| Metric | Value |
|---|---|
| GPU utilization | 96% (constant) |
| System memory | 64 GiB / 122 GiB (52%) — stable |
| Power draw | 27–35W (spikes during merge) |
| OOM crashes | No |
| Burst mode triggered | No |
| All jobs completed without retries | Yes |

## Notes

- Only one relationship type (`DIRECTED`) — extraction prompt does not produce typed relationships
- No cross-file relationships detected (`source_file` property not set on nodes)
- 18 UNKNOWN entity types (6.4%) — extraction sometimes fails to classify
- GPU well-utilized at 96% but generation throughput moderate at ~50 tok/s
- Memory headroom excellent — 52% usage with Conservative tuning profile
