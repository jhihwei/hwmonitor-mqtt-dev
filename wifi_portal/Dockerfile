# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends network-manager wpasupplicant \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fastapi uvicorn jinja2 python-multipart

WORKDIR /app
COPY . /app

CMD ["uvicorn", "wifi_portal.webui.app:app", "--host", "0.0.0.0", "--port", "8080"]
