# Use official SteamCMD image as base
FROM cm2network/steamcmd:latest

# Install dependencies
USER root
RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-dev build-essential ca-certificates procps && \
    rm -rf /var/lib/apt/lists/* && \
    update-ca-certificates && \
    python3 -m pip install --upgrade pip --break-system-packages

# Create application directory
WORKDIR /app
COPY requirements.txt .

# Install Python dependencies
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY manager.py .

USER steam
CMD ["python3", "manager.py"]
