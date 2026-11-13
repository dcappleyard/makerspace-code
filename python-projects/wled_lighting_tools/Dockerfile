# Show runner image. Deploy/update: docker compose up -d --build
FROM python:3.13-slim
# zoneinfo needs tz data; TZ (set in compose) makes log timestamps local
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Unbuffered so log lines reach `docker compose logs` immediately
ENV PYTHONUNBUFFERED=1
# Exec form: python is PID 1 and gets docker stop's SIGTERM (runner stops cleanly)
CMD ["python", "runner.py"]
