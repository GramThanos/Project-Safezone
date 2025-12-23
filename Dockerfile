# Use official SteamCMD image as base
FROM cm2network/steamcmd:latest

# Switch to root to install additional packages
USER root

# Install Python, pip, supervisor, and other dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    supervisor \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Create application directory
WORKDIR /app

# Copy Python requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .
COPY server_monitor.py .
COPY templates ./templates/

# Create necessary directories with proper permissions
RUN mkdir -p /var/log/supervisor && \
    chown -R steam:steam /var/log/supervisor

# Copy supervisor configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose Flask port
EXPOSE 5000

# Switch to steam user for running applications
USER steam

# Start supervisord
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
