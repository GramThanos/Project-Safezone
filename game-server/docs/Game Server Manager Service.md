# Game Server Manager Service Documentation

The Game Server Manager Service is a high-performance, multi-threaded supervisor system designed to manage Project Zomboid dedicated servers. It features a "Sleep Mode" that monitors UDP ports to wake up servers on demand, significantly saving CPU and RAM resources.

---

## 1. System Architecture

The system follows a **Supervisor-Worker** pattern. It is split into two primary logical components: the **Orchestrator** and the **GameManager**.

### The Orchestrator (The "Brain")

The Orchestrator is the top-level process. Its responsibility is to ensure that the number of running manager threads matches the entries in the MariaDB database.

- **Dynamic Scaling:** It adds or removes manager threads in real-time without requiring a service restart.
- **MariaDB Sync:** It uses a thread-safe context manager to fetch server configurations (ID, Name, Ports).
- **Global Listener:** It listens to a Redis Pub/Sub channel for system-wide commands like `update-managers`.

### The GameManager (The "Worker")

Each game server is managed by its own dedicated `GameManager` thread. This isolation ensures that a crash or a long "save" sequence on one server does not impact others.

- **Sleep Mode (UDP Wake):** When a server is offline, the manager binds to the game ports and uses the `select` system call to wait for incoming player packets.
- **Process Supervision:** It monitors the PID of the game server. If the process dies unexpectedly, the manager detects it within 15 seconds and returns to sleep mode.
- **Graceful Shutdown:** It handles the `save` and `quit` sequence to prevent world data corruption.

---

## 2. Communication Protocol (Redis Pub/Sub)

All remote interactions occur via Redis. Messages must be sent as **JSON strings** to the channel defined in your configuration.

### A. Orchestrator Commands

| Command           | Payload Example                  | Description                                                            |
| ----------------- | -------------------------------- | ---------------------------------------------------------------------- |
| `update-managers` | `{"command": "update-managers"}` | Forces the Orchestrator to sync with the MariaDB database immediately. |

### B. Server Instance Commands

These commands require a `server` field matching the `server_name` in your database.

| Command          | Payload Example                                                   | Description                                     |
| ---------------- | ----------------------------------------------------------------- | ----------------------------------------------- |
| `server-start`   | `{"command": "server-start", "server": "pz01"}`                   | Manually wakes the server from sleep.           |
| `server-stop`    | `{"command": "server-stop", "server": "pz01"}`                    | Triggers the Save & Quit sequence.              |
| `server-command` | `{"command": "server-command", "server": "pz01", "data": "save"}` | Sends a raw text command to the server console. |

---

## 3. Implementation Details

### Thread Safety & Stability

- **Locking:** A `threading.Lock` is used during start/stop operations to prevent race conditions between Redis commands and UDP wake packets.
- **Event Signaling:** The system uses `threading.Event` for shutdown signals. This allows threads to exit loops instantly rather than waiting for long `sleep()` timers.
- **Resource Management:** \* **MariaDB:** Connections are opened and closed immediately using a Context Manager to avoid "Too many connections" errors.
- **Sockets:** UDP sockets are wrapped in `try...finally` blocks to ensure ports are always released, preventing "Address already in use" errors.

### Operational Constants

- **Health Check:** 15 seconds (checks if the game process is still alive).
- **Save Delay:** 10 seconds (time allowed for the `save` command before `quit`).
- **Shutdown Timeout:** 60 seconds (max time to wait for a graceful exit before forcing a kill).

---

## 4. Admin CLI Quick-Start

To interact with the manager from the Linux terminal using `redis-cli` (the default channel is `game_server_managers`):

**To refresh the server list after a DB change:**

```bash
redis-cli publish game_server_managers '{"command": "update-managers"}'

```

**To send a broadcast message to a specific server:**

```bash
redis-cli publish game_server_managers '{"command": "server-command", "server": "Survival_1", "data": "servermsg \"Hello Players!\""}'

```

---

# Game Server Orchestrator Protocol Documentation

This document defines the communication protocol for managing game servers via **Redis Pub/Sub**. The Orchestrator and GameManagers listen for JSON-formatted messages on the channel defined in `config.MANAGER_GAME_COMMANDS_CHANNEL`.

---

## 📡 Message Format

All messages must be published as **JSON strings**.

### Standard Fields

| Field     | Type   | Required    | Description                                                              |
| --------- | ------ | ----------- | ------------------------------------------------------------------------ |
| `command` | String | Yes         | The action to be executed.                                               |
| `server`  | String | Conditional | The name of the server to target (required for server-specific actions). |
| `data`    | String | Optional    | Payload data (e.g., the raw console command string).                     |

---

## 1. Orchestration Commands

These commands are processed by the main Orchestrator thread to manage the lifecycle of the Manager threads.

### `update-managers`

Synchronizes the running threads with the current state of the MariaDB database.

- **Target:** Orchestrator
- **Effect:** Starts new threads for added servers; terminates threads for removed servers.
- **Payload Example:**

```json
{
  "command": "update-managers"
}
```

---

## 2. Manager Commands

These commands are processed by individual GameManager threads. They must include a `server` field matching the `server_name` in the database.

### `server-start`

Manually brings a server online if it is currently stopped or in sleep mode.

- **Target:** Specific GameManager
- **Effect:** Executes the server start script.
- **Payload Example:**

```json
{
  "command": "server-start",
  "server": "zomboid_survival_01"
}
```

### `server-stop`

Triggers a graceful shutdown sequence.

- **Target:** Specific GameManager
- **Effect:** Sends `save`, waits 10s, sends `quit`, and kills the process if it hangs.
- **Payload Example:**

```json
{
  "command": "server-stop",
  "server": "zomboid_survival_01"
}
```

### `server-command`

Injects a raw string into the game server's console (stdin).

- **Target:** Specific GameManager
- **Effect:** Allows remote administration (kicking, broadcasting, etc.).
- **Payload Example:**

```json
{
  "command": "server-command",
  "server": "zomboid_survival_01",
  "data": "kickuser \"Griefer123\""
}
```

---

## 🛠️ Integration Examples

### Bash (via redis-cli)

To broadcast a message to all players on a specific server:

```bash
redis-cli publish game_server_managers '{"command": "server-command", "server": "pz_01", "data": "servermsg \"Restart in 10 minutes\""}'

```

### Python

```python
import redis
import json

r = redis.Redis(host='localhost', port=6379)
msg = {
    "command": "server-stop",
    "server": "pz_01"
}
r.publish('game_server_managers', json.dumps(msg))

```

---

## ⚠️ Safety & Constraints

1. **Thread Safety:** The system uses `threading.Lock()` to ensure that a `server-start` and a `server-stop` command do not execute at the same time for the same instance.
2. **Validation:** If the `server` field does not match a manager's `server_name`, the message is silently ignored by that thread.
3. **Persistence:** Redis Pub/Sub is "fire and forget." If the Orchestrator is offline when a message is sent, the command will not be executed.
