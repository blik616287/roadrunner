FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir llama-cpp-python fastapi uvicorn sse-starlette

COPY server.py /app/server.py

EXPOSE 8000

CMD ["uvicorn", "app.server:app", \
     "--host", "0.0.0.0", \
     "--port", "8000"]
