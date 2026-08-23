# Project Safezone

A self-hosted web manager for Project Zomboid dedicated servers — accounts, character links, an in-game loot economy, and a staff panel for running the servers themselves.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)
![Deploy: Docker Compose](https://img.shields.io/badge/deploy-docker%20compose-blue.svg)

## Screenshots

> **Screenshots pending.** Capture the four views below at roughly 1600px wide, save them into `docs/images/` under these names, then delete this note and uncomment the gallery beneath it.
>
> - `home.png` — the public home page a visitor lands on, showing live server status
> - `rewards.png` — a player opening a loot box, or the inventory with rewards ready to send
> - `admin-servers.png` — Admin → Servers with at least one server running
> - `admin-give.png` — Admin → Give, showing the whitelisted console action picker

<!--
| | |
|:--:|:--:|
| ![The public home page](docs/images/home.png) | ![Opening a loot box](docs/images/rewards.png) |
| *What a visitor sees: live server status and player counts.* | *A daily box being opened; rewards land in the player's inventory.* |
| ![Admin server management](docs/images/admin-servers.png) | ![Whitelisted console actions](docs/images/admin-give.png) |
| *Staff control: start, stop, sleep, back up and configure each server.* | *Every runnable command is declared in a typed catalog.* |
-->

## Overview

Project Safezone puts a website in front of a Project Zomboid community's game servers. Players sign up, link their in-game characters to their account, and earn loot that is delivered into the running game. Staff monitor and control the servers, run whitelisted console commands, moderate accounts, and review an audit trail of everything sensitive.

It runs as six containers on one host: a React frontend, a Flask API, a recurring-job scheduler, a SteamCMD-based game server manager, MariaDB and Redis. Everything comes up with a single `docker compose up`.

It suits a range of setups. A small team running a private server for friends can use it to hand out accounts, control the server without an SSH session, and drop a little loot into the world — and the whole stack comes up with one command. It scales up from there to a public or semi-public community that already has moderators, wants players to have accounts, and wants server control and an audit trail in one place. Run only the parts you need: the loot economy, the alert channels and invite-only registration are all optional, so a handful of friends can ignore what a larger community leans on.

## Features

### Accounts and characters
- JWT sign in and sign up, with per-endpoint rate limiting
- Four roles: `banned` < `player` < `moderator` < `admin`, re-read from the database on every request so a ban or demotion takes effect immediately
- **Controllable registration**: open, closed, behind a shared password, or by invitation — independent switches, all editable in the panel without a redeploy
- **Invitation links**, single-use and/or time-limited. Players can issue them too, within a quota, if you allow it
- **Account recovery**: email confirmation, self-service password reset, and an admin-issued reset link for people whose self-service fails
- **Revocable sessions**: changing a password ends every other session, and "sign out everywhere" is one click
- **Your data is yours**: download everything held about an account, or close it permanently
- **Character claims**: an account claims an in-game character by name, and the character must be online at the time — that *is* the proof of control, so the link is made immediately rather than queued for review. Characters exist *only* through a claim; there is no create endpoint. Deleting a character is an *unlink* that releases the in-game name. Staff can revoke a link, with a reason the player sees

### Loot economy
- **Daily loot box**, one per account per day, weighted small / medium / big. The day boundary follows the primary server's timezone, not UTC
- **Weekly streak bonus**: collect at least five of the week's seven daily boxes and a bonus box is granted automatically
- **Item picker**: rewards and direct gives are chosen from a searchable list of every base-game item — icon, name and id — instead of typed from memory, and picking one fills in the reward's name and icon. The list comes from PZwiki's generated item list, fetched and cached by the game-server manager and refreshed weekly. Modded items are not in it, so those ids are still typed by hand
- **Reward catalog** of items (delivered with `additem`, in stacks if you like) and usables (a whitelisted console action). Only loot-safe actions may back a reward, so a drop can never carry a moderation command
- **Loot pools** per box size with per-reward drop weights, and box sizes whose draw counts and daily odds are retuned in the panel rather than in code
- **Published odds**: players can see what each box contains and how likely each reward is, and review what they have already received
- **Inventory**: opened rewards wait until the player sends them to one of their own linked characters, which must be online
- **Acknowledged delivery**: the manager confirms it actually wrote the command to the running server. No acknowledgement means the item comes back to the player
- **Optional expiry** for unopened boxes and unsent rewards, off by default
- **Notifications**: character links, delivery outcomes, bonuses and moderation all reach the player instead of requiring them to refresh and guess

### Server management
- Live status, player counts and a 24-hour activity chart
- Create, configure and delete servers; start, stop, or put to sleep
- **Wake on demand**: a sleeping server binds its ports and boots for real when a player first connects, so idle servers cost nothing. Server-browser queries and port scans are filtered out — the game's ports are swept constantly, and waking a server for a passing scanner is an outage's worth of noise for nobody
- **Sleep when empty**: set a per-server timeout and a running server with nobody on it goes back to sleep on its own, ready to be woken again. The countdown only starts once the world has finished loading, and resets the moment anyone joins. Off by default
- **World backups**: archive a server's save from the panel, with the running server flushed to disk first, retention pruning, and a restore that keeps the replaced world aside rather than deleting it
- **Server settings editor**: a whitelist of INI options, with credential keys write-only and unknown keys preserved untouched
- **Workshop mods**: a shared mod library managed from **Admin → Installations** — paste an item id or a Workshop URL and it is looked up against Steam first, so you see the mod's title, thumbnail and description and a typo fails in a second instead of after a several-minute download that quietly fetched nothing. Each server then picks what it loads from a checklist of what is actually on disk. Mod names come from each item's `mod.info`, so the id-present-but-name-wrong mismatch that silently breaks a server is a list you choose from rather than a string you have to get right
- **Collections expand**: paste a Workshop *collection* URL and it becomes every mod in it, in the order its author arranged them, previewed as a list before anything downloads. The collection is remembered, so adopting it on a server is one click that reproduces that order rather than dozens that do not
- **Load order is editable, and checked**: mods load top to bottom and one that extends another has to come after it, so the enabled list is reorderable — and each mod's declared `require=` is checked against it, flagging a dependency that is switched off or that loads too late. That is the difference between "reorder until it works" and being told what is wrong
- **RCON**: console commands return what the console printed, falling back to the acknowledged stdin path when RCON is not configured
- **Log viewer**: tail any server's log from the panel, with follow, instead of needing shell access to diagnose a failed start
- **Whitelisted console actions**: every runnable command is declared in a catalog with a typed parameter spec. Nothing else can reach the server console — the free-text path that once existed has been removed
- **Bans reach the game**: banning an account kicks and bans its linked characters on every server, reported per server so a failure is visible
- **Timed bans with reasons**, lifted automatically and restoring the role the account held before, with the full ban history kept for context
- **Operational alerts**: staff are told when a server has been given up on, the game-server is unreachable, or deliveries start failing — with a cooldown so the channel stays worth reading, and routed to whichever destinations you configured
- **Installation management**: what build is installed, on which branch, against what Steam is currently publishing — with install, update and branch switching from the panel rather than a redeploy

### Admin panel
- Grouped routes under `/admin`: servers, installations, tasks, users, character links, invitations, rewards, boxes, give, reports, jobs, alerts, branding, legal pages, audit and settings
- **Runtime settings**: registration posture, invite policy, loot expiry and retention are editable in the panel and take effect immediately, no restart
- **Scheduled jobs**: the streak bonus, retention sweeps and recurring server maintenance, each switchable with its last result on show
- **Alerts**: one list of events, and as many destinations as you like. A destination is a Discord webhook, the staff inbox, or an ops mailbox, and each one ticks what it wants to hear — players joining and leaving, servers starting or giving up, character links, signups, bans, reports, deliveries and operational alerts. Server-scoped events can be filtered to particular servers, so a per-server channel stays about that server. Busy events are labelled as such before you put them in a mailbox. A test button sends a sample and tells you what came back, a webhook URL is stored like a password and never shown again, and a destination that is gone for good is switched off rather than retried forever. The text of a report reaches the staff inbox and ops mail, never Discord
- Role-gated — moderators get servers, tasks, character links, and can switch *downloaded* mods on and off per server; admins additionally get user roles, server CRUD, the reward catalog, and everything that installs or deletes files
- **Audit log** of every sensitive action: role changes, server lifecycle and console commands, claim decisions, reward and loot-pool edits, and deliveries

## Requirements

- **Docker** with Compose v2 (`docker compose`, not `docker-compose`)
- **Memory** — 8 GB is a comfortable starting point for one game server. The manager gives Project Zomboid half of the available memory as its Java heap, clamped between 1 GB and 8 GB, and the other five containers want roughly 1 GB between them. 4 GB will run a small server; below that the game is killed mid-boot by the kernel and the log simply stops
- **Disk** — allow around 10 GB for the game install, plus your world saves and backups. Backups keep 10 archives per server by default (`BACKUP_KEEP`)
- **CPU** — 2 cores works; 4 or more lets the manager pick a better garbage collector for the game
- **Outbound internet** on first boot, for SteamCMD to download the dedicated server (several GB). This is why the first start takes a while
- **Inbound UDP** `16261-16262` reachable from the internet if players outside your network are to connect

## Quick start

1. Clone the repository:
   ```bash
   git clone https://github.com/GramThanos/Project-Safezone.git
   ```

2. Create your environment file:
   ```bash
   cp .env.example .env
   ```
   Edit it before going any further — see [Securing your install](#securing-your-install).

3. Start the stack:
   ```bash
   docker compose up -d
   ```
   The first boot downloads the Project Zomboid dedicated server through SteamCMD. It takes several minutes and looks like nothing is happening; watch it with `docker compose logs -f game-server`.

4. Open <http://localhost:8080> and sign in with the seeded administrator account:
   ```
   Username: admin
   Password: admin
   ```

5. **Change the admin password immediately.** The seeded account is locked to exactly that: it can read itself and set a new password, and nothing else, until you do.

## Securing your install

Work through this before the host is reachable by anyone but you. The values shipped in `docker-compose.yml` are development defaults, and they are published in this repository.

- [ ] **`SECRET_KEY`** — signs every session token. Anyone who knows it can mint an admin session. Generate a long random value
- [ ] **`DATABASE_PASSWORD`** and **`DATABASE_ROOT_PASSWORD`** — change both
- [ ] **`API_TOKEN`** and **`MANAGER_API_TOKEN`** — the shared secret between the backend and the game-server manager. The two must match each other, and both must change
- [ ] **The `admin` account password** — enforced at first sign-in, but confirm it happened
- [ ] **`ALLOWED_ORIGINS`** — set to the origin you actually serve from, not the localhost defaults
- [ ] **Put TLS in front of it.** There is none in the stack. The frontend serves plain HTTP on port 8080; run it behind a reverse proxy that terminates TLS, and set `HTTPS_ENABLED=true` so strict-transport headers are sent
- [ ] **Check what you publish.** Only the frontend (`8080`) and the game's UDP ports are mapped to the host by default. The backend, manager API, database and cache sit on an internal Docker network — keep it that way
- [ ] **Decide your registration posture** before announcing the URL. Open signup is the default; closed, shared-password and invite-only are all available under **Admin → Settings**
- [ ] **Set up SMTP** on the game-server container, or accept that password resets become an operator task — without `SMTP_HOST`, recovery mail is only written to the backend log, and an ops mail alert channel cannot send at all

## First-run setup

1. Wait for the services to settle (`docker compose logs -f`). The schema and the seeded admin account are created automatically by the backend entrypoint
2. Sign in and change the admin password — nothing else is reachable until you do
3. Install the game files under **Admin → Installations**. Nothing can start until SteamCMD has downloaded them, and it takes several minutes
4. Create a game server under **Admin → Servers**. Set its ports, its IANA `timezone`, and mark it **Primary** if its clock should decide when daily loot boxes reset
5. Start it, and watch **Admin → Servers → Logs** for the first boot
6. Build the reward catalog under **Admin → Rewards**, then assign rewards to box sizes under **Admin → Boxes**. *A box whose pool is empty cannot be opened*, so do this before players arrive
7. Review **Admin → Settings** for registration, invitations and retention, and **Admin → Legal** for your rules and privacy pages

## Operating it

### Upgrading

```bash
git pull && docker compose build && docker compose up -d
```

Database migrations run automatically from the backend entrypoint on every boot and are idempotent, so there is no separate migration step. Back up first regardless.

### Volumes and backups

Everything durable lives in named Docker volumes. Nothing of value is stored in the repository directory.

| Volume | Holds | Losing it means |
|---|---|---|
| `db_data` | MariaDB — accounts, characters, claims, loot, audit log | Every account and all loot history is gone |
| `game_data` | Project Zomboid data directory, including world saves | The world is gone |
| `game_files` | The SteamCMD game install and downloaded Workshop mods | A re-download, nothing more |
| `game_backups` | World archives taken from the panel | Your restore points are gone |

World backups are taken from **Admin → Servers → Backups**, which flushes the running server to disk first, prunes to `BACKUP_KEEP` archives, and on restore sets the replaced world aside rather than deleting it. That covers the game world but **not the database** — take that separately:

```bash
docker compose exec -T db mariadb-dump -u root -p"$DATABASE_ROOT_PASSWORD" safezone > safezone-$(date +%F).sql
```

To copy the world archives off the host:

```bash
docker compose cp game-server:/backups ./backups-export
```

### Logs and health

```bash
docker compose logs -f backend scheduler
```

```bash
docker compose logs -f game-server
```

`GET /health` reports the database, cache and game-server manager independently, and answers `degraded` rather than `healthy` when the database is unreachable. Per-server game logs are readable from the panel without shell access.

## Configuration

Set these in `.env` beside `docker-compose.yml`, or edit the compose file directly. Every secret below is interpolated as `${VAR:-dev default}`, so a value in `.env` wins and an absent one falls back to the development default — which is exactly why the defaults must not survive contact with the internet.

Keys marked ° are **seed values only** — an admin can change them live under **Admin → Settings**, and from then on the stored value wins.

### Secrets — change every one of these

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | dev value | Signs session tokens |
| `DATABASE_PASSWORD` / `DATABASE_ROOT_PASSWORD` | dev values | MariaDB credentials |
| `API_TOKEN` / `MANAGER_API_TOKEN` | dev value | Shared backend ↔ manager token; the two must match |

### Core services

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_HOST` / `DATABASE_NAME` / `DATABASE_USER` | `db` / `safezone` / `safezone` | |
| `REDIS_HOST` / `REDIS_PORT` | `cache` / `6379` | |
| `GAME_SERVER_API_URL` | `http://game-server:5000` | Internal address of the manager API |
| `TOKEN_EXPIRY_HOURS` ° | `24` | Sessions can be revoked sooner by changing the password or signing out everywhere |
| `TOKEN_ISSUER` / `TOKEN_AUDIENCE` | `safezone-api` / `safezone-frontend` | JWT claims |
| `ALLOWED_ORIGINS` | localhost origins | CORS allow-list — set to your real origin |
| `HTTPS_ENABLED` | `false` | Sends strict-transport headers; set true behind a TLS proxy |
| `FLASK_DEBUG` | `false` | Never enable on a reachable host |
| `RATELIMIT_DEFAULT` ° | `300 per minute;20000 per day` | Global per-IP. The interface polls live status, so keep it generous. Validated before it is stored, since a limit the limiter cannot parse would break every request |
| `RATELIMIT_SIGNIN` ° / `RATELIMIT_SIGNUP` ° / `RATELIMIT_SIGNUP_CAPTCHA` ° | `5 per minute` / `3 per hour` / `30 per hour` | Per-endpoint. Sign-in is the brute-force gate |
| `RATELIMIT_PASSWORD` ° / `RATELIMIT_PASSWORD_RESET` ° / `RATELIMIT_REPORT` ° | `5 per hour` / `5 per hour` / `10 per hour` | Password changes, reset requests, and reports — the last reaches a human |
| `REACT_APP_API_URL` | — | Build-time only. Left unset, the frontend talks same-origin through Nginx, which is what you want |

### Game server

| Variable | Default | Notes |
|---|---|---|
| `GAME_SERVER_MAX_HEAP` | `auto` | `auto` takes half the available memory, clamped 1–8 GB. Or a size like `4g`, or `keep` to leave the install alone |
| `GAME_SERVER_GC` | `auto` | `auto` picks by CPU count and heap size: Serial on 1–2 cores, ZGC only where it pays off, G1 between. Or name one: `Z`, `G1`, `Parallel`, `Serial`, `keep` |
| `STEAM_APP_BETA` | — | Branch of the dedicated server, e.g. `42.13.1`. The app id is `380870` |
| `STEAM_INSTALL_DIR` | `/opt/steam-apps` | |
| `WORKSHOP_METADATA` | `true` | Fetch Workshop item titles and summaries from Steam's keyless `GetPublishedFileDetails`. Set `false` on a host with no outbound HTTP; the panel then shows bare ids and everything still works |
| `WORKSHOP_CACHE_TTL` / `WORKSHOP_MISS_CACHE_TTL` / `WORKSHOP_API_TIMEOUT` | `86400` / `600` / `10` | How long an item's details are cached, how long a "no such item" is cached, and how long to wait on Steam |
| `SERVER_SCRIPT` | *(derived)* | Path to `start-server.sh`. Override if a server will not launch |
| `ITEM_CATALOG_URL` / `ITEM_CATALOG_ICON_BASE` | PZwiki | Where the item picker's list and its icons come from. Set on the **game-server**, not the backend: it is the only service with outbound network access |
| `ITEM_CATALOG_TTL` / `ITEM_CATALOG_TIMEOUT` | `604800` / `30` | How long the cached catalog is kept before a refresh is attempted, and how long to wait on the wiki. A failed refresh keeps serving the cached copy |
| `LAUNCH_PARAMS_FILE` | *(derived)* | Where the game keeps its JVM arguments |
| `ZOMBOID_DATA_DIR` | `/home/steam/Zomboid` | Saves are expected under `Saves/Multiplayer/<server name>` — check this first if a backup comes back empty |
| `RCON_HOST` | `127.0.0.1` | Loopback; the game runs beside the manager. Port and password are per-server, set in the panel |
| `BACKUP_DIR` / `BACKUP_KEEP` / `BACKUP_QUIESCE_SECONDS` | `/backups` / `10` / `10` | Archive location, retention per server, and seconds to let the server flush before archiving |
| `TASK_SWEEP_INTERVAL` / `TASK_PROCESSING_TIMEOUT` | `60` / `600` | Fallback sweep for pending tasks; when a stuck task is failed |
| `COMMAND_ACK_TIMEOUT` | `5` | Seconds to wait for confirmation that a console command reached the game |

### Email

| Variable | Default | Notes |
|---|---|---|
| `SMTP_HOST` ° / `SMTP_PORT` ° / `SMTP_USER` ° / `SMTP_PASSWORD` ° / `SMTP_TLS` ° / `SMTP_FROM` ° | — / `587` / — / — / `true` / — | Set on the **game-server** container, which is the only one with outbound access — the backend composes mail and hands it over. A blank host logs mail instead of sending it. All six are editable under **Admin → Settings → Mail**, which overrides the container's values the moment a host is entered there; a button on that page mails the admin to prove it works |
| `SITE_URL` ° | `http://localhost:8080` | Where the browser reaches you; used for links inside email and invitations |
| `SMTP_TIMEOUT` | `15` | Seconds to wait on the mail server before giving up |

### Alert delivery

The channels themselves — which Discord webhooks or mailboxes exist, and what each hears — live in the database and are edited under **Admin → Alerts**. These are the knobs for the relay that carries them, all read by the **game-server** container.

| Variable | Default | Notes |
|---|---|---|
| `WEBHOOK_TIMEOUT` | `10` | Seconds to wait on Discord |
| `WEBHOOK_EVENT_QUEUE` | `webhook:events` | Redis list the manager leaves player/server events on. Change it in both services or neither |
| `WEBHOOK_EVENT_QUEUE_MAX` | `500` | Capped so a scheduler that was down returns to the recent past, not an afternoon of stale arrivals |
| `WEBHOOK_EVENT_QUEUE_TTL` | `3600` | The queue is dropped entirely after this with nothing draining it |

### Registration and access

| Variable | Default | Notes |
|---|---|---|
| `REGISTRATION_ENABLED` ° | `true` | Master switch for new accounts |
| `REGISTRATION_PASSWORD` ° | — | Blank means no shared password is required |
| `INVITES_ENABLED` ° | `true` | Allow invite links even when registration is closed |
| `PLAYER_INVITES_ENABLED` ° / `PLAYER_INVITE_QUOTA` ° | `false` / `3` | Let ordinary players invite, within a quota |
| `CAPTCHA_ENABLED` ° | `true` | Self-hosted challenge on sign-up. Stops drive-by bots, not a determined attacker |

### Loot economy

| Variable | Default | Notes |
|---|---|---|
| `STREAK_BONUS_ENABLED` ° / `STREAK_THRESHOLD` ° | `true` / `5` | Bonus box for collecting at least this many of the week's seven daily boxes |
| `BOX_EXPIRY_DAYS` ° / `INVENTORY_EXPIRY_DAYS` ° | `0` / `0` | Expiry for unopened boxes and unsent rewards. `0` means never — expiry is opt-in |
| `DORMANT_LINK_DAYS` ° | `0` | Warn a player when a character link has not been seen for this long. Never unlinks on its own |

### Site content

| Variable | Default | Notes |
|---|---|---|
| `SITE_BRAND_NAME` ° / `SITE_HERO_TITLE` ° / `SITE_HERO_SUBTITLE` ° | `Project Safezone` / — / — | Public page copy |
| `SITE_SOCIAL_DISCORD` ° / `_TWITTER` ° / `_YOUTUBE` ° / `_STEAM` ° | — | Footer links; blank leaves the icon out rather than pointing nowhere |
| `SITE_RULES` ° / `SITE_LEGAL_TERMS` ° / `SITE_LEGAL_PRIVACY` ° / `SITE_LEGAL_COOKIES` ° | — | Markdown documents published at `/rules`, `/terms`, `/privacy` and `/cookies` |

### Operations

| Variable | Default | Notes |
|---|---|---|
| `LOG_FORMAT` / `LOG_LEVEL` | `text` / `INFO` | Use `json` when something is collecting logs |
| `ALERTS_ENABLED` ° / `ALERT_COOLDOWN_MINUTES` ° | `true` / `60` | Staff alerts for downed servers and failing deliveries |
| `AUDIT_RETENTION_DAYS` ° | `0` | Prune audit entries older than this. `0` keeps them forever |
| `SCHEDULER_TICK_SECONDS` | `30` | How often the scheduler looks for due work |

## Roles

| Role | Can |
|---|---|
| `banned` | Nothing — every authenticated request is refused |
| `player` | Manage their own characters, claim identities, collect and send loot, file reports |
| `moderator` | The above, plus the admin panel: servers, tasks, character links, console actions, giving rewards, reports and the audit log |
| `admin` | Everything, plus user roles, server CRUD, the reward catalog, runtime settings and scheduled jobs |

Handing someone `moderator` gives them the game server console, through the whitelisted action catalog. Treat it as the trust decision it is.

## Architecture

| Service | Tech | Published |
|---|---|---|
| `game-server` | Python + SteamCMD + supervisord | `16261-16262/udp` |
| `backend` | Flask + Gunicorn | internal only |
| `scheduler` | Backend image, worker command | internal only |
| `frontend` | React + Nginx | `8080` → `80` |
| `db` | MariaDB 11 | internal only |
| `cache` | Redis 7 | internal only |

Only the frontend and the game's own UDP ports are reachable from the host. Everything else sits on an internal Docker network — reach it through the frontend, or by exec-ing into a container.

Responsibility is split in two, and the dependency runs one way. The **backend** owns accounts, characters, claims, the loot economy and site content. The **game-server manager** owns servers, tasks and the console boundary. The backend never touches a server or task row directly; it calls the manager's token-authenticated internal API, and the manager never calls back. Live server state and the online player roster are published to Redis, which is how the backend knows who is in-game.

Module layout, table ownership and the conventions that keep the two halves apart are in [AGENTS.md](AGENTS.md).

## Known limitations

Worth knowing before putting this in front of a real community.

- **Email confirmation gates nothing.** An unconfirmed address is flagged in the interface but does not restrict the account
- **No TLS in the stack.** Run it behind a reverse proxy that terminates HTTPS; nothing here does it for you
- **An in-game ban does not ban the website account.** The reverse direction works, but a `banuser` typed at the console is invisible to the panel
- **Character profiles are notes, not game data.** Nothing reads skills or hours survived from the game; `Last online` is the only synced fact
- **Some Project Zomboid specifics are assumed, not verified**: the save directory, the Workshop content path, and that the game speaks standard Source RCON. All are configurable — check them first if backups come back empty or RCON falls back to stdin
- **The launch script path depends on how the game was installed.** Override `SERVER_SCRIPT` if a server will not start
- **Read-only console actions** (`players`, `showoptions`) print to the server log, and the panel does not tie their output back to the command you ran — the log viewer means you can go and read it
- **A server that repeatedly fails to start** is marked `failed` and left alone rather than restarted forever, but only the staff alert tells you it happened
- **Route and authorization tests do not exist.** The test suites cover pure logic only

## Development

Run the stack with Docker as above, or the pieces directly:

```bash
cd backend && pip install -r requirements.txt && python -m init_db && python app.py
```

```bash
cd frontend && npm install && npm start
```

The dev server runs on <http://localhost:3000> and proxies API calls to the backend.

Tests are stdlib `unittest` with no extra dependencies, covering the security-sensitive pure logic — console command building, the action catalog, roster parsing, crash-loop and delivery-acknowledgement handling, loot draws and the daily boundary.

```bash
cd game-server && python -m unittest discover -s tests
```

```bash
cd backend && python -m unittest discover -s tests
```

Architecture, module layout and the conventions to follow are in [AGENTS.md](AGENTS.md). The HTTP API between the frontend and the backend is an internal detail that changes with the application's needs; it is not a supported integration surface.

## Contributing and security

Issues and pull requests are welcome.

If you find a security issue, please report it privately rather than opening a public issue.

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).
