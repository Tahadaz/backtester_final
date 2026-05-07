# services/api/Dockerfile
FROM python:3.12-slim

WORKDIR /repo

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-dev.txt /repo/requirements-dev.txt
RUN pip install --no-cache-dir -r /repo/requirements-dev.txt

COPY . /repo

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/repo

CMD ["sh", "-c", "uvicorn services.api.app.main:app --host 0.0.0.0 --port 8000 --workers ${API_WORKERS:-4}"]
