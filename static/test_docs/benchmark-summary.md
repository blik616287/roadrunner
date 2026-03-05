# Extraction Model Benchmark Summary

**Platform**: NVIDIA DGX Spark (ARM64, GB10, 128GB unified memory)
**GPU sharing**: NVIDIA MPS (3 slices: extract, embed, rerank)
**Embedding**: Qwen3-Embedding-0.6B via vLLM (1024-dim)
**Test corpus**: `apps/` directory — 71 source files (Python, JavaScript/JSX, Dockerfiles, configs)
**Pipeline**: LightRAG with CODE_EXTRACTION_PROMPT, TYPED_RELATIONSHIPS, MAX_ASYNC=8
**Date**: 2026-03-04

---

## Top Models

### 1. Fastest: Qwen3-8B BF16 (Baseline)

| | |
|---|---|
| **Model** | Qwen3-8B (BF16, native weights) |
| **Memory** | 15.3 GiB |
| **Wall time** | ~5 min |
| **Avg per file** | ~4.2s |

| Graph Metric | Value |
|---|---|
| Nodes | 300 |
| Relationships | 406 |
| Cross-file rels | 269 |
| Rel types | 27 |
| Entity types | 11 |
| Orphan nodes | 6 (2.0%) |
| UNKNOWN entities | 18 (6.0%) |

**Strengths**:
- Fastest wall time at ~5 min — half the time of any other model
- Strong cross-file linking (269) — second only to Phase 4
- Lowest orphan rate (2.0%) across all models
- Native BF16 weights — no GGUF overhead, clean startup
- Stable: zero errors, zero length-truncated responses

**Weaknesses**:
- Fewer entity types (11) — less granular classification
- USES (107) and DEPENDS_ON (88) dominate — graph is heavy on generic dependency relationships
- CALLS only 34 — doesn't trace function call chains as well as larger models

**Best for**: Production deployment where ingestion speed matters and graph quality is sufficient.

---

### 2. Best Graph Quality: Qwen3-30B-A3B Q4_K_M (Phase 4)

| | |
|---|---|
| **Model** | Qwen3-30B-A3B-Instruct-2507 (Q4_K_M GGUF, MoE) |
| **Memory** | 18.5 GiB |
| **Wall time** | ~10 min |
| **Avg per file** | ~8.6s |

| Graph Metric | Value |
|---|---|
| Nodes | 326 |
| Relationships | 439 |
| Cross-file rels | 256 |
| Rel types | 43 |
| Entity types | 17 |
| Orphan nodes | 15 (4.6%) |
| UNKNOWN entities | 29 (8.9%) |

**Strengths**:
- Most relationships (439) — 8% more than baseline, 62% more than Phase 1
- Most diverse graph (43 rel types) — captures semantic nuances other models miss
- CALLS (79) — 2.3x baseline, excels at tracing function call chains
- RENDERS (13) — unique to this model, captures React component relationships
- ROUTES_TO (6), EXPOSES (4), SUBSCRIBES_TO (1) — captures API and event-driven patterns
- MoE architecture: 30B total params but only 3.3B active per token — quality of a large model at moderate speed

**Weaknesses**:
- 2x slower than baseline (~10 min vs ~5 min)
- Workspace label contamination: 7 entities mistyped as `phase4-run5`
- Requires chat template fix (remove `<think>` block injection for non-thinking 2507 variant)
- MPS contention on startup — must start pods sequentially
- Higher orphan rate (4.6%) than baseline (2.0%)

**Best for**: Maximizing graph quality for codebases where richer entity/relationship extraction justifies the 2x time cost.

---

## Head-to-Head Comparison

| Metric | Qwen3-8B BF16 | Qwen3-30B-A3B Q4_K_M | Delta |
|---|---|---|---|
| **Wall time** | **~5 min** | ~10 min | +100% |
| **Nodes** | 300 | **326** | +8.7% |
| **Relationships** | 406 | **439** | +8.1% |
| **Cross-file rels** | **269** | 256 | -4.8% |
| **Rel types** | 27 | **43** | +59% |
| **Entity types** | 11 | **17** | +55% |
| **Orphan rate** | **2.0%** | 4.6% | +2.6pp |
| **UNKNOWN rate** | **6.0%** | 8.9% | +2.9pp |
| **CALLS rels** | 34 | **79** | +132% |
| **IMPORTS rels** | 73 | **96** | +32% |
| **Model memory** | **15.3 GiB** | 18.5 GiB | +21% |
| **LLM requests** | ~120 | 149 | +24% |
| **Gen tokens/req** | ~500 | ~220 | -56% |
| **Errors** | 0 | 0 | — |
| **Startup complexity** | Simple | Requires sequential pod starts + chat template fix | — |

### Key Takeaways

1. **The 8B baseline is surprisingly competitive.** It produces more cross-file relationships (269 vs 256) and has fewer orphans (2.0% vs 4.6%) than the 30B MoE model. For raw connectivity, the smaller model wins.

2. **The 30B MoE model wins on semantic richness.** 43 relationship types vs 27 means the graph captures more distinct kinds of relationships — CALLS, RENDERS, ROUTES_TO, EXPOSES, SUBSCRIBES_TO are all absent or underrepresented in the baseline.

3. **Speed vs quality is a 2x trade-off.** The 30B model takes exactly twice as long for ~8% more nodes/rels but ~59% more relationship type diversity.

4. **Both models generate concise output.** The 30B model generates fewer tokens per request (220 vs 500) but extracts more entities — suggesting it's more token-efficient at structured extraction.

5. **Operational complexity favors the baseline.** Qwen3-8B BF16 loads natively with zero workarounds. The 30B MoE requires GGUF + dtype half + chat template patching + sequential pod starts.

---

## All Phases Summary

| Phase | Model | Params | Quant | Nodes | Rels | Cross-file | Rel Types | Time | Status |
|---|---|---|---|---|---|---|---|---|---|
| Baseline | Qwen3-8B | 8B dense | BF16 | 300 | 406 | 269 | 27 | ~5 min | **Fastest** |
| 1 | Qwen2.5-Coder-14B | 14B dense | Q4_K_M | 262 | 271 | 139 | 24 | ~5 min | Competitive |
| 2 | Qwen2.5-Coder-32B | 32B dense | Q4_K_M | 131* | 105* | — | — | ~100 min* | Too slow |
| 3 | DeepSeek-Coder-V2-Lite | 16B MoE | Q4_K_M | — | — | — | — | — | GGUF unsupported |
| **4** | **Qwen3-30B-A3B** | **30B MoE** | **Q4_K_M** | **326** | **439** | **256** | **43** | **~10 min** | **Best quality** |
| 5 | Mistral Small 3.1 24B | 24B dense | Q4_K_M | 390 | 365 | 197 | 46 | ~40 min | Poor quality/speed |
| 6 | Nemotron-3-Nano-30B | 30B MoE | NVFP4 | — | — | — | — | — | Deployment impractical |
| 7 | Phi-4 | 14B dense | Q4_K_M | — | — | — | — | — | Gated model |

*Phase 2: partial run (24/70 files)

---

## Recommendation

**Default production model: Qwen3-8B BF16** — fast, simple deployment, excellent cross-file linking, lowest orphan rate.

**Quality-optimized alternative: Qwen3-30B-A3B Q4_K_M** — when graph semantic richness matters more than speed. Best for initial knowledge base construction where the 2x time cost is acceptable.

Both models fit comfortably within a single MPS slice on DGX Spark GB10 with room for the embedding and reranker models.
