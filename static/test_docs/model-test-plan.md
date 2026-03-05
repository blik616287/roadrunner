# Roadrunner Extraction Model Test Plan

## Environment

- **Hardware:** NVIDIA DGX Spark (ARM64, GB10, 128 GB unified memory)
- **Pipeline:** Roadrunner GraphRAG — tree-sitter → LLM extraction → LightRAG → Neo4j
- **Current model:** Qwen3-8B (BF16, ~16 GB) via vLLM
- **Config file:** `group_vars/k8s.yml` → `models.extract.tag`
- **Test workspace:** Pick one repo with 50–100 files (mixed classes, utilities, cross-file imports)

## Models to Test

### Code-Specialist Models

| Phase    | Model                  | Tag                                           | Quant  | VRAM     | Notes                                            |
| -------- | ---------------------- | --------------------------------------------- | ------ | -------- | ------------------------------------------------ |
| Baseline | Qwen3-8B               | `Qwen/Qwen3-8B`                               | BF16   | ~16 GB   | Current production model                         |
| 1        | Qwen2.5-Coder-14B      | `Qwen/Qwen2.5-Coder-14B-Instruct`             | Q4_K_M | ~9 GB    | Lowest-risk swap, same footprint as baseline     |
| 2        | Qwen2.5-Coder-32B      | `Qwen/Qwen2.5-Coder-32B-Instruct`             | Q4_K_M | ~18 GB   | Top code-specialist pick, trained on AST parsing |
| 3        | DeepSeek-Coder-V2-Lite | `deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct` | Q4_K_M | ~9–10 GB | MoE (16B total, 2.4B active), 338 languages      |

### General-Purpose Models

| Phase | Model                   | Tag                                             | Quant  | VRAM      | Notes                                                  |
| ----- | ----------------------- | ----------------------------------------------- | ------ | --------- | ------------------------------------------------------ |
| 4     | Qwen3-30B-A3B           | `Qwen/Qwen3-30B-A3B-Instruct-2507`              | Q4_K_M | ~17 GB    | MoE (30.5B total, 3.3B active), non-thinking variant   |
| 5     | Mistral Small 3.1 24B   | `mistralai/Mistral-Small-3.1-24B-Instruct-2503` | Q4_K_M | ~13–14 GB | Cleanest JSON output, strong tool calling              |
| 6     | Nemotron-3-Nano-30B-A3B | NVIDIA Nemotron-3-Nano-30B-A3B                  | NVFP4  | ~15–18 GB | Hardware-optimized for DGX Spark (~56 t/s benchmarked) |
| 7     | Phi-4 14B               | `microsoft/phi-4`                               | Q4_K_M | ~8–9 GB   | Lightweight, synthetic + academic training data        |

## Test Procedure (repeat per model)

1. Update `group_vars/k8s.yml` with the model tag
2. Run `download-models.yml` then `deploy-graphrag.yml`
3. Delete the test workspace in Neo4j to start clean
4. Ingest the test repo via `/v1/codebase/ingest`
5. Wait for all jobs to complete
6. Collect metrics below

## Metrics to Record

**Extraction quality** (query Neo4j after ingestion):

- Total nodes
- Total relationships
- Cross-file relationships
- Unique entity types (labels)
- Unique relationship types
- Orphan nodes (no relationships)

**Performance:**

- Wall-clock per chunk (avg seconds)
- Total ingestion time (minutes)
- Tokens/sec from vLLM logs
- Output tokens per chunk (avg)
- JSON parse failures (check LightRAG logs for errors)

**Stability:**

- OOM crashes (Y/N)
- Burst mode triggered (Y/N)
- All jobs completed without retries (Y/N)
- Peak GPU memory during ingestion

## Neo4j Validation Queries

```cypher
MATCH (n) RETURN count(n) AS total_nodes;
MATCH ()-[r]->() RETURN count(r) AS total_rels;
MATCH (n) WHERE NOT (n)--() RETURN count(n) AS orphans;
MATCH (n) RETURN labels(n) AS type, count(n) AS count ORDER BY count DESC;
MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS count ORDER BY count DESC;
MATCH (a)-[r]->(b) WHERE a.file_path IS NOT NULL AND b.file_path IS NOT NULL AND a.file_path <> b.file_path RETURN count(r) AS cross_file;
MATCH path = (a)-[*1..5]->(b) RETURN length(path) AS depth, count(*) AS chains ORDER BY depth;
```

## Recommended Testing Order

**Round 1 — Code specialists (compare against baseline):**

1. Qwen2.5-Coder-14B — zero-infrastructure-change swap
2. Qwen2.5-Coder-32B — bump MPS slice to ~20 GB
3. DeepSeek-Coder-V2-Lite — MoE code specialist

**Round 2 — General-purpose (compare against Round 1 winner):**

4. Qwen3-30B-A3B (non-thinking 2507) — best for mixed code + docs
5. Mistral Small 3.1 24B — cleanest structured output
6. Nemotron-3-Nano-30B-A3B — DGX Spark hardware-optimized
7. Phi-4 14B — lightweight alternative

**Round 3 — Optimization (apply to winner):**

- Test Q5_K_M and Q8 quantization on the winning model
- Tune ingest worker concurrency (4 → 3 → 2)
- Validate thinking mode disabled (for Qwen3 models)
- Run full stress test (3 repos, 200–500 files each)

## Decision Criteria

- **Code specialists win if:** They find meaningfully more cross-file relationships and code-specific entity types (interface, abstract_class, generator, coroutine) than baseline.
- **General-purpose wins if:** Code specialists are too narrow and miss architectural patterns in mixed codebases with docs/configs.
- **Final pick:** Model producing the most complete and accurate graph wins, weighted toward extraction quality over raw speed (this is batch ingestion, not interactive chat).

## Key Reminders

- Use the **non-thinking 2507 variant** for Qwen3-30B-A3B (no `<think>` blocks, saves 30–50% output tokens)
- All models at **Q4_K_M** for fair comparison on memory footprint
- Keep ingest workers at **4** for baseline, drop to **2–3** if larger models cause queuing
- Burst mode auto-scales reranker to zero during heavy ingestion — this is expected behavior
- MoE models (Qwen3-30B-A3B, DeepSeek-Coder-V2-Lite, Nemotron) load all parameters into memory even though only a fraction are active per token — expect 2–4x slower than dense models of similar active parameter count
- Gemma 3 27B removed — gated repo requires manual license acceptance on HuggingFace
