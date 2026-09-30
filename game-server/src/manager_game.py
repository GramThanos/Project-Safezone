#!/usr/bin/env python3
import os
import time
import socket
import datetime
import threading
import subprocess
import select
import json
import hashlib
import hmac
import re
import secrets
import struct

# Custom modules
import config
import cache
import models
import database
import roster
import servers
import events
import server_config

# Paths this manager touches or could touch, observed from a real install.
# Kept because they are the reference for the file layout the rest of the code
# assumes - `server_config.py` reads the .ini named here, and `mods.py` and
# `backups.py` sit alongside it.
#
#   /opt/steam-apps/ProjectZomboid{32,64}.json    launch parameters
#   /home/steam/Zomboid/Server/<name>.ini          server config  (server_config.py)
#   /home/steam/Zomboid/Server/<name>_spawnregions.lua
#   /home/steam/Zomboid/backups/                   the game's own backups, which
#                                                  are not the panel's (see BACKUP_DIR)
#   /home/steam/Zomboid/db/<name>.db               user database
#
# Not yet managed here: launch parameters, spawn regions, and the in-game admin
# account. `start-server.sh -nosteam` is the no-Steam launch option.

class GameManager:
    def __init__(self, server_id, server_name, server_ports, initial_state="sleeping",
                 idle_sleep_seconds=0):
        self.server_id = server_id
        self.server_name = server_name
        self.server_ports = server_ports
        # Configurable, because the right answer depends on how the game was
        # installed: SteamCMD with +force_install_dir puts start-server.sh at the
        # install root, a library-style install puts it under
        # steamapps/common/Project Zomboid Dedicated Server/. Override with
        # SERVER_SCRIPT if the server will not launch.
        self.server_script = config.SERVER_SCRIPT
        self.server_log_path = f'/tmp/game_server_{server_name}.log'

        # Thread-safe State Management
        #
        # First-boot provisioning. Project Zomboid writes its per-server INI
        # only on its first successful launch, and much of the panel (the config
        # and mod editors, the mod-usage listing) needs that file to exist. When
        # it is missing we boot the server once to generate it, then fall back to
        # the configured default - see the "initializing" branch in run(). A
        # server asked to run anyway needs no special handling (running writes
        # the config on its own), and an already-provisioned one skips straight
        # to its default. The INI's presence is the flag, so this is idempotent
        # across manager restarts with no state to track in the database.
        self.default_state = initial_state
        if initial_state != "running" and not self._config_exists():
            initial_state = "initializing"
        self._state = initial_state
        self.state_lock = threading.Lock()
        
        # Process and Listener handles
        self.server_process = None
        self.onwake_thread = None
        self._onwake_stop_event = threading.Event()

        # Set when the listener cannot bind a single port, which means the
        # server cannot be woken at all. Retried on an interval instead of every
        # reconcile pass, so a held port is not a five-second respawn loop.
        self.wake_bind_retry_interval = 60
        self._wake_bind_failed = False
        self._wake_retry_after = 0.0

        # A2S-intent wake heuristic. A Steam client's actual join is brokered by
        # Steam's networking layer, not sent as a UDP packet to the game port, so
        # a sleeping server never sees the join itself - the only signal it gets
        # that somebody wants in is the client's A2S query. So the wake is keyed
        # on that: a source that completes the IP-bound challenge (proving it is a
        # real client, not a spoofed amplification probe) and issues at least
        # `wake_a2s_threshold` authenticated A2S_INFO queries inside
        # `wake_a2s_window` seconds is treated as a join attempt.
        #
        # The threshold is the browse-vs-join dial. 1 wakes on first contact
        # (most eager - a server-list refresh wakes it too); higher values wait
        # for the repeated queries a client makes while a player sits on the
        # connect screen. A false wake costs one boot that idle-sleep undoes; a
        # missed wake is a player who cannot get in, so this is biased low.
        self.wake_a2s_threshold = config.WAKE_A2S_THRESHOLD
        self.wake_a2s_window = config.WAKE_A2S_WINDOW
        # Sources seen inside the window, pruned when the map grows rather than on
        # every packet, so a query flood cannot make this quadratic.
        self.wake_sources_max = 4096
        self._wake_a2s_hits = {}

        self.resource_lock = threading.Lock() # Guards ports and process spawning
        self.server_log_handle = None
        # The process whose exit has already been explained, so a death is
        # reported once rather than on every pass of the reconcile loop.
        self._exit_reported_for = None
        self._stop_event = threading.Event()
        self.stdin_lock = threading.Lock()  # Serializes console writes to the server

        # Online-player roster tracking. The generation counter identifies the
        # process launch a worker belongs to: a crash-restart starts a new worker
        # while the old one may still be parked in its interval wait, and only
        # the current generation is allowed to keep polling.
        self.roster_interval = 30
        self.online_players = []
        # The last *stable* state announced as a webhook event, so a change can
        # be announced once. Transient "restarting" is deliberately never stored
        # here: it is shown to the UI but not paged, so a crash that recovers
        # leaves this pointing at the last real state and emits nothing. None
        # until the first publish: a manager restart re-publishing what was
        # already true is not something to wake anybody for.
        self._published_state = None
        self.roster_thread = None
        self._roster_stop_event = threading.Event()
        self._roster_generation = 0

        # Idle auto-sleep. A server nobody is on still costs a full JVM heap, so
        # after this many seconds with an empty roster the desired state drops
        # back to "sleeping" and the wake listener takes the ports again. 0
        # disables it, which is the behaviour every server had before.
        #
        # `_roster_ready` is what keeps this honest: the roster is also empty for
        # the several minutes the game spends loading its world, and counting
        # that as idleness would put the server back to sleep just as it became
        # joinable. It flips true only once the server has actually answered a
        # `players` query, which is proof it is up.
        self.idle_sleep_seconds = idle_sleep_seconds or 0
        self._roster_ready = False
        self._idle_since = None
        # Whether the game version has been captured from the current launch's
        # boot log yet. Reset on every launch so a game update is re-captured.
        self._version_captured = False

        self.game_server_quit_timeout = 60
        self.running_healthcheck_timeout = 5

        # Crash-loop guard. Restarting a dead server is the right reflex, but an
        # unbounded one hides the outage: a server that dies on startup (bad mod,
        # corrupt save, port already bound) would otherwise respawn every health
        # check forever while the UI flickers back to "running". After
        # crash_threshold restarts inside crash_window the manager gives up and
        # parks in "failed" until an operator changes the desired state.
        self.crash_window = 300          # seconds a restart stays "recent"
        self.crash_threshold = 5         # restarts within the window before giving up
        self.crash_backoff_base = 5      # seconds; doubles per consecutive restart
        self.crash_backoff_cap = 300
        self._crash_lock = threading.Lock()
        self._restart_times = []
        self._backoff_until = 0.0
        self._last_start_at = 0.0
        self._failed = False

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
                # A deliberate state change is the operator saying "try again":
                # clear the crash history so a previously failed server is not
                # stuck refusing to start.
                self._reset_crash_tracking()
                # Whatever the new state is, the idle clock is about a run that
                # is now over. A plain assignment takes no lock, so it cannot
                # invert the state_lock -> _crash_lock order taken above.
                self._idle_since = None
                # Same reasoning for the bind verdict: asking for a state again
                # means "try again", so the listener gets a fresh attempt rather
                # than sitting out the retry interval it was given.
                self._wake_bind_failed = False
                self._wake_retry_after = 0.0

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

    def _config_exists(self):
        """Whether PZ has already written this server's INI.

        Its presence is proof the server has booted at least once, and is what
        the first-boot provisioning in run() keys off. Read from disk every time
        rather than cached: the file appears partway through the very boot this
        check governs.
        """
        path = server_config.path_for(self.server_name)
        return bool(path) and os.path.isfile(path)

    def _reset_crash_tracking(self):
        """Forget recent restarts, clearing any backoff or failed verdict."""
        with self._crash_lock:
            self._restart_times = []
            self._backoff_until = 0.0
            self._failed = False

    def _may_restart(self):
        """Whether the reconciler is allowed to respawn a dead server right now.

        Returns False while backing off, and permanently (until the desired state
        changes) once the server has proved it cannot stay up.

        Nothing is logged while ``_crash_lock`` is held: ``log()`` reads
        ``self.state`` and so takes ``state_lock``, while the state setter takes
        ``state_lock`` and then this lock. Logging inside would invert that order
        and can deadlock. ``_crash_lock`` is a leaf - it acquires nothing.
        """
        now = time.monotonic()
        message = None
        with self._crash_lock:
            if self._failed:
                return False

            # Only restarts inside the window count toward the threshold.
            self._restart_times = [t for t in self._restart_times
                                   if now - t < self.crash_window]

            if len(self._restart_times) >= self.crash_threshold:
                self._failed = True
                message = (f"CRASH LOOP: {len(self._restart_times)} restarts in "
                           f"{self.crash_window}s. Giving up - the server will stay "
                           f"down until its desired state is set again.")
                allowed = False
            elif now < self._backoff_until:
                allowed = False
            else:
                attempt = len(self._restart_times)
                delay = min(self.crash_backoff_base * (2 ** attempt), self.crash_backoff_cap)
                self._restart_times.append(now)
                self._backoff_until = now + delay
                if attempt:
                    message = (f"Restart attempt {attempt + 1} after a crash; "
                               f"backing off {delay}s before the next one.")
                allowed = True

        if message:
            self.log(message)
        return allowed

    def _note_healthy_run(self):
        """Clear the crash history once a launch has stayed up past the window."""
        with self._crash_lock:
            if not self._restart_times or self._failed:
                return
            if self._last_start_at and time.monotonic() - self._last_start_at > self.crash_window:
                self._restart_times = []
                self._backoff_until = 0.0

    def set_idle_sleep_seconds(self, seconds):
        """Apply a new idle timeout to a live manager.

        Unlike the ports, this needs no rebuild - it is a number the reconcile
        loop reads on its next pass - so an operator changing it does not cost
        the players on the server their session.
        """
        seconds = seconds or 0
        if seconds == self.idle_sleep_seconds:
            return
        self.log(f"Idle sleep timeout: {self.idle_sleep_seconds}s -> {seconds}s")
        self.idle_sleep_seconds = seconds
        self._idle_since = None

    def _reconcile_initializing(self, game_alive):
        """One reconcile pass for the first-boot provisioning state.

        Boots the server once so Project Zomboid writes its INI, then hands off
        to the configured default. Split out of run() so it can be exercised on
        its own. See the note in __init__ for why this state exists.
        """
        if not game_alive:
            # If the config is already there - a manager restart caught
            # mid-provision, or a boot that finished between passes - there is
            # nothing to generate; go straight to the default.
            if self._config_exists():
                self.state = self.default_state
            elif self._may_restart():
                self._last_start_at = time.monotonic()
                self.manage_server_process(start=True)
            else:
                # Repeatedly failed to boot; say why. _publish_live_state reports
                # "failed", and it parks until the state is set again, exactly as
                # a crash-looping "running" server does.
                self._report_exit()
        else:
            # Booting. Wait until the server has genuinely come up (answered a
            # `players` query) so the INI it writes is complete, then fall back
            # to the default - the stopped / sleeping branch does the graceful
            # save+quit from there. The INI appears early in boot, so
            # file-existence alone is not enough to prove it is safe to shut down.
            self._note_healthy_run()
            if self._roster_ready:
                self.log("First boot complete; configuration generated. "
                         f"Applying default state '{self.default_state}'.")
                self.state = self.default_state

    def _check_idle_sleep(self):
        """Put a running server with nobody on it back to sleep.

        Called once per reconcile pass while the game process is up. Returns
        without arming anything until the roster worker has had an answer out of
        the server, so the quiet minutes while the world loads are not mistaken
        for an idle server.
        """
        if self.idle_sleep_seconds <= 0:
            self._idle_since = None
            return
        if not self._roster_ready:
            return
        if self.online_players:
            self._idle_since = None
            return

        now = time.monotonic()
        if self._idle_since is None:
            self._idle_since = now
            self.log(f"Nobody online; going to sleep in {self.idle_sleep_seconds}s "
                     f"unless somebody joins.")
        elif now - self._idle_since >= self.idle_sleep_seconds:
            self.log(f"Idle for {int(now - self._idle_since)}s with nobody online. "
                     f"Sleeping.")
            # The reconcile loop's "sleeping" branch does the rest: it shuts the
            # process down gracefully (save, then quit) and re-arms the wake
            # listener on the way out.
            self.state = "sleeping"

    def _publish_live_state(self):
        """Publish the actual runtime state to the cache for the web UI to read."""
        if self._is_game_server_running():
            actual = "running"
        elif self._is_onwake_running():
            actual = "sleeping"
        elif self._failed or self._wake_bind_failed:
            # Wanted up, repeatedly could not stay up - or wanted to be wakeable
            # and could not bind the ports to listen on. Distinct from
            # "stopped", which means somebody asked for it.
            actual = "failed"
        elif self.state in ("running", "initializing"):
            # Dead, but nobody asked for it down: the reconciler is about to
            # relaunch it this pass, or is backing off between attempts (and
            # first-boot provisioning is the same coming-up case). Reporting
            # "stopped" here would flap the UI and page every webhook on a
            # transient hiccup, so this is its own state - shown, not paged.
            actual = "restarting"
        else:
            actual = "stopped"
        # TTL well above the reconcile interval so the key survives between loops
        # but expires if this manager dies.
        cache.set_value(f"server:{self.server_id}:state", actual, ttl=30)

        # "restarting" is a transient the UI shows but subscribers are not paged
        # for: skip the event and leave _published_state on the last real state,
        # so a crash that recovers emits nothing while one that gives up still
        # emits server.failed from the branch above once _failed latches.
        if actual == "restarting":
            return
        if actual != self._published_state:
            if self._published_state is not None:
                # "failed" is its own event because it is the one an operator
                # wants in a channel they actually watch, without subscribing to
                # every wake and sleep. Exactly one event per transition, so a
                # webhook listening to both does not hear the failure twice.
                events.emit('server.failed' if actual == 'failed' else 'server.state',
                            server_id=self.server_id, server_name=self.server_name,
                            state=actual, previous=self._published_state)
            self._published_state = actual

    def _send_console(self, text, ack_id=None):
        """Write a single console command to the running server's stdin.

        When ``ack_id`` is given, the outcome is published to
        ``cmd_ack:<ack_id>`` so the dispatcher can tell an actually-written
        command from one that was dropped because the server was not running.
        Without this, a publish to a dead server looks identical to a delivery.
        """
        written = False
        detail = 'server not running'
        with self.stdin_lock:
            if self._is_game_server_running() and self.server_process.stdin:
                try:
                    self.server_process.stdin.write(f"{text}\n")
                    self.server_process.stdin.flush()
                    written = True
                except Exception as e:
                    detail = f'write failed: {e}'
                    self.log(f"Console write failed: {e}")

        if ack_id:
            cache.set_value(
                f"{config.COMMAND_ACK_PREFIX}{ack_id}",
                json.dumps({'ok': written, 'detail': None if written else detail}),
                ttl=config.COMMAND_ACK_TTL
            )
        if not written:
            self.log(f"Console command dropped ({detail}): {text}")
        return written

    def _report_roster_change(self, before, after):
        """Queue who joined and who left, for the backend's webhook alerts.

        Comparing samples rather than reading the log for connect lines: the
        roster is the one view of who is on that is already parsed and already
        trusted for claims and deliveries, so joins reported here can never
        disagree with what the rest of the stack believes.
        """
        joined = [name for name in after if name not in before]
        left = [name for name in before if name not in after]
        for name in joined:
            events.emit('player.join', server_id=self.server_id,
                        server_name=self.server_name, player=name, online=len(after))
        for name in left:
            events.emit('player.leave', server_id=self.server_id,
                        server_name=self.server_name, player=name, online=len(after))

    def _roster_worker(self, generation):
        """Periodically query online players and publish them to the cache.

        Tails the server log, issues the `players` command each interval, and
        parses the response so the website can validate identity claims and
        deliveries against who is actually online.

        ``generation`` is the process launch this worker was started for; it
        stops as soon as a newer launch supersedes it.
        """
        roster_key = f"server:{self.server_id}:online_players"
        try:
            with open(self.server_log_path, "r") as reader:
                reader.seek(0, 2)  # Tail from the end of the log
                while (not self._roster_stop_event.is_set()
                       and self._roster_generation == generation
                       and self._is_game_server_running()):
                    self._send_console("players")
                    # Wait for the server to print the response before reading.
                    if self._roster_stop_event.wait(timeout=self.roster_interval):
                        break
                    # A newer launch may have superseded us during that wait. Bail
                    # before touching the shared roster, so a retired generation
                    # cannot publish a stale sample or emit phantom join/leave
                    # events over its replacement's roster.
                    if self._roster_generation != generation:
                        break
                    try:
                        new_text = reader.read()
                    except Exception as e:
                        self.log(f"Roster log read error: {e}")
                        new_text = ""
                    parsed = roster.parse_online_players(new_text)
                    if parsed is not None:
                        # Only once a baseline exists. The first answer after a
                        # launch says who is already on, and announcing that as
                        # a burst of joins would make every manager restart look
                        # like a rush of players.
                        if self._roster_ready:
                            self._report_roster_change(self.online_players, parsed)
                        self.online_players = parsed
                        # The server answered `players`, so it is genuinely up:
                        # an empty roster from here on is idleness, not a world
                        # still loading. This is what arms the idle timeout.
                        self._roster_ready = True
                    cache.set_value(roster_key, json.dumps(self.online_players), ttl=self.roster_interval * 3)
                    # Persist a sample so the site can chart player activity.
                    servers.record_player_count(self.server_id, len(self.online_players))
        except FileNotFoundError:
            self.log("Roster worker: server log not found.")
        except Exception as e:
            self.log(f"Roster worker error: {e}")
        finally:
            # A superseded worker must not clear the roster its replacement is
            # already publishing, nor record a phantom drop to zero. Nor is the
            # emptying announced as everybody leaving: the server going away is
            # one event (`server.state`), not one per player who was on it.
            if self._roster_generation == generation:
                self.online_players = []
                cache.set_value(roster_key, json.dumps([]), ttl=self.roster_interval * 3)
                # Record the drop to zero so the chart shows the server going offline.
                servers.record_player_count(self.server_id, 0)
                self.log("Roster worker stopped.")
            else:
                self.log(f"Roster worker (generation {generation}) superseded.")

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


    # Protocol Constants
    A2S_HEADER = b"\xff\xff\xff\xff"
    RAKNET_MAGIC = b"\x00\xff\xff\x00\xfe\xfe\xfe\xfe\xfd\xfd\xfd\xfd\x12\x34\x56\x78"

    # A2S query request types (the byte after the 0xffffffff header). A full
    # server-browser refresh sends all three; answering only INFO leaves the
    # browser showing no player count and no ping detail, and some clients will
    # not treat the server as fully reachable until PLAYER/RULES also answer.
    A2S_INFO_REQ = ord("T")    # 0x54 -> reply 'I' (0x49)
    A2S_PLAYER_REQ = ord("U")  # 0x55 -> reply 'D' (0x44)
    A2S_RULES_REQ = ord("V")   # 0x56 -> reply 'E' (0x45)
    A2S_QUERY_TYPES = (A2S_INFO_REQ, A2S_PLAYER_REQ, A2S_RULES_REQ)
    A2S_CHALLENGE_REPLY = ord("A")  # 0x41, the S2C_CHALLENGE header byte
    # The "I have no challenge yet" placeholder a client sends in its first
    # PLAYER/RULES request; the reply is a challenge for it to echo back.
    A2S_NO_CHALLENGE = b"\xff\xff\xff\xff"

    # RakNet Packet IDs
    RAKNET_ID_UNCONNECTED_PING = 0x01
    RAKNET_ID_UNCONNECTED_PING_OPEN = 0x02
    RAKNET_ID_UNCONNECTED_PONG = 0x1C
    RAKNET_ID_OPEN_CONNECTION_REQUEST_1 = 0x05  # Actual client join initiation

    def _is_server_info_request(self, data: bytes) -> bool:
        """Returns True for any Steam A2S query or a RakNet Unconnected Ping."""
        is_a2s = (data.startswith(self.A2S_HEADER) and len(data) >= 5
                  and data[4] in self.A2S_QUERY_TYPES)
        is_raknet = len(data) >= 25 and data[0] in (
            self.RAKNET_ID_UNCONNECTED_PING,
            self.RAKNET_ID_UNCONNECTED_PING_OPEN,
        )
        return is_a2s or is_raknet

    def _player_trying_to_connect(self, data: bytes) -> bool:
        """Detects explicit RakNet join attempts (OPEN_CONNECTION_REQUEST_1).

        This is the direct-IP / non-Steam path, where the join really is a UDP
        packet on the game port. Steam clients never reach here (their join goes
        over Steam's network); those are handled by the A2S-intent heuristic.
        """
        return len(data) >= 18 and data[0] == self.RAKNET_ID_OPEN_CONNECTION_REQUEST_1

    def _note_a2s_intent(self, ip: str) -> bool:
        """Record an authenticated A2S_INFO from ``ip``; True once it wants in.

        Keyed by source address so one client's repeated queries accumulate while
        a sweep touching many addresses once never does. Returns True when the
        source has reached ``wake_a2s_threshold`` hits inside ``wake_a2s_window``.
        """
        now = time.monotonic()
        cutoff = now - self.wake_a2s_window
        hits = self._wake_a2s_hits

        # Pruned on growth, not per packet: pruning every packet would make a
        # query flood quadratic in the number of sources.
        if len(hits) > self.wake_sources_max:
            for address in list(hits):
                fresh = [t for t in hits[address] if t > cutoff]
                if fresh:
                    hits[address] = fresh
                else:
                    del hits[address]

        recent = [t for t in hits.get(ip, ()) if t > cutoff]
        recent.append(now)
        hits[ip] = recent
        return len(recent) >= self.wake_a2s_threshold

    STEAM_APP_ID = 380870  # Project Zomboid dedicated server AppID

    # A dotted version token: 42, 42.20, 42.20.4, 42.20.4.1 all match. Anchored
    # to a non-digit boundary so a build id (24775771) is not mistaken for one.
    _VERSION_RE = re.compile(r'(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)')
    # Lines that carry a *Java/JVM* version, not the game's - filtered out before
    # the game-version pattern is applied so "java.version=17.0.9" cannot win.
    _JAVA_LINE_RE = re.compile(r'(?i)\b(java|jre|jdk|jvm|openjdk|hotspot)\b')

    def _scan_log_for_version(self, text: str):
        """Return the game version found in boot-log ``text``, or None."""
        pattern = re.compile(config.GAME_VERSION_LOG_PATTERN)
        for line in text.splitlines():
            if self._JAVA_LINE_RE.search(line):
                continue
            match = pattern.search(line)
            if match:
                return match.group(1)
        return None

    def _maybe_capture_version(self):
        """Capture the game version from the boot log, once per launch.

        The game prints its version early in boot, before the roster worker
        (which tails from the end of the log) is even listening, so this reads
        the whole current log from the top. On success the value is persisted to
        ``GAME_VERSION_CACHE_FILE`` - surviving the server sleeping and this
        manager restarting - and published for the web UI. Guarded by
        ``_version_captured`` so it scans at most once per server launch.
        """
        if self._version_captured:
            return
        try:
            with open(self.server_log_path, 'r', encoding='utf-8',
                      errors='replace') as handle:
                text = handle.read()
        except FileNotFoundError:
            return
        except OSError as e:
            self.log(f"[version] could not read server log: {e}")
            self._version_captured = True  # don't retry a broken read every pass
            return

        version = self._scan_log_for_version(text)
        if not version:
            return  # version line may not have been printed yet; try next pass

        self._version_captured = True
        cache.set_value("game:version", version)  # no TTL: it changes only on update
        try:
            with open(config.GAME_VERSION_CACHE_FILE, 'w', encoding='utf-8') as handle:
                handle.write(version + "\n")
            self.log(f"[version] captured game version {version} from boot log.")
        except OSError as e:
            self.log(f"[version] captured {version} but could not persist it "
                     f"to {config.GAME_VERSION_CACHE_FILE}: {e}")

    def _resolve_game_version(self) -> str:
        """The game version to advertise while sleeping.

        See config.py for the resolution order: explicit GAME_VERSION override,
        then the value captured from the boot log, then an optional install file,
        then the fallback. Resolved once per sleep cycle onto ``_emu_version``.
        """
        if config.GAME_VERSION:
            return config.GAME_VERSION

        for path in (config.GAME_VERSION_CACHE_FILE, config.GAME_VERSION_FILE):
            if not path:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as handle:
                    match = self._VERSION_RE.search(handle.read(8192))
                if match:
                    return match.group(1)
            except FileNotFoundError:
                continue
            except OSError as e:
                self.log(f"[version] could not read {path}: {e}")

        self.log(f"[version] no captured version yet; advertising fallback "
                 f"{config.GAME_VERSION_FALLBACK}. It is captured on first boot.")
        return config.GAME_VERSION_FALLBACK

    def _build_a2s_info_response(self) -> bytes:
        """Constructs an A2S_INFO payload reporting 0 active players."""
        payload = bytearray(self.A2S_HEADER + b"I")
        payload.append(17)  # Protocol version
        payload.extend(self._emu_server_name.encode("utf-8") + b"\x00")
        payload.extend(b"Muldraugh, KY\x00")  # Map name
        payload.extend(b"projectzomboid\x00")  # Folder
        payload.extend(b"Project Zomboid\x00")  # Game
        # The 16-bit AppID field only holds the low word; the full AppID goes in
        # the 64-bit GameID field below (Extra Data Flag 0x01).
        payload.extend(struct.pack("<H", self.STEAM_APP_ID & 0xFFFF))  # Steam AppID
        payload.append(0)  # Current players
        payload.append(self._emu_max_players)  # Max players
        payload.append(0)  # Bots
        payload.append(ord("d"))  # Server type (Dedicated)
        payload.append(ord("l"))  # OS (Linux = 'l', Windows = 'w')
        payload.append(0)  # Password required (0 = No)
        payload.append(1)  # VAC enabled
        # Version string (null-terminated). REQUIRED by the A2S_INFO layout and
        # sits between the VAC byte and the Extra Data Flag - omitting it shifts
        # every following byte, so the client reads the EDF/GameID as the version
        # string and rejects the packet (ping -1, no player count).
        payload.extend(self._emu_version.encode("utf-8") + b"\x00")
        payload.append(0x01)  # Extra Data Flag: GameID present
        payload.extend(struct.pack("<Q", self.STEAM_APP_ID))  # 64-bit GameID
        return bytes(payload)

    def _build_a2s_player_response(self) -> bytes:
        """A2S_PLAYER reply for a sleeping (empty) server: zero players."""
        # header + 'D' + player count (0). Per-player records follow when >0.
        return self.A2S_HEADER + b"D" + bytes([0])

    def _build_a2s_rules_response(self) -> bytes:
        """A2S_RULES reply advertising the game version as the sole rule."""
        rules = {b"version": self._emu_version.encode("utf-8")}
        payload = bytearray(self.A2S_HEADER + b"E")
        payload.extend(struct.pack("<H", len(rules)))  # rule count (short)
        for name, value in rules.items():
            payload.extend(name + b"\x00")
            payload.extend(value + b"\x00")
        return bytes(payload)

    def _build_raknet_pong(self, data: bytes) -> bytes:
        """Constructs a RakNet RAKNET_ID_UNCONNECTED_PONG payload."""
        client_timestamp = data[1:9] if len(data) >= 9 else b"\x00" * 8
        server_guid = b"\x01\x02\x03\x04\x05\x06\x07\x08"

        pong_str = (
            f"{self._emu_server_name};0;{self._emu_max_players};"
            f"v{self._emu_version};0".encode("utf-8")
        )
        str_len = struct.pack(">H", len(pong_str))

        return (
            bytes([self.RAKNET_ID_UNCONNECTED_PONG])
            + client_timestamp
            + server_guid
            + self.RAKNET_MAGIC
            + str_len
            + pong_str
        )

    def _generate_challenge(self, ip: str) -> bytes:
        """Computes a 4-byte HMAC derived from the client IP and secret."""
        return hmac.new(self._emu_secret, ip.encode("utf-8"), hashlib.sha256).digest()[
            :4
        ]

    def _a2s_received_challenge(self, data: bytes, qtype: int):
        """The challenge a client echoed back, or None if it has none yet.

        The three query types carry the challenge differently: INFO appends it
        after the "Source Engine Query\\0" string (so a bare request is 25 bytes
        and a challenged one is longer), while PLAYER and RULES put a 4-byte
        challenge field right after the type byte, using 0xffffffff to mean "send
        me one". Returning None means "no challenge yet -> reply with one".
        """
        if qtype == self.A2S_INFO_REQ:
            return data[-4:] if len(data) > 25 else None
        # PLAYER / RULES: 4-byte challenge field at offset 5.
        field = data[5:9]
        if len(field) < 4 or field == self.A2S_NO_CHALLENGE:
            return None
        return field

    def _handle_server_info_request(self, data: bytes, s, addr) -> bool:
        """Answer a Steam A2S query or RakNet ping. True if it is a join intent.

        Returns True only when an authenticated A2S_INFO pushes the source over
        the wake threshold - the loop turns that into a wake. Every other case
        (a challenge round-trip, PLAYER/RULES, a RakNet pong) returns False: it
        is answered to stay visible, but it is not by itself somebody joining.
        """
        ip = addr[0]

        # Handle the Steam A2S query family (INFO / PLAYER / RULES). All three
        # are gated behind the same IP-bound HMAC challenge: a first request with
        # no challenge is answered with one, and only a request echoing the
        # correct challenge gets the real payload. This is the anti-spoofing /
        # anti-amplification step every modern Source query server does.
        if data.startswith(self.A2S_HEADER) and len(data) >= 5 \
                and data[4] in self.A2S_QUERY_TYPES:
            qtype = data[4]
            challenge = self._generate_challenge(ip)
            received = self._a2s_received_challenge(data, qtype)

            if received is None or not hmac.compare_digest(received, challenge):
                # No challenge yet, or a wrong/spoofed one: (re)issue a fresh one.
                s.sendto(self.A2S_HEADER + bytes([self.A2S_CHALLENGE_REPLY])
                         + challenge, addr)
                return False

            if qtype == self.A2S_INFO_REQ:
                s.sendto(self._build_a2s_info_response(), addr)
                # An authenticated INFO is a real client asking about this server
                # right now - the only join signal a Steam client ever gives us.
                return self._note_a2s_intent(ip)
            elif qtype == self.A2S_PLAYER_REQ:
                s.sendto(self._build_a2s_player_response(), addr)
            else:  # A2S_RULES_REQ
                s.sendto(self._build_a2s_rules_response(), addr)
            return False

        # Handle RakNet Direct IP Ping. Unlike the A2S branch above, this answers
        # without an IP-bound challenge: RakNet's unconnected ping has no
        # challenge/response step, and the pong's amplification factor is low
        # (~1.4x). Intentionally unauthenticated - consistent with the project's
        # no-rate-limiting stance; do not assume parity with the A2S hardening.
        elif data[0] in (self.RAKNET_ID_UNCONNECTED_PING, self.RAKNET_ID_UNCONNECTED_PING_OPEN):
            s.sendto(self._build_raknet_pong(data), addr)
        return False

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

            # Binding nothing means the server can never be woken
            if not sockets:
                self._wake_bind_failed = True
                self._wake_retry_after = time.monotonic() + self.wake_bind_retry_interval
                self.log(f"On-Wake listener could not bind any of {self.server_ports}; "
                         f"Retrying in {self.wake_bind_retry_interval}s.")
                return
            self._wake_bind_failed = False
            self._wake_retry_after = 0.0

            # Prepare server emulation info
            self._emu_server_name = self.server_name + ' (sleeping)'
            self._emu_max_players = 32
            self._emu_secret = secrets.token_bytes(16)
            self._emu_version = self._resolve_game_version()
            self.log(f"On-Wake emulation reporting game version {self._emu_version}.")

            self.log(f"On-Wake listener active on {[s.getsockname()[1] for s in sockets]}.")
            while not self._onwake_stop_event.is_set() and self.state == "sleeping":
                readable, _, _ = select.select(sockets, [], [], 0.5)
                for s in readable:
                    try:
                        data, addr = s.recvfrom(2048)
                    except OSError as e:
                        self.log(f"Wake listener read error: {e}")
                        continue

                    if not data:
                        continue

                    # --- WAKE DEBUG TRACE ---------------------------------------
                    # Every datagram the sleeping listener sees, so a join
                    # handshake can be captured. `local` is the port it arrived
                    # on (game vs query), `head` the first bytes in hex. Behind
                    # config.WAKE_DEBUG: the game port is public, so unguarded
                    # this logs a line per scan packet and records player IPs.
                    if config.WAKE_DEBUG:
                        local_port = s.getsockname()[1]
                        head = data[:32].hex(" ")
                        self.log(
                            f"[wake-debug] rx {len(data)}B on :{local_port} "
                            f"from {addr[0]}:{addr[1]} first32=[{head}]"
                        )
                    # -----------------------------------------------------------

                    # Direct-IP / non-Steam join: the join really is a UDP packet
                    # on the game port, so wake on it immediately.
                    if self._player_trying_to_connect(data):
                        self.log(f"Wake triggered by connection request from {addr[0]}:{addr[1]}")
                        self.state = "running"
                        return  # Exit thread so ports are freed

                    # Steam browser/client A2S query (or RakNet ping): answer it to
                    # stay visible. A Steam client's real join never reaches us as a
                    # packet, so the handler also decides - from repeated
                    # authenticated A2S_INFO queries - when a source is a join
                    # attempt rather than a passing browse, and we wake on that.
                    if self._is_server_info_request(data):
                        try:
                            wake = self._handle_server_info_request(data, s, addr)
                            if config.WAKE_DEBUG:
                                self.log(f"[wake-debug] answered A2S/ping "
                                         f"(byte0=0x{data[0]:02x}) wake={wake}")
                        except Exception as e:
                            wake = False
                            self.log(f"Emulated server info sent to {addr[0]}:{addr[1]} failed: {e}")
                        if wake:
                            self.log(f"Wake triggered by A2S join intent from {addr[0]}:{addr[1]}")
                            self.state = "running"
                            return  # Exit thread so ports are freed
                        continue

                    # Neither a join nor a known info query: this is where a real
                    # client's handshake would land if its signature is not the
                    # one `_player_trying_to_connect` expects, and so the packet
                    # to look at when a server will not wake. Same gate - on a
                    # public port this is otherwise one line per stray scan.
                    if config.WAKE_DEBUG:
                        self.log(
                            f"[wake-debug] DROPPED (no wake, no reply) "
                            f"byte0=0x{data[0]:02x} len={len(data)} from {addr[0]}:{addr[1]}"
                        )

        finally:
            for s in sockets:
                s.close()
            self.log("On-Wake listener thread stopped.")

    # Directories the game expects to find under its data directory. On a fresh
    # volume it does not create them itself before using them, and each one it
    # trips over throws a Java exception that names the path but not the reason:
    #
    #   java.io.FileNotFoundException: .../Zomboid/Server/<name>.ini
    #       (No such file or directory)          - writing the server config
    #   java.nio.file.NoSuchFileException: .../Zomboid/mods
    #       ... LinuxWatchService$Poller          - registering a file watch
    #
    # Two flavours, same cause: the ones it writes into (Server, Saves, db,
    # Logs) and the ones it only watches or reads (mods, Workshop, Lua). The
    # watched ones are the more confusing failure, because an empty mods folder
    # is a perfectly normal thing to have - it just has to exist.
    #
    # `backups` is the game's own world backups, not the panel's (those go to
    # BACKUP_DIR, on their own volume) - it is here because it is the same
    # layout, documented at the top of this file, and the same failure waiting
    # to happen on the first save.
    DATA_SUBDIRS = (
        'Server', os.path.join('Saves', 'Multiplayer'), 'db', 'Logs',
        'mods', 'Workshop', 'Lua', 'backups',
    )

    def _ensure_data_dirs(self):
        """Create the game's data directories, and say plainly if we cannot.

        Two different failures produce almost the same Java stack trace, and
        neither trace names the cause: the directory does not exist (fresh
        volume), or it exists but belongs to another user (a volume created
        root-owned before the image had the mountpoint - see the Dockerfile).
        Both are worth catching here, before the process is launched, where the
        message can say which one it is.
        """
        root = config.ZOMBOID_DATA_DIR
        for relative in self.DATA_SUBDIRS:
            path = os.path.join(root, relative)
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as e:
                self.log(f"Could not create the game data directory {path}: {e}")

        if not os.access(root, os.W_OK):
            uid = os.getuid() if hasattr(os, 'getuid') else 'unknown'
            self.log(
                f"WARNING: {root} is not writable by this process (uid {uid}). "
                "The game will fail to write its config and saves. The data "
                "volume is most likely root-owned; recreate it, or chown it to "
                "steam."
            )

    HEAP_FLAG = '-Xmx'

    def _launch_params(self):
        """The pzexe launch parameters as a dict, or None if unreadable."""
        try:
            with open(config.LAUNCH_PARAMS_FILE, 'r', encoding='utf-8') as handle:
                return json.load(handle)
        except (OSError, ValueError) as e:
            self.log(f"Could not read the launch parameters at "
                     f"{config.LAUNCH_PARAMS_FILE}: {e}")
            return None

    def _configured_heap(self, params=None):
        """The `-Xmx` value the game will launch with, as text, or None."""
        params = params if params is not None else self._launch_params()
        for arg in (params or {}).get('vmArgs') or []:
            if str(arg).startswith(self.HEAP_FLAG):
                return str(arg)[len(self.HEAP_FLAG):]
        return None

    # Collectors worth choosing between. Project Zomboid ships ZGC, which is
    # built for large heaps and spare cores to run its concurrent phases on. On
    # a small heap, an old CPU, or few cores, G1 gives most of the benefit for
    # less overhead and less reserved memory - and Serial is a reasonable answer
    # on one or two cores. Named rather than free-text so a typo cannot produce
    # a JVM that will not boot.
    GC_CHOICES = {
        'Z': '-XX:+UseZGC',
        'G1': '-XX:+UseG1GC',
        'Parallel': '-XX:+UseParallelGC',
        'Serial': '-XX:+UseSerialGC',
    }

    @staticmethod
    def _is_gc_arg(arg):
        """Whether a vmArg selects a garbage collector."""
        text = str(arg)
        return ((text.startswith('-XX:+Use') or text.startswith('-XX:-Use'))
                and text.endswith('GC')) or 'ZGenerational' in text

    # Half the memory the container may use, which leaves the other half for
    # the JVM's own overhead (metaspace, thread stacks, GC structures, the
    # native game libraries) and for whatever else shares the machine - on a
    # single-box deployment that is the database, the cache and the web tier.
    HEAP_FRACTION = 0.5
    # Below this the game will struggle whatever we do; above it, a dedicated
    # server sees little benefit and the operator can set a number by hand.
    HEAP_FLOOR_MB = 1024
    HEAP_CAP_MB = 8192

    @staticmethod
    def _read_first_line(path):
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                return handle.readline().strip()
        except OSError:
            return None

    def _memory_budget_mb(self):
        """Memory this container may use, in MB, or None if it cannot be told.

        The container's own limit when one is set, otherwise the machine's. Both
        are consulted because `/proc/meminfo` inside a container reports the
        host's total, which would be a wild overestimate under a memory limit.
        """
        candidates = []

        for path in ('/sys/fs/cgroup/memory.max',                     # cgroup v2
                     '/sys/fs/cgroup/memory/memory.limit_in_bytes'):  # cgroup v1
            raw = self._read_first_line(path)
            if not raw or raw == 'max':
                continue
            try:
                value = int(raw)
            except ValueError:
                continue
            # cgroup v1 reports a sentinel near 2^63 to mean "no limit".
            if 0 < value < (1 << 62):
                candidates.append(value)

        try:
            with open('/proc/meminfo', 'r', encoding='utf-8') as handle:
                for line in handle:
                    if line.startswith('MemTotal:'):
                        candidates.append(int(line.split()[1]) * 1024)
                        break
        except (OSError, ValueError, IndexError):
            pass

        return int(min(candidates) / (1024 * 1024)) if candidates else None

    def _cpu_budget(self):
        """CPUs this container may use, honouring a cgroup quota if there is one."""
        raw = self._read_first_line('/sys/fs/cgroup/cpu.max')          # "<quota> <period>"
        if raw and not raw.startswith('max'):
            try:
                quota, period = (int(part) for part in raw.split()[:2])
                if quota > 0 and period > 0:
                    return max(1, int(quota / period))
            except (ValueError, IndexError):
                pass
        return os.cpu_count()

    @staticmethod
    def _heap_mb(text):
        """`-Xmx` text ('4g', '3072m') as MB, or None if it is not a size."""
        text = str(text).strip().lower()
        units = {'k': 1 / 1024, 'm': 1, 'g': 1024, 't': 1024 * 1024}
        scale = units.get(text[-1:], None)
        number = text[:-1] if scale else text
        try:
            return int(float(number) * (scale or 1 / (1024 * 1024)))
        except ValueError:
            return None

    def _auto_heap(self):
        """A heap ceiling sized to this machine, as `-Xmx` text, or None."""
        budget = self._memory_budget_mb()
        if not budget:
            return None
        megabytes = int(budget * self.HEAP_FRACTION)
        megabytes = max(self.HEAP_FLOOR_MB, min(self.HEAP_CAP_MB, megabytes))
        megabytes -= megabytes % 256          # a round number reads better in a log
        return f'{megabytes}m'

    def _auto_gc(self, heap_mb):
        """The collector that fits this machine.

        ZGC - what the game ships - pays for its very short pauses with
        concurrent work and extra reserved memory, and needs a big heap and
        spare cores to be worth it. G1 is the better trade in the middle, and
        on one or two cores Serial stops the collector competing with the game
        for the only CPUs there are.
        """
        cpus = self._cpu_budget() or 2
        if cpus <= 2:
            return 'Serial'
        if cpus >= 8 and (heap_mb or 0) >= 8192:
            return 'Z'
        return 'G1'

    # Settings whose value means "change nothing".
    KEEP_VALUES = {'keep', 'off', 'none', 'installed'}

    def _resolve_launch_params(self):
        """Decide the heap and collector to launch with: ``(heap, gc_name)``.

        Either may be None, meaning "leave whatever the game installed with".
        """
        heap_setting = (config.GAME_SERVER_MAX_HEAP or 'auto').strip()
        gc_setting = (config.GAME_SERVER_GC or 'auto').strip()

        heap = None
        if heap_setting.lower() in self.KEEP_VALUES:
            pass
        elif heap_setting.lower() == 'auto':
            heap = self._auto_heap()
            if heap is None:
                self.log("Could not read this machine's memory, so the JVM heap "
                         "is left as installed. Set GAME_SERVER_MAX_HEAP if the "
                         "server is killed while starting.")
        elif self._heap_mb(heap_setting) is None:
            self.log(f"GAME_SERVER_MAX_HEAP='{heap_setting}' is not a size like "
                     f"'4g' or '3072m'; leaving the heap as installed")
        else:
            heap = heap_setting

        collector = None
        if gc_setting.lower() in self.KEEP_VALUES:
            pass
        elif gc_setting.lower() == 'auto':
            collector = self._auto_gc(self._heap_mb(heap) if heap else None)
        elif gc_setting in self.GC_CHOICES:
            collector = gc_setting
        else:
            self.log(f"GAME_SERVER_GC='{gc_setting}' is not one of "
                     f"{', '.join(sorted(self.GC_CHOICES))}; leaving the "
                     f"collector as installed")

        return heap, collector

    def _apply_launch_params(self):
        """Point the JVM at what this machine can actually back, before launch.

        Two settings, both living in a JSON file inside the game install rather
        than on the command line, which is why they are edited here instead of
        being passed as arguments:

        *Heap.* Project Zomboid installs with `-Xmx8g`. A machine with less than
        that plus room for the rest of the container does not get a polite
        error - the kernel kills the JVM partway through loading tile
        definitions, the shell prints "Killed", and the log simply stops.

        *Collector.* ZGC assumes a big heap and cores to spare. Neither is free
        on a small machine.

        Both default to `auto`, which measures the machine rather than trusting
        a number somebody wrote for a different one - so the same image is
        correct on a 2011 desktop and on a modern server. An explicit value
        wins, and `keep` opts out entirely. Rewritten before every launch, so a
        SteamCMD update that restores the file cannot quietly undo it.
        """
        heap, collector = self._resolve_launch_params()
        if not heap and not collector:
            return

        gc_flag = self.GC_CHOICES.get(collector) if collector else None

        params = self._launch_params()
        if params is None:
            return
        args = params.get('vmArgs')
        if not isinstance(args, list):
            self.log(f"{config.LAUNCH_PARAMS_FILE} has no vmArgs list; leaving "
                     f"the JVM options as installed")
            return

        updated = list(args)
        if heap:
            flag = f'{self.HEAP_FLAG}{heap}'
            updated = [flag if str(a).startswith(self.HEAP_FLAG) else a for a in updated]
            if flag not in updated:
                updated.append(flag)
        if gc_flag:
            # Drop every collector flag first: they are mutually exclusive, and
            # ZGC also carries -XX:+ZGenerational, which is meaningless without it.
            updated = [a for a in updated if not self._is_gc_arg(a)]
            updated.append(gc_flag)

        if updated == args:
            return                      # already what we want

        params['vmArgs'] = updated
        try:
            with open(config.LAUNCH_PARAMS_FILE, 'w', encoding='utf-8') as handle:
                json.dump(params, handle, indent=2)
        except OSError as e:
            self.log(f"Could not set the JVM options in "
                     f"{config.LAUNCH_PARAMS_FILE}: {e}")
            return

        changed = []
        if heap:
            was = self._configured_heap({'vmArgs': args}) or 'unset'
            changed.append(f"heap {was} -> {heap}")
        if gc_flag:
            previous = [str(a) for a in args if self._is_gc_arg(a)]
            changed.append(f"collector {' '.join(previous) or 'default'} -> {gc_flag}")
        # The measurements too, so a surprising choice can be checked against
        # what the container was actually told it had.
        budget = self._memory_budget_mb()
        self.log(f"JVM launch parameters ({budget or '?'}MB usable, "
                 f"{self._cpu_budget() or '?'} cpus): {'; '.join(changed)}")

    def _report_exit(self):
        """Say why the last launch ended, once per dead process.

        A server that dies during boot leaves a log that just stops, and the
        reconciler's next line is a restart - so without this the interesting
        fact (killed? bad exit code?) never appears anywhere.
        """
        process = self.server_process
        if process is None or process is self._exit_reported_for:
            return
        code = process.poll()
        if code is None:
            return
        self._exit_reported_for = process

        if code == -9:
            heap = self._configured_heap()
            self.log(
                "The game server was killed with SIGKILL. A process does not "
                "choose that, and this manager only sends it to a server that "
                "ignored a stop request - so during a boot it is almost always "
                "the kernel's out-of-memory killer. The JVM is configured for a "
                f"{heap or 'default'} heap: give the container more memory, or "
                "lower it with GAME_SERVER_MAX_HEAP."
            )
        elif code < 0:
            self.log(f"The game server was terminated by signal {-code}.")
        elif code != 0:
            self.log(f"The game server exited with status {code}. The tail of "
                     f"{self.server_log_path} should say why.")

    # A restart appends to the same /tmp log rather than truncating, so the
    # previous crash's tail survives for _report_exit to point at. Left unchecked
    # it grows without bound across a long-lived manager, so roll it to a single
    # `.1` companion once it crosses this size - keeping the last two generations
    # and no more.
    SERVER_LOG_MAX_BYTES = 50 * 1024 * 1024

    def _roll_server_log(self):
        """Rotate the game-server log if it has grown past the cap.

        Best effort: a rotation that fails just leaves the log to grow, which is
        never worth failing a launch over. Safe while the roster worker holds the
        old file open - the rename leaves that reader on the old inode and the
        launch opens a fresh one.
        """
        try:
            if os.path.getsize(self.server_log_path) < self.SERVER_LOG_MAX_BYTES:
                return
        except OSError:
            return
        try:
            os.replace(self.server_log_path, self.server_log_path + ".1")
            self.log(f"Rolled {self.server_log_path} (over "
                     f"{self.SERVER_LOG_MAX_BYTES // (1024 * 1024)}MB) to .1")
        except OSError as e:
            self.log(f"Could not roll the server log {self.server_log_path}: {e}")

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
                    # A crashed server leaves its log handle open (only the
                    # graceful stop path closes it), so drop it before reopening.
                    if self.server_log_handle:
                        try:
                            self.server_log_handle.close()
                        except Exception as e:
                            self.log(f"Closing stale log handle failed: {e}")
                        self.server_log_handle = None

                    self._ensure_data_dirs()
                    self._apply_launch_params()
                    self._roll_server_log()
                    self.server_log_handle = open(self.server_log_path, "a")
                    cmd = [self.server_script, "-servername", self.server_name]
                    self.server_process = subprocess.Popen(
                        cmd, stdin=subprocess.PIPE, stdout=self.server_log_handle,
                        stderr=subprocess.STDOUT, text=True, bufsize=1
                    )
                    # Start polling the online-player roster for this server. The
                    # new generation retires any worker left over from a previous
                    # launch of this process.
                    self._roster_stop_event.clear()
                    self._roster_generation += 1
                    generation = self._roster_generation
                    # This launch has its own world to load, so the idle timeout
                    # re-arms from scratch rather than inheriting the last run's.
                    self._roster_ready = False
                    self._idle_since = None
                    # A fresh launch may be a fresh game version; re-capture it.
                    self._version_captured = False
                    self.roster_thread = threading.Thread(
                        target=self._roster_worker, args=(generation,), daemon=True
                    )
                    self.roster_thread.start()
                except Exception as e:
                    self.log(f"Spawn Error: {e}")
                    self.state = "stopped"
            
            elif not start and is_running:
                self.log("Shutting down game server...")
                # Stop roster polling before the process goes away.
                self._roster_stop_event.set()
                try:
                    if self.server_process.stdin:
                        self.server_process.stdin.write("save\nquit\n")
                        self.server_process.stdin.flush()
                    self.server_process.wait(timeout=self.game_server_quit_timeout)
                except Exception as e:
                    # Graceful quit did not land in time; say why before killing.
                    self.log(f"Graceful shutdown failed ({e}); killing the process")
                    self.server_process.kill()
                finally:
                    if self.server_log_handle:
                        self.server_log_handle.close()
                        self.server_log_handle = None
                    cache.set_value(f"server:{self.server_id}:online_players", json.dumps([]), ttl=self.roster_interval * 3)

    def run(self):
        """Reconciliation loop: compares desired state with polled truth."""
        threading.Thread(target=self.commands_listener, daemon=True).start()

        while not self._stop_event.is_set():
            current_goal = self.state
            game_alive = self._is_game_server_running()
            wake_alive = self._is_onwake_running()

            # Publish the observed runtime state so the web UI reflects reality.
            self._publish_live_state()

            # While the server is up its boot log carries the game version;
            # capture it once per launch so it can be advertised while sleeping.
            if game_alive:
                self._maybe_capture_version()

            if current_goal == "initializing":
                self._reconcile_initializing(game_alive)

            elif current_goal == "sleeping":
                if game_alive:
                    self.manage_server_process(start=False)
                elif not wake_alive and time.monotonic() >= self._wake_retry_after:
                    # The retry gate is only ever set by a total bind failure,
                    # so the normal path is unaffected.
                    self.manage_onwake(start=True)

            elif current_goal == "running":
                # manage_server_process handles stop_onwake internally for safety
                if not game_alive:
                    # Why it died, before the restart line buries it.
                    self._report_exit()
                    if self._may_restart():
                        self._last_start_at = time.monotonic()
                        self.manage_server_process(start=True)
                else:
                    self._note_healthy_run()
                    self._check_idle_sleep()

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
                        self._send_console(data.get('data', ''), ack_id=data.get('ack_id'))
            except Exception as e:
                self.log(f"Command listener error: {e}")
                time.sleep(5)

    def terminate(self):
        """Full system shutdown."""
        self._stop_event.set()
        self._roster_stop_event.set()
        self.state = "stopped"
        self.manage_onwake(start=False)
        self.manage_server_process(start=False)
        cache.set_value(f"server:{self.server_id}:online_players", json.dumps([]), ttl=self.roster_interval * 3)


class Orchestrator:
    channel_listener_error_timeout = 5
    managers_shutdown_timeout = 60
    # How often the manager list is reconciled without being asked to. Catches a
    # dead manager thread, and a DB edit whose notification was lost.
    manager_sweep_interval = 60

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
                        'state': s.default_state,
                        'idle_sleep_seconds': s.idle_sleep_seconds or 0
                    }
                    for s in db_servers
                ]
        except Exception as e:
            self.log(f"DB Sync Error: {e}")
            return

        by_name = {s['name']: s for s in servers_data}

        # Terminate managers whose server was removed, or whose ports changed:
        # the wake-on-demand listener binds those ports at startup, so a port
        # change can only be applied by rebuilding the manager. `default_state`
        # is deliberately NOT re-applied - it is the boot default, and live
        # start/stop control is meant to be transient.
        active_list = []
        for m_entry in self.managers:
            server_data = by_name.get(m_entry['name'])
            if server_data is None:
                self.log(f"Removing manager: {m_entry['name']}")
                m_entry['object'].terminate()
            elif not m_entry['thread'].is_alive():
                # A reconcile loop that died took its server's supervision with
                # it, silently: the live-state key expires and the panel falls
                # back to showing the configured default, so the server looks
                # managed when nothing is managing it. Rebuild it. `terminate`
                # still runs, because the game process may well have outlived
                # the thread that was watching it.
                self.log(f"Manager thread for {m_entry['name']} is not alive; rebuilding")
                m_entry['object'].terminate()
            elif server_data['ports'] != m_entry['ports']:
                self.log(f"Ports changed for {m_entry['name']} "
                         f"({m_entry['ports']} -> {server_data['ports']}); rebuilding manager")
                m_entry['object'].terminate()
            else:
                # Config a live manager can take without being rebuilt. The
                # idle timeout is only a number the reconcile loop reads, so
                # changing it must not cost the players on the server their
                # session the way a rebuild would.
                m_entry['object'].set_idle_sleep_seconds(server_data['idle_sleep_seconds'])
                active_list.append(m_entry)

        # Start managers that are missing (new servers, and rebuilds above)
        current_names = {m['name'] for m in active_list}
        for server_data in servers_data:
            if server_data['name'] not in current_names:
                self.log(f"Creating manager: {server_data['name']} (Init: {server_data['state']})")
                game_manager_object = GameManager(
                    server_data['id'],
                    server_data['name'],
                    server_data['ports'],
                    initial_state=server_data['state'],
                    idle_sleep_seconds=server_data['idle_sleep_seconds']
                )
                thread = threading.Thread(target=game_manager_object.run, name=f"GameManager-{server_data['name']}", daemon=False)
                thread.start()
                active_list.append({
                    'name': server_data['name'],
                    'object': game_manager_object,
                    'ports': server_data['ports'],
                    'thread': thread
                })

        self.managers = active_list

    def start(self):
        self.log("Starting Orchestrator lifecycle...")
        self.update_managers()

        while True:
            try:
                pubsub = cache.subscribe_to_channel(self.commands_channel)
                if not pubsub:
                    time.sleep(self.channel_listener_error_timeout)
                    continue

                # Polled rather than blocking on listen(), so the sweep below
                # still runs while the channel is quiet. Without it, a manager
                # thread that died would stay dead until somebody happened to
                # edit a server - the only thing that used to reach this code.
                last_sweep = time.monotonic()
                while True:
                    msg = pubsub.get_message(timeout=1.0)

                    if msg and msg.get('type') == 'message':
                        try:
                            data = (json.loads(msg['data'])
                                    if isinstance(msg['data'], str) else msg['data'])
                        except Exception as e:
                            self.log(f"Ignoring malformed manager message: {e}")
                            continue
                        # Per-server commands belong to the managers, not here.
                        if 'server' in data:
                            continue
                        if data.get('command') == 'update-managers':
                            self.log("Managers update triggered")
                            self.update_managers()
                            last_sweep = time.monotonic()
                    elif time.monotonic() - last_sweep >= self.manager_sweep_interval:
                        self.update_managers()
                        last_sweep = time.monotonic()
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
