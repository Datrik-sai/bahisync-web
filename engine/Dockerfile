FROM python:3.13-slim

# Tesseract + Poppler for scanned statements, qpdf libs for password-protected PDFs
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bahisync_engine ./bahisync_engine
COPY api ./api

ENV BAHISYNC_DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8000
RUN useradd --create-home app && mkdir -p /data && chown app /data
USER app
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
