FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BROKER=paper \
    ARM_LIVE_TRADING=false

COPY pyproject.toml README.md ./
COPY paperbot ./paperbot
COPY fixtures ./fixtures
COPY docs ./docs

RUN mkdir -p /app/data \
    && python -c "from paperbot.market.fixtures import write_synthetic_fixture; from pathlib import Path; p=Path('fixtures/synthetic_momentum.json'); p.exists() or write_synthetic_fixture(p)"

VOLUME ["/app/data"]

CMD ["python", "-m", "paperbot", "run"]
