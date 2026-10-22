FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends osmium-tool \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
COPY worker/requirements.txt /app/worker/requirements.txt
# CPU torch keeps the image runnable without a GPU. Install a CUDA wheel and set
# MASKING_DEVICE=cuda when this worker should use a GPU; auto uses CUDA only if the installed torch can see one.
RUN pip install --no-cache-dir -r /app/worker/requirements.txt
COPY . /app

ENV PYTHONPATH=/app \
    SCENE_ROOT=/app/scenes \
    MASKING_DEVICE=auto \
    MASKING_OUTPUT_ROOT=/app/outputs/masking-sites \
    HF_HOME=/app/outputs/huggingface
CMD ["python", "-m", "worker.main"]
