#!/usr/bin/env python3
# Manager of the game server

# Import necessary modules
import time
import socket
import datetime
import threading
import subprocess

# Import custom modules
import config
import cache
import database


class GameManager:
    def __init__(self, server_name, server_ports):
        self.server_script = '/opt/pzserver/start-server.sh'
        self.server_name = server_name
        self.server_log = f'/tmp/game_server_{server_name}.log'
        self.server_ports = server_ports

        self.process = None
        self.is_running = False
        self.lock = threading.Lock()
        self.listener = None

    def log(self, message):
        print(f"[{datetime.datetime.now().isoformat()}][Game-Manager {self.server_name}] {message}")

    def start_server(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                self.log("Server is already running.")
                return

            self.log("Starting game server...")
            log_handle = open(self.server_log, "a")
            
            cmd = [self.server_script, "-servername", self.server_name]
            
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            self.is_running = True
            self.log("Server process started.")

    def stop_server(self):
        with self.lock:
            if not self.process or self.process.poll() is not None:
                self.log("Server is not running.")
                return

            self.log("Stopping server (Save & Quit sequence)...")
            
            try:
                self.send_command("save")
                time.sleep(15)
                self.send_command("quit")
            except Exception as e:
                self.log(f"Error sending save/quit commands: {e}")

            try:    
                # Wait for process to exit naturally
                self.process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.log("Server took too long to quit. Forcing termination.")
                self.process.kill()
            
            self.is_running = False
            self.log("Server stopped.")

    def send_command(self, cmd_string):
        """Pipes a raw command string to the server stdin"""
        if self.process and self.process.poll() is None:
            self.log(f"Executing command: {cmd_string}")
            self.process.stdin.write(f"{cmd_string}\n")
            self.process.stdin.flush()
        else:
            self.log("Cannot send command: Server is offline.")

    def onwake(self):
        """Binds to ports and waits for any packet to trigger start"""
        sockets = []
        for port in self.server_ports:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP
                s.bind(("0.0.0.0", port))
                s.settimeout(1.0)
                sockets.append(s)
            except Exception as e:
                self.log(f"Could not bind to port {port}: {e}")

        self.log("Sleep mode active. Listening for traffic on game ports...")
        
        triggered = False
        while not self.is_running and not triggered:
            for s in sockets:
                try:
                    data, addr = s.recvfrom(1024)
                    if data:
                        self.log(f"Wake-up packet received from {addr} on port {s.getsockname()[1]}")
                        triggered = True
                        break
                except socket.timeout:
                    continue
            
            # Check if someone started the server via commands listener while we were waiting
            if self.is_running: break

        # Cleanup sockets before starting server
        for s in sockets:
            s.close()
        
        if triggered:
            self.start_server()

    def commands_listener(self):
        """Listens for commands on a cache channel"""
        self.commands_channel = cache.subscribe_to_channel(config.MANAGER_GAME_COMMANDS_CHANNEL)
        self.log(f"Subscribed to commands channel")

        for message in cache.listen_to_channel(self.commands_channel):
            if 'type' in message and message['type'] == 'message' and 'server' in message and int(message['server']) == self.server_name:
                command = message['command']
                
                if command == "server-start":
                    self.start_server()
                elif command == "server-stop":
                    self.stop_server()
                elif command == "server-command":
                    if 'data' in message:
                        self.send_command(message['data'])
                    else:
                        self.log("No command data provided in server-command message.")
                else:
                    self.log(f"Unknown command received: {command}")

    def run(self):
        # Start commands listener in a separate thread
        self.listener = threading.Thread(target=self.commands_listener, daemon=True)
        self.listener.start()

        self.log("Manager initialized. Starting in Sleep Mode.")
        
        while True:
            if not self.is_running:
                # This blocks until a packet is received or server starts via commands listener
                self.onwake()
            
            # Keep the main thread alive while server is running
            while self.is_running:
                if self.process.poll() is not None:
                    self.log("Server process exited unexpectedly.")
                    self.is_running = False
                time.sleep(15)
    
    def terminate(self):
        self.listener.join(timeout=5)
        self.stop_server()



def update_managers(managers):
    """Update managers based on database servers"""
    session = database.get_session()
    servers = session.query(database.Server).all()
    servers = [s.to_dict() for s in servers]

    next_server_names = {s['name'] for s in servers}
    previous_server_names = {m['name'] for m in managers}

    # Managers to stop
    to_stop = previous_server_names - next_server_names
    for manager in managers:
        if manager['name'] in to_stop:
            manager['object'].terminate()
            manager['thread'].join(timeout=30)
            
    managers = [m for m in managers if m['name'] not in to_stop]
    
    # Managers to start
    to_start = next_server_names - previous_server_names
    for server in servers:
        if server['name'] in to_start:
            name = server['name']
            ports = server['ports']
            obj = GameManager(name, ports)
            thread = threading.Thread(target=obj.run, daemon=False)
            thread.start()
            managers.append({
                'name': name,
                'object': obj,
                'thread': thread
            })
    
    return managers


if __name__ == "__main__":
    # Load initial servers from database
    managers = update_managers([])

    # Montior for update command
    channel = cache.subscribe_to_channel(config.MANAGER_GAME_COMMANDS_CHANNEL)
    for message in cache.listen_to_channel(channel):
        if ('type' in message and message['type'] == 'message') and ('command' in message and message['command'] == 'update-managers'):
            # Update managers
            managers = update_managers(managers)
