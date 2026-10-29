ARG AIRFLOW_VERSION=3.3.2
FROM apache/airflow:${AIRFLOW_VERSION}-python3.12

ARG AIRFLOW_VERSION
COPY orchestration/requirements-airflow.txt /tmp/requirements-airflow.txt

RUN python -m pip install --no-cache-dir \
    "apache-airflow[statsd]==${AIRFLOW_VERSION}" \
    -r /tmp/requirements-airflow.txt
