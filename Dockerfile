# ============================================================================
# Stage 1: Base image with system dependencies
# ============================================================================
FROM python:3.12-slim-bookworm AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_PREFER_BINARY=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install build dependencies and core system packages (Layer 1 - changes rarely)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build tools (needed for some packages)
    build-essential \
    python3-dev \
    # Core utilities
    wget \
    curl \
    gnupg \
    ca-certificates \
    procps \
    unzip \
    # Display dependencies
    xvfb \
    fluxbox \
    x11-xserver-utils \
    # Audio dependencies
    pulseaudio \
    pulseaudio-utils \
    alsa-utils \
    libsndfile1 \
    libportaudio2 \
    # Screenshot utility
    scrot \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libatspi2.0-0 \
    libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

# Install fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    fonts-noto-color-emoji \
    fonts-freefont-ttf \
    fonts-ipafont-gothic \
    fonts-wqy-zenhei \
    fonts-tlwg-loma-otf \
    fonts-unifont \
    xfonts-scalable \
    && rm -rf /var/lib/apt/lists/*

# ============================================================================
# Stage 2: Python dependencies
# ============================================================================
FROM base AS dependencies

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install chromium && \
    playwright install-deps chromium

# ============================================================================
# Stage 3: Final runtime image
# ============================================================================
FROM dependencies AS runtime

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash botuser && \
    mkdir -p /app /app/recordings && \
    chown -R botuser:botuser /app

# Copy application code
COPY --chown=botuser:botuser app/ /app/app/

# Copy startup scripts
COPY --chown=botuser:botuser docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# Switch to non-root user
USER botuser

WORKDIR /app

# Expose ports
EXPOSE 8000

# Entrypoint and command
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]