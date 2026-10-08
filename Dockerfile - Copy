FROM python:3.11-slim

WORKDIR /app

# System deps for PyMuPDF, pdfplumber, pytesseract, Pillow, faiss
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (excludes .env, venv, etc. via .dockerignore)
COPY . .

# Runtime data (SQLite, uploads) is mounted at /app/data
ENV ROUTING_DB_PATH=/app/data/faq.db
ENV PYTHONUNBUFFERED=1

EXPOSE 9000

CMD ["python", "run.py"]
