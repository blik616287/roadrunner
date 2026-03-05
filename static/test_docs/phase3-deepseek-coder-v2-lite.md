# Phase 3: DeepSeek-Coder-V2-Lite (Q4_K_M GGUF)

- **Model**: DeepSeek-Coder-V2-Lite-Instruct
- **Quant**: Q4_K_M GGUF (~9.6 GiB)
- **Date**: 2026-03-04

## Status: SKIPPED

vLLM does not support the `deepseek2` GGUF architecture:

```
ValueError: GGUF model with architecture deepseek2 is not supported yet.
```

Would need to either:
- Use the HuggingFace checkpoint (full BF16, ~32 GiB — too large for 0.30 GPU allocation)
- Wait for vLLM GGUF support for deepseek2 architecture
- Use a different serving backend (llama.cpp, etc.)
