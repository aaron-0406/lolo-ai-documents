# =============================================================================
# LOLO AI Documents Microservice - Production Dockerfile
# =============================================================================
# Multi-stage build optimized for AWS ECS Fargate deployment
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Builder - Install dependencies
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libheif-dev \
    libjpeg-dev \
    libpng-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt with pinned versions
COPY requirements.txt ./

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies (all pinned versions)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# -----------------------------------------------------------------------------
# Stage 2: Runtime - Final production image
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    # For pillow-heif HEIC/HEIF support (iPhone photos)
    libheif1 \
    # For image processing
    libjpeg62-turbo \
    libpng16-16 \
    # For health checks and debugging
    curl \
    # Timezone data
    tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set timezone to Lima, Peru
ENV TZ=America/Lima
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set Python environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    # Disable pip version check for faster startup
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Copy application code
COPY app/ ./app/

# Expose port (FastAPI default)
EXPOSE 8000

# Health check for ECS/ALB
# Uses curl to check the /health endpoint
# - interval: Check every 30 seconds
# - timeout: Wait max 10 seconds for response
# - start-period: Give app 60 seconds to start before checking
# - retries: Fail after 3 consecutive failures
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application with production settings
# - workers: Single worker for Fargate (scale with task count, not workers)
# - timeout-keep-alive: Match ALB idle timeout
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--timeout-keep-alive", "120", \
     "--access-log", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
