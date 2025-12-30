#!/usr/bin/env python3
import time
import socket
import datetime
import threading
import subprocess
import select
import json

# Custom modules
import config
import cache
import models
import database

class GameManager:
    commands_listener_interval_timeout = 5
    commands_listener_on_error_timeout = 15
    running_healthcheck_timeout = 15
    game_server_quit_timeout = 60

    def __init__(self, server_id, server_name, server_ports):
        self.server_id = server_id
        self.server_name = server_name
        self.server_script = '/opt/pzserver/start-server.sh'
        self.server_log_path = f'/tmp/game_server_{server_name}.log'
        self.server_ports = server_ports

        self.server_process = None
        self.server_is_running = False
        self.lock = threading.Lock()
        self.server_log_handle = None
        self._stop_event = threading.Event()

    def log(self, message):
        ts = datetime.datetime.now().isoformat()
        print(f"[{ts}][Manager {self.server_name}] {message}")

    def _send_raw_command(self, cmd_string):
        """Safely writes to the game server's stdin pipe."""
        try:
            if self.server_process and self.server_process.stdin and self.server_process.poll() is None:
                self.server_process.stdin.write(f"{cmd_string}\n")
                self.server_process.stdin.flush()
        except Exception as e:
            self.log(f"STDIN Error: {e}")

    def start_server(self):
        """Starts the physical server process."""
        with self.lock:
            if self.server_process and self.server_process.poll() is None:
                return

            self.log("Starting game server process...")
            try:
                self.server_log_handle = open(self.server_log_path, "a")
                cmd = [self.server_script, "-servername", self.server_name]
                
                self.server_process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=self.server_log_handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                self.server_is_running = True
            except Exception as e:
                self.log(f"Process Spawn Error: {e}")
                if self.server_log_handle:
                    self.server_log_handle.close()

    def stop_server(self):
        """Performs graceful shutdown of the game server."""
        with self.lock:
            if not self.server_process or self.server_process.poll() is not None:
                self.server_is_running = False
                return

            self.log("Shutting down game server (Save/Quit)...")
            try:
                self._send_raw_command("save")
                time.sleep(10)
                self._send_raw_command("quit")
                self.server_process.wait(timeout=self.game_server_quit_timeout)
            except subprocess.TimeoutExpired:
                self.log("Server did not exit gracefully. Killing...")
                self.server_process.kill()
            finally:
                if self.server_log_handle:
                    self.server_log_handle.close()
                    self.server_log_handle = None
                self.server_is_running = False

    def onwake(self):
        """UDP loop that checks for wake-up packets and the stop event."""
        sockets = []
        for port in self.server_ports:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.bind(("0.0.0.0", port))
                s.setblocking(False)
                sockets.append(s)
            except Exception as e:
                self.log(f"Port Bind Error {port}: {e}")

        try:
            while not self.server_is_running and not self._stop_event.is_set():
                # Efficient wait for 1 second across all sockets
                readable, _, _ = select.select(sockets, [], [], 1.0)
                if readable:
                    for s in readable:
                        data, addr = s.recvfrom(1024)
                        if data:
                            self.log(f"Wake-up packet detected from {addr}")
                            self.start_server()
                            return 
        finally:
            for s in sockets:
                s.close()

    def commands_listener(self):
        """Individual cache listener for this specific server."""
        while not self._stop_event.is_set():
            pubsub = cache.subscribe_to_channel(config.MANAGE_GAME_SERVERS_CHANNEL)
            if not pubsub:
                time.sleep(self.commands_listener_interval_timeout)
                continue
            
            try:
                for message in pubsub.listen():
                    if self._stop_event.is_set(): 
                        break
                    if message['type'] != 'message': 
                        continue
                    
                    try:
                        # Decode message and check if it targets this server
                        data = json.loads(message['data']) if isinstance(message['data'], str) else message['data']
                        if str(data.get('server')) != str(self.server_name):
                            continue

                        cmd = data.get('command')
                        if cmd == "server-start":
                            self.start_server()
                        elif cmd == "server-stop":
                            self.stop_server()
                        elif cmd == "server-command":
                            self._send_raw_command(data.get('data', ''))
                    except Exception as e:
                        self.log(f"JSON/Command Error: {e}")
            except Exception as e:
                self.log(f"Command Listener Error: {e}")
                # Cooldown on error
                self._stop_event.wait(timeout=self.commands_listener_on_error_timeout)

    def run(self):
        """Main Manager thread loop."""
        self.listener = threading.Thread(target=self.commands_listener, daemon=True)
        self.listener.start()

        self.log("Manager thread active.")
        while not self._stop_event.is_set():
            if not self.server_is_running:
                self.onwake()
            
            # Health check while running
            while self.server_is_running and not self._stop_event.is_set():
                if self.server_process.poll() is not None:
                    self.log("Detected server exit.")
                    self.server_is_running = False
                self._stop_event.wait(timeout=self.running_healthcheck_timeout)

    def terminate(self):
        """Stop loops and kill process."""
        self._stop_event.set()
        self.stop_server()


class Orchestrator:
    channel_listener_error_timeout = 5
    managers_shutdown_timeout = 60

    def __init__(self):
        self.managers = []
        self.commands_channel = config.MANAGE_GAME_SERVERS_CHANNEL

    def log(self, message):
        ts = datetime.datetime.now().isoformat()
        print(f"[{ts}][Orchestrator] {message}")

    def update_managers(self):
        """Synchronizes database list with running threads."""
        try:
            with database.get_context_session() as session:
                db_servers = session.query(models.Server).all()
                servers_data = [
                    {'id': s.id, 'name': s.name, 'ports': s.ports} 
                    for s in db_servers
                ]
        except Exception as e:
            self.log(f"DB Sync Error: {e}")
            return

        next_server_names = {s['name'] for s in servers_data}
        
        # Terminate managers from removed servers
        active_list = []
        for m_entry in self.managers:
            if m_entry['name'] in next_server_names:
                active_list.append(m_entry)
            else:
                self.log(f"Removing manager: {m_entry['name']}")
                m_entry['object'].terminate()
        
        # Start managers for new servers
        current_names = {m['name'] for m in active_list}
        for server_data in servers_data:
            if server_data['name'] not in current_names:
                self.log(f"Creating manager: {server_data['name']}")
                game_manager_object = GameManager(server_data['id'], server_data['name'], server_data['ports'])
                thread = threading.Thread(target=game_manager_object.run, name=f"GameManager-{server_data['name']}", daemon=False)
                thread.start()
                active_list.append({
                    'name': server_data['name'],
                    'object': game_manager_object,
                    'thread': thread
                })
        
        self.managers = active_list

    def start(self):
        """Main Orchestrator blocking loop."""
        self.log("Starting Orchestrator lifecycle...")
        self.update_managers()

        while True:
            try:
                pubsub = cache.subscribe_to_channel(self.commands_channel)
                for msg in pubsub.listen():
                    if msg['type'] != 'message': continue
                    try:
                        data = json.loads(msg['data']) if isinstance(msg['data'], str) else msg['data']
                        if data.get('command') == 'update-managers':
                            self.log("Managers update triggered")
                            self.update_managers()
                    except: continue
            except Exception as e:
                self.log(f"Cache link dropped: {e}")
                time.sleep(self.channel_listener_error_timeout)

    def shutdown(self):
        """Clean shutdown of all children."""
        self.log(f"System shutdown. Stopping {len(self.managers)} managers...")
        for manager in self.managers:
            manager['object'].terminate()
        for manager in self.managers:
            manager['thread'].join(timeout=self.managers_shutdown_timeout)
        self.log("Shutdown complete.")

if __name__ == "__main__":
    orchestrator = Orchestrator()
    try:
        orchestrator.start()
    except KeyboardInterrupt:
        pass
    finally:
        orchestrator.shutdown()
