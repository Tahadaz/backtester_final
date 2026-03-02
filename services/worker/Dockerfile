FROM python:3.12-slim

WORKDIR /repo

# No apt-get to avoid corrupted shared libs issues
COPY requirements-dev.txt /repo/requirements-dev.txt
RUN pip install --no-cache-dir -r /repo/requirements-dev.txt

COPY . /repo

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/repo

CMD ["python","-m","services.worker.worker"]
