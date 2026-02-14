FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libpq-dev \
    libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 botuser && chown botuser:botuser /app
USER botuser

# Copy requirements first for better caching
COPY --chown=botuser:botuser requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=botuser:botuser . .

# Create necessary directories
RUN mkdir -p /app/user_states /app/logs /app/data && \
    chmod 700 /app/user_states /app/logs

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Expose log directory (for volume mounting)
VOLUME ["/app/user_states", "/app/logs", "/app/data"]

# Run the bot
CMD ["python", "main.py"]