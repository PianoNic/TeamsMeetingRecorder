# Multi-stage Dockerfile for Teams Meeting Recorder
# Based on 2026 Docker best practices

# Stage 1: Base image with system dependencies
FROM python:3.13-slim-bookworm AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Chrome and Selenium dependencies
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    # VNC and display dependencies
    x11vnc \
    xvfb \
    fluxbox \
    # Audio dependencies
    pulseaudio \
    pulseaudio-utils \
    alsa-utils \
    libportaudio2 \
    libsndfile1 \
    # Additional utilities
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Install ChromeDriver
RUN CHROME_VERSION=$(google-chrome --version | awk '{print $3}' | cut -d '.' -f 1) && \
    wget -q "https://storage.googleapis.com/chrome-for-testing-public/stable/linux64/chromedriver-linux64.zip" -O /tmp/chromedriver.zip && \
    unzip /tmp/chromedriver.zip -d /tmp/ && \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/ && \
    chmod +x /usr/local/bin/chromedriver && \
    rm -rf /tmp/chromedriver*

# Stage 2: Python dependencies
FROM base AS dependencies

WORKDIR /app

# Copy requirements first (leverage Docker layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Stage 3: Final runtime image
FROM dependencies AS runtime

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash botuser && \
    mkdir -p /app /app/recordings /app/logs && \
    chown -R botuser:botuser /app

# Copy application code
COPY --chown=botuser:botuser app/ /app/app/

# Setup VNC and audio directories
RUN mkdir -p /home/botuser/.vnc /home/botuser/.config/pulse && \
    chown -R botuser:botuser /home/botuser

# Copy startup scripts
COPY --chown=botuser:botuser docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# Switch to non-root user
USER botuser

WORKDIR /app

# Expose ports
EXPOSE 8000 5900

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Set entrypoint
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Default command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
