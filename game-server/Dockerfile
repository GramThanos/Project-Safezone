# Use official SteamCMD image as base
FROM cm2network/steamcmd:latest

# Install dependencies
USER root
RUN apt-get update && \
    apt-get install -y python3 python3-pip supervisor && \
    rm -rf /var/lib/apt/lists/*

# Create application directory
WORKDIR /app

# Copy Supervisor configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
RUN mkdir -p /var/log/supervisor && \
    chown -R steam:steam /var/log/supervisor

# Configure folders
# /opt/steam-apps is where the game files are installed
# /home/steam/Zomboid is the game's data directory (HOME/Zomboid),
# /backups is where world archives are written.
RUN mkdir -p /opt/steam-apps /home/steam/Zomboid /backups && \
    chown -R steam:steam /opt/steam-apps /home/steam/Zomboid /backups

# Install Python dependencies
USER steam
COPY requirements.txt .
RUN python3 -m pip install --break-system-packages --upgrade pip && \
    python3 -m pip install --break-system-packages --no-cache-dir -r requirements.txt

# Copy application files
COPY ./src /app/

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
