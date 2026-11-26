FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /mlflow/data /mlflow/artifacts \
    && chown -R app:app /mlflow

# --- MLOps app dependencies ---
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

# --- Agentic layer dependencies ---
COPY backend/agentic/pyproject.toml /app/backend/agentic/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install \
        "langgraph>=1.2,<2" \
        "pydantic>=2.7,<3" \
        "pydantic-settings>=2.3,<3" \
        "fastapi>=0.115" \
        "httpx>=0.27,<1" \
        "pyyaml>=6" \
        "numpy>=1.26" \
        "pillow>=10"

# --- GenAI+RAG+RL tuteur library ---
COPY pyproject.toml /app/pyproject.toml
COPY src/ /app/src/
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -e /app

# --- Application source ---
COPY --chown=app:app app/ /app/app/
COPY --chown=app:app backend/agentic/src/ /app/backend/agentic/src/
COPY --chown=app:app orchestration/shared/ /app/orchestration/shared/

# Make tutor_agentic importable from the app
ENV PYTHONPATH=/app:/app/src:/app/backend/agentic/src

USER app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
