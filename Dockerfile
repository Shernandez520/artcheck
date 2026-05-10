FROM python:3.11-slim

# Runtime libs only — libcairo2 (not -dev), no build headers
# cairocffi installs via pre-built wheel so dev headers are not needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpangocairo-1.0-0 \
    poppler-utils \
    ghostscript \
    libcdr-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/start.sh

EXPOSE 8501

CMD ["/app/start.sh"]
