FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY db ./db
COPY api ./api
COPY ingest ./ingest
COPY web ./web
COPY scripts ./scripts

EXPOSE 8000
