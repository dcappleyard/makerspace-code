FROM python:3.12-slim
WORKDIR /app
# A font with broad Unicode coverage for server-rendered captions (installed at
# build time, not vendored in the repo).
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ server/
ENV DATA_DIR=/data
VOLUME /data
EXPOSE 8080
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
