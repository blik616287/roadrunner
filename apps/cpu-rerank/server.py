"""CPU-based reranker serving Cohere-compatible /rerank endpoint."""

import os
import logging
import time

from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import CrossEncoder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cpu-rerank")

MODEL_PATH = os.environ.get("MODEL_PATH", "/data")

app = FastAPI(title="CPU Reranker")
model: CrossEncoder | None = None


@app.on_event("startup")
def load_model():
    global model
    logger.info(f"Loading reranker from {MODEL_PATH}...")
    t0 = time.time()
    model = CrossEncoder(MODEL_PATH, max_length=256)
    logger.info(f"Reranker loaded in {time.time() - t0:.1f}s")


class RerankDoc(BaseModel):
    text: str


class RerankRequest(BaseModel):
    model: str = ""
    query: str
    documents: list[str] | list[RerankDoc] = []
    top_n: int | None = None


class RerankResult(BaseModel):
    index: int
    relevance_score: float


class RerankResponse(BaseModel):
    results: list[RerankResult]
    model: str


@app.post("/rerank")
def rerank(req: RerankRequest) -> RerankResponse:
    docs = []
    for d in req.documents:
        if isinstance(d, str):
            docs.append(d)
        else:
            docs.append(d.text)

    if not docs:
        return RerankResponse(results=[], model=req.model)

    pairs = [(req.query, doc) for doc in docs]
    t0 = time.time()
    scores = model.predict(pairs, batch_size=16, show_progress_bar=False).tolist()
    logger.info(f"Reranked {len(pairs)} pairs in {time.time() - t0:.1f}s")

    results = [
        RerankResult(index=i, relevance_score=float(s))
        for i, s in enumerate(scores)
    ]
    results.sort(key=lambda r: r.relevance_score, reverse=True)

    if req.top_n:
        results = results[: req.top_n]

    return RerankResponse(results=results, model=req.model)


@app.get("/health")
def health():
    return {"status": "ok" if model is not None else "loading"}
