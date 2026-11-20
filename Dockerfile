FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Prague

# tzdata kvůli místnímu času v lozích (logika bota si časovou zónu bere z balíčku tzdata v pipu)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# závislosti zvlášť, ať se při změně kódu nemusí znovu instalovat
COPY requirements.txt .
RUN pip install -r requirements.txt

# bot neběží jako root; zapisovat smí jen do data/ (stažený jízdní řád MHD, volume)
RUN useradd --create-home --uid 1000 bot \
    && mkdir -p /app/data \
    && chown bot:bot /app/data

COPY . .

ARG BOT_VERSION=dev
ENV BOT_VERSION=${BOT_VERSION}

USER bot

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "bot.py"]
