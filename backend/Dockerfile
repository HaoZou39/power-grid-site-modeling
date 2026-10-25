FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libarchive-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements-data.txt /app/backend/requirements-data.txt
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements-data.txt
COPY . /app

ENV PYTHONPATH=/app
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
