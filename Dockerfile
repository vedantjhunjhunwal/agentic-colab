FROM python:3.11-slim

WORKDIR /app

# system deps for matplotlib/PIL
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy application
COPY . .

# non-root user for security
RUN useradd -m -u 1000 appuser && \
    mkdir -p /data && chown appuser:appuser /data
USER appuser

ENV MPLBACKEND=Agg
ENV COLAB_DATA_DIR=/data
ENV PORT=8080

EXPOSE 8080

# Shell form so ${PORT} is expanded (cloud platforms inject their own PORT).
# One worker with many threads: notebook kernels hold in-memory Python state,
# so all requests for a notebook must hit the same process.
CMD gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 8 --timeout 300 app:app
