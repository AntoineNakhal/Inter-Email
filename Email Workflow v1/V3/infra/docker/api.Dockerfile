FROM python:3.12-slim

WORKDIR /app

# Build tools + system libs needed by some Python deps:
#   * build-essential / gcc — fallback when a package has no pre-built wheel
#     for our arch (notably tiktoken on ARM, cryptography on edge cases).
#   * libxml2/libxslt — runtime libs for lxml (used by python-pptx).
#   * libjpeg/zlib — runtime libs for Pillow (used by pdfplumber).
# We clean up apt lists in the same RUN so the layer stays small.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    libjpeg-dev \
    zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*

COPY alembic.ini pyproject.toml README.md ./
COPY backend ./backend
COPY api ./api
COPY data ./data

RUN pip install --no-cache-dir -e ".[postgres]"

EXPOSE 8000

CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
