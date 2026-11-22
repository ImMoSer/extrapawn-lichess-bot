FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LICHESS_BOT_DOCKER=true

RUN groupadd -r -g 10001 appuser && \
    useradd -r -u 10001 -g appuser -m -s /bin/bash appuser

WORKDIR /app

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/lichess_bot_auto_logs && chown -R appuser:appuser /app

USER appuser

CMD ["python3", "lichess-bot.py", "--config", "config.extrapawn.yml", "--disable_auto_logging"]
