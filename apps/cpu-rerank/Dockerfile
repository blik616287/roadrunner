FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY server.py /app/server.py

EXPOSE 8000

WORKDIR /app

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
