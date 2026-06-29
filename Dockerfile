# stage 1: Build stage
FROM python:3.11-slim as builder

#set working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*


# Copy requirements first
COPY requirements.txt .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Production stage
FROM python:3.11-slim

# Set working directory
WORKDIR /app

#Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

#Set environment variables
ENV PATH="/opt/venv/bin:$PATH" \
PYTHONUNBUFFERED=1 \
PYTHONDONTWRITEBYTECODE=1


# Install runtime dependendies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

#Copy the application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && \
   chown -R appuser:appuser /app

#switch to non-root user
USER appuser

#expose port
EXPOSE 8000

#Healtch check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl --fail http://localhost:8000/docs || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
