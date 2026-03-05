# Phase 6: Nemotron-3-Nano-30B-A3B (NVFP4) — SKIPPED

- **Model**: nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4
- **Quant**: NVFP4 (ModelOpt, FP8 KV cache)
- **Architecture**: Hybrid Mamba-2 + Attention MoE (30B total, 3B active), NemotronHForCausalLM
- **Date**: 2026-03-04

## Why Skipped

The Nemotron-3-Nano-30B-A3B NVFP4 model could not be loaded for benchmarking due to multiple compounding issues on the DGX Spark GB10 (SM121):

### Issue 1: CUTLASS FP4 GEMM fails on SM121

The stock vLLM image (`vllm/vllm-openai:nightly-aarch64`, v0.16.1rc1) crashes during model weight initialization:

```
RuntimeError: [FP4 gemm Runner] Failed to run cutlass FP4 gemm on sm120. Error: Error Internal
```

SM121 (GB10) is routed to SM120 tile configs, but GB10 only has 99 KiB shared memory vs B200's ~228 KiB. The SM120 tile configs overflow GB10's SMEM.

### Issue 2: Requires custom vLLM image

A community image (`avarok/vllm-dgx-spark:v11`) with patched CUTLASS kernels for SM121 was needed. This image:
- Uses `vllm` entrypoint (requires `serve` subcommand, unlike the stock image)
- JIT-compiles FlashInfer CUTLASS MoE kernels from source on first startup (~10+ min)
- Requires `VLLM_FLASHINFER_MOE_BACKEND=latency` env var

### Issue 3: JIT kernel compilation OOM

The FlashInfer CUTLASS MoE kernel compilation (`nvcc`/`cicc` for SM121a) consumes massive CPU RAM during JIT. With the default 32Gi memory limit, the container was OOMKilled during compilation. Bumping to 64Gi caused node-wide memory pressure that evicted other pods (postgresql, redis, nats, neo4j, lightrag, vllm-embed, vllm-rerank).

### Issue 4: Startup time exceeds probe thresholds

Model load (~107s) + torch.compile (~30s) + FlashInfer kernel JIT (~10+ min) = ~13+ min startup. The default 600s startup probe was insufficient. Even with 1200s (120 * 10s), the OOM kills occurred before compilation completed.

## What Would Be Needed

To run this model on DGX Spark in our pipeline:
1. Custom vLLM image (`avarok/vllm-dgx-spark:v11` or equivalent)
2. Pre-compiled FlashInfer kernel cache persisted to a PVC (avoid JIT on every restart)
3. 64Gi+ memory limit for the extract pod during initial compilation
4. Scale down all other GPU pods during startup to avoid MPS/memory contention
5. 20+ min startup probe threshold
6. `VLLM_FLASHINFER_MOE_BACKEND=latency` env var

## Verdict

**Not practical for pipeline use.** While NVIDIA markets this model as optimized for DGX Spark, the NVFP4 quantization requires extensive workarounds (custom images, kernel JIT, high memory limits) that make it operationally fragile. The JIT compilation on every pod restart is a non-starter for a Kubernetes deployment without pre-built kernel caches. The model may perform well once running (~65 tok/s per community reports), but the deployment complexity far exceeds any other model tested.

## Sources

- [DGX Spark, Nemotron3, and NVFP4: Getting to 65+ tps](https://forums.developer.nvidia.com/t/dgx-spark-nemotron3-and-nvfp4-getting-to-65-tps/355261)
- [PSA: State of FP4/NVFP4 Support for DGX Spark in vLLM](https://forums.developer.nvidia.com/t/psa-state-of-fp4-nvfp4-support-for-dgx-spark-in-vllm/353069)
- [avarok/vllm-dgx-spark Docker image](https://huggingface.co/Avarok/vllm-dgx-spark)
- [CUTLASS FP4 GEMM SM121 issue](https://github.com/NVIDIA/cutlass/issues/2800)
- [vLLM issue #34452: NVFP4 on SM12x](https://github.com/vllm-project/vllm/issues/34452)
