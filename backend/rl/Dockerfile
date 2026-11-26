FROM python:3.11-slim

WORKDIR /app

# Install RL service dependencies
COPY backend/rl/pyproject.toml /app/backend/rl/pyproject.toml
RUN pip install --no-cache-dir fastapi uvicorn pydantic numpy

# Install tuteur library (for LinUCB policy, optional)
COPY src/ /app/src/
COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir -e /app || true

# Copy RL service source
COPY backend/rl/ /app/backend/rl/

ENV PYTHONPATH=/app

CMD ["python", "-m", "uvicorn", "backend.rl.main:app", "--host", "0.0.0.0", "--port", "8001"]
