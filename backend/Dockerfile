FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx asyncpg \
    "sqlalchemy[asyncio]" alembic "pydantic>=2.9" "pydantic-settings>=2.6" \
    anthropic python-dotenv tenacity psycopg2-binary

COPY app/ ./app/

CMD ["python", "-c", "import os,uvicorn; uvicorn.run('app.main:app', host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))"]
