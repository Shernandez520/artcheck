FROM python:3.11-slim

# Install system dependencies + build tools
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    libcairo2-dev \
    libpango1.0-dev \
    libpangocairo-1.0-0 \
    poppler-utils \
    ghostscript \
    libcdr-tools \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/start.sh

EXPOSE 8501

CMD ["/app/start.sh"]
