# Airflow with the pipeline code installed in its own virtualenv, so the
# pipeline's dependencies cannot conflict with Airflow's.
FROM apache/airflow:3.0.6-python3.12
USER root
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /opt/directory-truth
COPY pipeline/ pipeline/
COPY dbt/ dbt/
COPY api/schema.sql api/schema.sql
RUN cd pipeline && uv sync --frozen --no-dev && chown -R airflow /opt/directory-truth
USER airflow
ENV PATH="/opt/directory-truth/pipeline/.venv/bin:$PATH"
