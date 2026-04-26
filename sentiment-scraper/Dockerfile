FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for lxml
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libxml2-dev libxslt1-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-deps .

# Dedup cache location inside the container — mount a volume here to persist across restarts
RUN mkdir -p /var/lib/sentiment-scraper
ENV SCRAPER_DEDUP_DB_PATH=/var/lib/sentiment-scraper/dedup.sqlite

ENTRYPOINT ["sentiment-scraper"]
