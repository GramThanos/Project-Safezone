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
    def __init__(self, server_id, server_name, server_ports, initial_state="sleeping"):
        self.server_id = server_id
        self.server_name = server_name
        self.server_ports = server_ports
        self.server_script = '/opt/pzserver/start-server.sh'
        self.server_log_path = f'/tmp/game_server_{server_name}.log'

        # Thread-safe State Management
        self._state = initial_state
        self.state_lock = threading.Lock()
        
        # Process and Listener handles
        self.server_process = None
        self.onwake_thread = None
        self._onwake_stop_event = threading.Event()
        
        self.resource_lock = threading.Lock() # Guards ports and process spawning
        self.server_log_handle = None
        self._stop_event = threading.Event()
        
        self.game_server_quit_timeout = 60
        self.running_healthcheck_timeout = 5

        self.log(f"Initialized GameManager for server '{self.server_name}' with initial state '{self._state}'")

    @property
    def state(self):
        """Thread-safe getter for the desired server state."""
        with self.state_lock:
            return self._state

    @state.setter
    def state(self, value):
        """Thread-safe setter for the desired server state."""
        with self.state_lock:
            if self._state != value:
                self._state = value

    def log(self, message):
        ts = datetime.datetime.now().isoformat()
        print(f"[{ts}][Manager {self.server_name}][{self.state.upper()}] {message}")

    # --- Pollable State Helpers ---

    def _is_game_server_running(self):
        """Polls the game server process."""
        return self.server_process is not None and self.server_process.poll() is None

    def _is_onwake_running(self):
        """Polls the on-wake thread status."""
        return self.onwake_thread is not None and self.onwake_thread.is_alive()

    # --- Action Methods ---

    def manage_onwake(self, start=True):
        """Starts or stops the on-wake background listener."""
        with self.resource_lock:
            if start:
                if not self._is_onwake_running() and not self._is_game_server_running():
                    self._onwake_stop_event.clear()
                    self.onwake_thread = threading.Thread(target=self._onwake_worker, daemon=True)
                    self.onwake_thread.start()
            else:
                if self._is_onwake_running():
                    self.log("Stopping On-Wake listener...")
                    self._onwake_stop_event.set()
                    # We wait briefly for the thread to close sockets
                    self.onwake_thread.join(timeout=3.0) 

    def _onwake_worker(self):
        """Asynchronous UDP listener thread logic."""
        sockets = []
        try:
            for port in self.server_ports:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind(("0.0.0.0", port))
                    s.setblocking(False)
                    sockets.append(s)
                except Exception as e:
                    self.log(f"Bind Error {port}: {e}")

            self.log("On-Wake listener active.")
            while not self._onwake_stop_event.is_set() and self.state == "sleeping":
                if not sockets: break
                readable, _, _ = select.select(sockets, [], [], 0.5)
                if readable:
                    for s in readable:
                        data, addr = s.recvfrom(1024)
                        if data:
                            self.log(f"Wake packet from {addr}. Triggering wakeup.")
                            self.state = "running"
                            return # Exit thread so ports are freed
        finally:
            for s in sockets:
                s.close()
            self.log("On-Wake listener thread stopped.")

    def manage_server_process(self, start=True):
        """Starts or stops the game server subprocess."""
        with self.resource_lock:
            is_running = self._is_game_server_running()
            
            if start and not is_running:
                # CRITICAL: Stop the onwake listener and ensure it's dead before Popen
                if self._is_onwake_running():
                    self.log("On-Wake is running. Stopping it before server start...")
                    self._onwake_stop_event.set()
                    self.onwake_thread.join(timeout=5.0) 

                self.log("Launching game server process...")
                try:
                    self.server_log_handle = open(self.server_log_path, "a")
                    cmd = [self.server_script, "-servername", self.server_name]
                    self.server_process = subprocess.Popen(
                        cmd, stdin=subprocess.PIPE, stdout=self.server_log_handle,
                        stderr=subprocess.STDOUT, text=True, bufsize=1
                    )
                except Exception as e:
                    self.log(f"Spawn Error: {e}")
                    self.state = "stopped"
            
            elif not start and is_running:
                self.log("Shutting down game server...")
                try:
                    if self.server_process.stdin:
                        self.server_process.stdin.write("save\nquit\n")
                        self.server_process.stdin.flush()
                    self.server_process.wait(timeout=self.game_server_quit_timeout)
                except:
                    self.server_process.kill()
                finally:
                    if self.server_log_handle:
                        self.server_log_handle.close()
                        self.server_log_handle = None

    def run(self):
        """Reconciliation loop: compares desired state with polled truth."""
        threading.Thread(target=self.commands_listener, daemon=True).start()

        while not self._stop_event.is_set():
            current_goal = self.state
            game_alive = self._is_game_server_running()
            wake_alive = self._is_onwake_running()

            if current_goal == "sleeping":
                if game_alive:
                    self.manage_server_process(start=False)
                elif not wake_alive:
                    self.manage_onwake(start=True)

            elif current_goal == "running":
                # manage_server_process handles stop_onwake internally for safety
                if not game_alive:
                    self.manage_server_process(start=True)

            elif current_goal == "stopped":
                if game_alive:
                    self.manage_server_process(start=False)
                if wake_alive:
                    self.manage_onwake(start=False)

            self._stop_event.wait(timeout=self.running_healthcheck_timeout)

    def commands_listener(self):
        """Redis command listener to update desired state."""
        while not self._stop_event.is_set():
            pubsub = cache.subscribe_to_channel(config.MANAGE_GAME_SERVERS_CHANNEL)
            if not pubsub:
                time.sleep(5)
                continue
            try:
                for message in pubsub.listen():
                    if self._stop_event.is_set(): break
                    if message['type'] != 'message': continue
                    data = json.loads(message['data'])
                    if not 'server' in data or str(data['server']) != str(self.server_name): continue
                    cmd = data.get('command')
                    if cmd == "server-start": self.state = "running"
                    elif cmd == "server-stop": self.state = "stopped"
                    elif cmd == "server-sleep": self.state = "sleeping"
                    elif cmd == "server-command":
                        if self._is_game_server_running():
                            self.server_process.stdin.write(f"{data.get('data','')}\n")
                            self.server_process.stdin.flush()
            except:
                time.sleep(5)

    def terminate(self):
        """Full system shutdown."""
        self._stop_event.set()
        self.state = "stopped"
        self.manage_onwake(start=False)
        self.manage_server_process(start=False)


class Orchestrator:
    channel_listener_error_timeout = 5
    managers_shutdown_timeout = 60

    def __init__(self):
        self.managers = []
        self.commands_channel = config.MANAGE_GAME_SERVERS_CHANNEL
        self.log("Orchestrator initialized.")

    def log(self, message):
        ts = datetime.datetime.now().isoformat()
        print(f"[{ts}][Orchestrator] {message}")

    def update_managers(self):
        """Synchronizes database list with running threads."""
        try:
            with database.get_context_session() as session:
                db_servers = session.query(models.Server).all()
                servers_data = [
                    {
                        'id': s.id, 
                        'name': s.name, 
                        'ports': s.ports, 
                        'state': s.default_state
                    } 
                    for s in db_servers
                ]
        except Exception as e:
            self.log(f"DB Sync Error: {e}")
            return

        next_server_names = {s['name'] for s in servers_data}
        
        # Terminate removed
        active_list = []
        for m_entry in self.managers:
            if m_entry['name'] in next_server_names:
                active_list.append(m_entry)
            else:
                self.log(f"Removing manager: {m_entry['name']}")
                m_entry['object'].terminate()
        
        # Start new
        current_names = {m['name'] for m in active_list}
        for server_data in servers_data:
            if server_data['name'] not in current_names:
                self.log(f"Creating manager: {server_data['name']} (Init: {server_data['state']})")
                game_manager_object = GameManager(
                    server_data['id'], 
                    server_data['name'], 
                    server_data['ports'],
                    initial_state=server_data['state']
                )
                thread = threading.Thread(target=game_manager_object.run, name=f"GameManager-{server_data['name']}", daemon=False)
                thread.start()
                active_list.append({
                    'name': server_data['name'],
                    'object': game_manager_object,
                    'thread': thread
                })
        
        self.managers = active_list

    def start(self):
        self.log("Starting Orchestrator lifecycle...")
        self.update_managers()

        while True:
            try:
                pubsub = cache.subscribe_to_channel(self.commands_channel)
                for msg in pubsub.listen():
                    if msg['type'] != 'message': continue
                    try:
                        data = json.loads(msg['data']) if isinstance(msg['data'], str) else msg['data']
                        if 'server' in data: continue
                        if data.get('command') == 'update-managers':
                            self.log("Managers update triggered")
                            self.update_managers()
                    except: continue
            except Exception as e:
                self.log(f"Cache link dropped: {e}")
                time.sleep(self.channel_listener_error_timeout)

    def shutdown(self):
        self.log(f"System shutdown. Stopping {len(self.managers)} managers...")
        for manager in self.managers:
            manager['object'].terminate()
        for manager in self.managers:
            manager['thread'].join(timeout=self.managers_shutdown_timeout)
        self.log("Shutdown complete.")

# Logging
def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Game Manager] {message}")

if __name__ == "__main__":
    # Wait for DB
    _log("Checking database availability...")
    database.wait_table(models.Server, timeout=60*5)
    # Wait for Cache
    _log("Checking cache availability...")
    cache.wait()
    
    # Start Orchestrator
    orchestrator = Orchestrator()
    try:
        orchestrator.start()
    except KeyboardInterrupt:
        pass
    finally:
        orchestrator.shutdown()
