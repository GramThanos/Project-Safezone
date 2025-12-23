# Use official SteamCMD image as base
FROM cm2network/steamcmd:latest

# Switch to root to install additional packages
USER root

# Install Python, pip, and dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Create application directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy monitor script
COPY server_monitor.py .

# Switch to steam user for running applications
USER steam

# Run server monitor directly (no supervisord needed)
CMD ["python3", "server_monitor.py"]
