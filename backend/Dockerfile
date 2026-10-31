FROM python:3.11-slim AS cad-converter
COPY deploy/install_libredwg.sh /tmp/install_libredwg.sh
RUN sh /tmp/install_libredwg.sh

FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libarchive-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements-data.txt /app/backend/requirements-data.txt
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements-data.txt
COPY . /app
COPY --from=cad-converter /usr/local/bin/dwg2dxf /usr/local/bin/dwg2dxf

ENV PYTHONPATH=/app CAD_DWG_CONVERTER=/usr/local/bin/dwg2dxf
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
