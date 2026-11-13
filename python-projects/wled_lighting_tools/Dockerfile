# Show runner + dashboard image. Deploy/update: docker compose up -d --build
FROM python:3.13-slim
# zoneinfo needs tz data; TZ (set in compose) makes log timestamps local
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Unbuffered so log lines reach `docker compose logs` immediately.
# The config lives in the mounted /data dir so the dashboard can save it
# atomically (a bind-mounted single file can't be replaced).
# The program (shows + schedule, git-tracked) is mounted from the checkout's
# program/ dir, so a `git pull` reaches the runner without a rebuild.
ENV PYTHONUNBUFFERED=1 \
    WLED_CONFIG=/data/config.yaml \
    WLED_PROGRAM=/program/program.yaml
EXPOSE 8049
# Exec form: python is PID 1 and gets docker stop's SIGTERM (runner stops cleanly)
CMD ["python", "runner.py"]
