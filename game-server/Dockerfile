# Use official SteamCMD image as base
FROM cm2network/steamcmd:latest

# Install dependencies
USER root
RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-dev build-essential ca-certificates procps supervisor && \
    rm -rf /var/lib/apt/lists/* && \
    update-ca-certificates && \
    python3 -m pip install --upgrade pip --break-system-packages

# Create application directory
WORKDIR /app
COPY requirements.txt .

# Install Python dependencies
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt

# Copy application files
COPY manager.py .
COPY api_service.py .
COPY task_processor.py .
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create log directory
RUN mkdir -p /var/log/supervisor

USER steam
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
