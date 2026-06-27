FROM apache/airflow:2.10.4-python3.11

# Install postgresql-client so airflow_init can run psql for the idempotent
# CREATE DATABASE guard. apt-get requires root; switch back to airflow after.
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# dbt is installed in its OWN isolated virtualenv, NOT into Airflow's Python env.
# Reason: dbt-core 1.11 and Airflow 2.10 pin CONFLICTING transitive deps
# (e.g. opentelemetry-proto 1.27.0 vs dbt's requirement) — co-installing them is
# impossible (pip ResolutionImpossible). An isolated venv gives dbt its own
# dependency tree. Same isolation principle as the Phase-1 host venv and the
# separate Airflow image, applied one level deeper. The DAG calls /opt/dbt-venv/bin/dbt.
# (apache-airflow-providers-postgres is intentionally NOT installed: the DAG talks to
# the app over HTTP and to Postgres only through dbt's own adapter — nothing uses the
# Postgres provider/hook.)
USER root
RUN python -m venv /opt/dbt-venv \
    && /opt/dbt-venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/dbt-venv/bin/pip install --no-cache-dir \
         "dbt-core==1.11.11" \
         "dbt-postgres==1.10.1"

# Drop back to the unprivileged airflow user (uid 50000) for runtime.
USER airflow
