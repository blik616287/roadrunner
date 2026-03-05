# Phase 4: Qwen3-30B-A3B (Q4_K_M GGUF, Non-Thinking 2507)

- **Model**: Qwen3-30B-A3B-Instruct-2507
- **Tag**: `Qwen/Qwen3-30B-A3B`
- **GGUF**: `unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF` → `Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf`
- **Quant**: Q4_K_M (~18.5 GiB loaded)
- **Backend**: vLLM (--dtype half)
- **Architecture**: MoE (30.5B total, 3.3B active per token)
- **Embedding**: Qwen3-Embedding-0.6B via vLLM
- **Workspace**: `phase4-run5`
- **Test corpus**: `apps/` directory (71 files, 70 processed)
- **Date**: 2026-03-04
- **Patches**: CODE_EXTRACTION_PROMPT=1, LLM_MAX_TOKENS=2048, TYPED_RELATIONSHIPS=1, PIPELINED_EMBEDDING=1
- **MAX_ASYNC**: 8, **LLM_TIMEOUT**: 600
- **Chat template fix**: Removed `<think>` block injection from generation prompt (caused empty responses on initial runs)

## Extraction Quality

| Metric | Value | vs Baseline v2 (Qwen3-8B) | vs Phase 1 (Coder-14B) |
|---|---|---|---|
| Total nodes | 326 | 139 (+135%) | 262 (+24%) |
| Total relationships | 439 | 151 (+191%) | 271 (+62%) |
| Orphan nodes | 15 (4.6%) | 5 (3.6%) | 13 (5.0%) |
| Unique relationship types | 43 | 20 | 24 |
| Unique entity types | 17 | 15 | 18 |
| Cross-file relationships | 256 | 111 (+131%) | 139 (+84%) |

### Relationship Type Breakdown

| Type | Count |
|---|---|
| IMPORTS | 96 |
| CALLS | 79 |
| USES | 58 |
| CONTAINS | 45 |
| DEPENDS_ON | 28 |
| DEFINES | 21 |
| RENDERS | 13 |
| EXTENDS | 9 |
| INSTALLS | 8 |
| DEFINED_IN | 8 |
| ROUTES_TO | 6 |
| TAKES | 5 |
| RETURNS | 5 |
| RECEIVES | 4 |
| ACCEPTS | 4 |
| EXPOSES | 4 |
| QUERIES | 3 |
| COPIES | 3 |
| CONFIGURES | 3 |
| CHECKS | 2 |
| CONFIGURED_BY | 2 |
| MIGRATES | 2 |
| INSTALL_REQUIRES | 2 |
| PROXIES_TO | 2 |
| SETS | 2 |
| UPDATES | 2 |
| UNDEFINED | 1 |
| TAKES_PARAMETER | 1 |
| CLOSES | 1 |
| RETRIEVES | 1 |
| RUNS_ON | 1 |
| EXTRACTS | 1 |
| DEFAULTS_TO | 1 |
| SUBSCRIBES_TO | 1 |
| POLLS | 1 |
| CREATES | 1 |
| MODIFIES | 1 |
| ADDS | 1 |
| INITIATES | 1 |
| TRACKS | 1 |
| HANDLES | 1 |
| MANAGES | 1 |
| TRANSFORMS | 1 |
| SENDS | 1 |
| FORWARDS | 1 |
| SERVES | 1 |
| PRODUCES | 1 |
| READS | 1 |
| RUNS | 1 |

### Entity Type Breakdown

| Type | Count |
|---|---|
| function | 116 |
| module | 51 |
| class | 30 |
| UNKNOWN | 29 |
| package | 28 |
| configuration | 12 |
| variable | 10 |
| service | 8 |
| component | 7 |
| data | 7 |
| phase4-run5 | 7 |
| page | 6 |
| artifact | 5 |
| library | 5 |
| image | 2 |
| plugin | 2 |
| tool | 1 |

## Performance

| Metric | Value | vs Baseline v2 |
|---|---|---|
| Files processed | 70 | 71 |
| Total processing time | ~10 min | ~5 min |
| Avg time per file | ~8.6s | ~4.2s |
| Total LLM requests | 149 | ~120 |
| Total prompt tokens | 414,652 | - |
| Total generation tokens | 32,727 | - |
| Avg gen tokens/request | ~220 | ~500 |
| Errors | 0 | 0 |
| finished_reason=length | 0 | 0 |
| Model load size | ~18.5 GiB | 15.3 GiB |

## Stability

| Metric | Value |
|---|---|
| OOM crashes | No |
| MPS contention on startup | Yes (required sequential pod starts) |
| All finished_reason=stop | Yes (149/149) |
| Chat template fix required | Yes (empty responses with `<think>` block injection) |

## Issues Encountered

1. **MPS contention**: When all 3 vLLM pods (extract, embed, rerank) restarted simultaneously, MPS error 807 ("server not ready") caused all to crash. Fixed by scaling down embed/rerank, starting extract first, then bringing others up sequentially.

2. **Empty responses**: The chat template injected `<think>\n\n</think>` to suppress thinking, but the 2507 non-thinking variant doesn't use think blocks. This caused empty content responses for some documents. Fixed by changing generation prompt to plain `<|im_start|>assistant\n`.

3. **Stale configmap**: LightRAG pod kept old model name (`deepseek-coder-v2-lite-extract`) after helm upgrade. Required explicit pod restart to pick up new configmap.

## Analysis

### Best graph quality so far

- **439 relationships** — highest of any benchmark (baseline v2: 151, Phase 1: 271)
- **43 unique relationship types** — most diverse semantic graph (baseline v2: 20, Phase 1: 24)
- **CALLS (79)** is very high — MoE model excels at tracing function call chains
- **RENDERS (13)** — unique to this model, captures React component rendering relationships
- **ROUTES_TO (6)**, **EXPOSES (4)**, **SUBSCRIBES_TO (1)** — captures API/event patterns

### Weaknesses

- **UNKNOWN entities**: 29 (8.9%) — better than Phase 1 (23%) but worse than baseline (14%)
- **Workspace label contamination**: 7 entities typed as `phase4-run5` — same model-specific bug as Phase 1
- **Orphan rate**: 4.6% — higher than baseline (3.6%)
- **Speed**: ~10 min (2x baseline) — MoE overhead despite only 3.3B active params
- **Lower tokens/request**: 220 vs baseline 500 — more concise but still effective

### MoE characteristics

Despite loading 18.5 GiB of parameters (30B total), only 3.3B are active per token. This means:
- Higher memory footprint than equivalent dense model
- Token generation speed comparable to a ~3B dense model (fast per token, but overhead from expert routing)
- Quality benefits from having specialized experts for different extraction patterns

### Verdict

**Best extraction quality across all benchmarks.** 326 nodes, 439 rels, 43 relationship types, 256 cross-file — significantly outperforms all previous models. The MoE architecture seems well-suited for entity extraction with its diverse expert routing. Main concerns are startup complexity (MPS contention), chat template requirements, and 2x speed penalty vs baseline. Memory footprint (18.5 GiB) is comparable to Qwen3-8B BF16 (15.3 GiB).
