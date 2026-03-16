"""Thin OpenAI-compatible wrapper around llama-cpp-python with SSE ping support."""
import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from llama_cpp import Llama

MODEL_PATH = os.environ.get("MODEL_PATH", "/data")
N_THREADS = int(os.environ.get("N_THREADS", "8"))
N_CTX = int(os.environ.get("N_CTX", "8192"))

_llm: Llama | None = None


def _find_gguf(path: str) -> str:
    if os.path.isfile(path) and path.endswith(".gguf"):
        return path
    for f in sorted(os.listdir(path)):
        if f.endswith(".gguf"):
            return os.path.join(path, f)
    raise FileNotFoundError(f"No .gguf file found in {path}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _llm
    model_file = _find_gguf(MODEL_PATH)
    print(f"Loading model: {model_file} (n_threads={N_THREADS}, n_ctx={N_CTX})")
    _llm = Llama(
        model_path=model_file,
        n_threads=N_THREADS,
        n_ctx=N_CTX,
        verbose=False,
    )
    print("Model loaded.")
    yield
    del _llm


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/models")
def list_models():
    return {"data": [{"id": "qwen3-4b-cpu", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    max_tokens = body.get("max_tokens", 512)
    temperature = body.get("temperature", 0.7)
    stream = body.get("stream", False)

    if not stream:
        result = _llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return JSONResponse(result)

    # Streaming with SSE ping to keep connection alive during prompt eval.
    # llama-cpp generation is synchronous and blocks during prompt eval,
    # so we run it in a thread and feed chunks through a queue.
    queue: asyncio.Queue = asyncio.Queue()

    async def producer():
        def _run():
            try:
                for chunk in _llm.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=True,
                ):
                    asyncio.run_coroutine_threadsafe(queue.put(json.dumps(chunk)), loop)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _run)

    async def generate():
        await producer()
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    return EventSourceResponse(generate(), ping=5)
