FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

COPY monitoring/evidently/requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/requirements.txt

COPY scripts/generate_drift_report.py ./scripts/generate_drift_report.py

ENTRYPOINT ["python", "scripts/generate_drift_report.py"]
