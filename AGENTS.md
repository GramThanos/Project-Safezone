# AGENTS.md

Orientation for anyone working in this repository, covering what you need to find your way around.

## What it is

**Project Safezone** is a web manager for Project Zomboid dedicated servers. Players sign up, link their in-game characters to their account, and earn loot that is delivered into the running game. Staff monitor and control servers, run whitelisted console actions, and review an audit trail.

The stack is **6 containers** (`docker-compose.yml`):

| Service       | Tech                                 | Published         |
|---------------|--------------------------------------|-------------------|
| `game-server` | Python + SteamCMD + supervisord      | `16261-16262/udp` |
| `backend`     | Flask + Gunicorn                     | internal only     |
| `scheduler`   | backend image, `python -m scheduler` | internal only     |
| `frontend`    | React + Nginx                        | `8080` -> `80`    |
| `db`          | MariaDB 11                           | internal only     |
| `cache`       | Redis 7                              | internal only     |

Only the frontend and the game's UDP ports are reachable from the host. The backend API and the manager API sit on the `internal` network - reach them through the frontend's Nginx (`/api` and `/health` are proxied) or by exec-ing into a container.

**The split that matters:** the *backend* owns accounts, characters, claims, loot and site content. The *game-server manager* owns servers, tasks and the console boundary. The backend has no `Server` or `Task` model; it proxies to the manager's HTTP API with a shared `API_TOKEN`. Never invert that dependency - the manager does not call the backend.

## Backend (`backend/`) - Flask REST API

- `app.py` - blueprint registration, CORS, Redis-backed rate limiting, security headers, and `/` and `/health`. Version from `Config.APP_VERSION` (`2.0.0`).
- `init_db.py` - runs Alembic migrations, seeds box types and the default admin. Idempotent; `entrypoint.sh` runs it on every boot. Exit code `75` means "the database is not up yet" and is the only one the entrypoint retries.
- `alembic/versions/` - **the schema lives here.** A new model means a new migration; there is no `create_all` bootstrap on this side.
- `scheduler.py` - separate worker process for recurring jobs. It claims work with `SELECT ... FOR UPDATE`, so running more than one is safe. It also pumps the alert event queue on every tick - deliberately not a job, since job intervals are floored at a minute and new job kinds register switched off, neither of which suits an event pump.
- `src/config.py` (`configure_app()`), `src/database.py`, `src/extensions.py` (the limiter instance, so blueprints can declare per-endpoint limits).
- `src/middleware/auth.py` - JWT plus `token_required` / `moderator_required` / `admin_required`. Role, ban state and `token_version` are re-read from the database on every request, so a ban, a demotion or `logout-all` takes effect immediately. An account with `must_change_password` can reach almost nothing until it does.
- `src/models/` - `user`, `auth_token`, `ban`, `character`, `claim_request`, `reward`, `box_type`, `box_loot_pool`, `user_box`, `inventory_item`, `invitation`, `notification`, `report`, `audit_log`, `app_setting`, `scheduled_job`, `alert_channel`.
- `src/routes/` - blueprints: `auth`, `characters`, `claims`, `servers`, `site`, `boxes`, `inventory`, `invitations`, `notifications`, `reports`, `rewards` (mounted at `/api/admin/rewards`) and `admin` (`/api/admin` - the large one: users, servers, installation, mods, claims, box pools/types, actions, give, tasks, audit, settings, jobs, reports, alert channels).
- `src/utils/` - `settings` (runtime-editable config), `jobs` (scheduler job registry), `game_server` (proxy helper), `redis_utils` (live state and online roster), `actions` (console-action catalog access), `loot`, `box_types`, `daily`, `expiry`, `notify` (in-app messages to *one player*), `moderation`, `audit`, `alerting` (the staff event catalog, routing, cooldown and the game-event queue), `channels` (how each kind of destination is written), `mailer` (composes mail; the game-server sends it), `captcha`, `paging`, `logging_setup`.

**Roles:** `banned` < `player` < `moderator` < `admin`.

**Characters are claimed, never created.** `POST /api/claims` **auto-approves** when the given in-game name is currently online on the server - being online is the proof of ownership. Staff can revoke afterwards (`POST /api/admin/claims/<id>/revoke`), and `DELETE /api/characters/<id>` is an *unlink*: it releases the in-game identity for anyone to claim again.

**Loot flow:** daily box (`POST /api/boxes/daily`, one per account per day; the day boundary follows the primary server's timezone) -> open it to draw rewards into inventory -> `POST /api/inventory/<id>/send` to an online linked character, which queues a `give_reward` task on the manager. A reward is either an **item** (`additem`) or a **`droppable` action** from the catalog, so loot can never issue a moderation command. Delivery is *acknowledged*, not assumed: the task waits for `cmd_ack:<id>` in Redis, and un-acked items go back to the player.

**Settings are two-layered.** Every key in `src/utils/settings.py::REGISTRY` has an environment variable as its default and an optional `app_settings` row as a live override, editable in the admin panel. Only registered keys are readable or writable. Registration control (open / closed / shared password / invitations) works this way - independent switches, not a mode.

### Table ownership

Split so two services never create the same table differently. Each service's initialization only creates what it owns.

| Owner       | Tables |
|-------------|--------|
| backend     | `users`, `auth_tokens`, `bans`, `characters`, `claim_requests`, `rewards`, `box_types`, `box_loot_pools`, `user_boxes`, `inventory_items`, `invitations`, `notifications`, `reports`, `audit_logs`, `app_settings`, `scheduled_jobs`, `alert_channels` |
| game-server | `servers`, `tasks`, `server_player_counts`, `workshop_collections` |

## Game Server Manager (`game-server/`)

Based on `cm2network/steamcmd`. Three processes under `supervisord`, all in `src/` (copied to `/app`):

1. `manager_api.py` - Flask API on port `5000`, internal only. Bearer `MANAGER_API_TOKEN` (auth is skipped when no token is configured). This is what `GAME_SERVER_API_URL` points at.
2. `manager_tasks.py` - task worker (`pending` -> `processing` -> `completed`). Reacts to pub/sub and also sweeps every `TASK_SWEEP_INTERVAL`, so a lost notification delays a task rather than stranding it.
3. `manager_game.py` - runs and monitors the game process, and publishes live state and the online roster to Redis (`server:<id>:state`, `server:<id>:online_players`), which the backend reads for the UI, claims and reward delivery.

Modules: `config`, `database`, `models` (`Task`, `Server`, `ServerPlayerCount`), `cache`, `servers`, `tasks`, `commands` (**the command-injection boundary**), `actions` (whitelisted PZ admin commands with typed parameters and `droppable` / `min_role` flags, exposed as `GET /api/actions` so the backend never re-implements the rules), `rcon`, `roster` (pure parser for `players` output), `items` (the in-game item catalog behind the reward picker - PZwiki's autogenerated item list parsed from raw wikitext, cached in Redis under one never-expiring key and refreshed on age so a wiki outage degrades to a stale list rather than an empty one; base-game items only), `server_config` (PZ INI), `mods` (on-disk library, `mod.info` parsing, `require=` checking; deliberately offline and dependency-free so it stays testable), `workshop` (Workshop item titles/descriptions from Steam's keyless `GetPublishedFileDetails`, Redis-cached, stdlib `urllib` so it adds no dependency, and degrades to no-metadata rather than failing), `backups`, `logs`, `steam`, `webhook` (the Discord relay - a hole in the egress boundary, so its allowlist is tested), `mailer` (the SMTP relay, for the same reason: the backend cannot reach a mail server either), `events` (the queue of player/server events the backend's scheduler drains).

Task actions: `update_server` (optional per-task `beta` to switch branch), `get_app_info`, `give_reward`, `run_action` (same handler, staff-initiated), `backup_world`, `restore_world`, `update_mods` (reconciles what a server's INI already lists), `download_workshop` (installs explicit ids, which is how a *new* mod arrives). `reap_stuck()` fails tasks abandoned in `processing` by a restart.

Steam: PZ dedicated server `STEAM_APP_ID = 380870`, branch via `STEAM_APP_BETA`, installed to `STEAM_INSTALL_DIR` (`/opt/steam-apps`). Heap and GC are sized at launch from the container's limits (`GAME_SERVER_MAX_HEAP=auto`, `GAME_SERVER_GC=auto`).

**Installing is admin-only; switching mods on and off is not.** A moderator may edit which of the *downloaded* mods a server loads (`PUT /api/admin/servers/:id/mods`, which sets `downloaded_only` for any non-admin so the manager refuses newly-added ids or names that are not on disk) - that is the 3am repair. Installing game files, downloading Workshop items, deleting them, and `POST /api/admin/tasks` (free-form action, so it could reinstall the game) are all `@admin_required`.

**Collections are remembered for their order.** `workshop_collections` stores each collection installed from, with its items in the author's `sortorder` - frequently the intended load order for Project Zomboid. A table rather than a cache entry because losing it to an eviction silently downgrades "enable all of this, in order" back into dozens of manual clicks. Written by `download_workshop` only after the items are really on disk. `mod.info`'s `require=` is parsed into `requires`, and `mods.check_requirements()` reports a dependency that is missing from a load order or that loads after the mod needing it.

**Three sources of mod naming, deliberately kept apart.** `mod.info` on disk gives the *mod* id, name and description (offline, only after download). `workshop.lookup()` gives the *Workshop item* title and summary for any id, before download, and is what tells a typo from a real item - SteamCMD reports success for an id that does not exist, so this is the only cheap way to catch one. Browsing or searching the Workshop would need `IPublishedFileService/QueryFiles` and a Steam Web API key; not implemented. `workshop.collections()` is the keyless substitute - `GetCollectionDetails` expands a collection id into its items in the author's `sortorder`, and doubles as the way to tell a collection id from an item id, since their URLs are identical.

**Staff alerts are one registry and three kinds of channel.** `src/utils/alerting.py` holds the event catalog, the cooldown and the dispatcher; `alert_channels` rows are the destinations - a Discord webhook, the staff inbox, an ops mailbox - each subscribing to the events it wants, and `src/utils/channels.py` decides how each kind is written. A message carries `detail` for the internal channels only, which is how the text of a report reaches the moderators without reaching a Discord channel that has a wider membership.

**Only staff-facing events are routable.** A message to a *player* about their own account goes through `notify.py` to the person concerned, and account mail (verification, reset) is part of how those flows work. Neither is in the registry, because neither is something an operator should be able to switch off.

**The sending is split across the two services on purpose.** The backend decides who hears what; the manager owns the sockets - `POST /api/webhook` for Discord, `POST /api/mail` for SMTP - because `internal: true` leaves the backend with no egress and no DNS. Backend-side events are emitted at their call site on a background thread. Events only the manager can see (a player joining, a server giving up) are pushed onto a Redis list by `events.py` and drained by the scheduler, because the manager still does not call the backend.

**Outbound network access lives here, not in the backend.** `backend` and `scheduler` sit only on the compose `internal` network, which is declared `internal: true` - no egress and no DNS, so anything reaching a third party (`workshop`, `items`, SteamCMD) has to run in this container and be proxied. That is deliberate: giving the backend egress would hand outbound access to the service holding authentication and untrusted user input. If you add an integration that needs the internet, put it here.

**One install serves every server.** There is a single `STEAM_INSTALL_DIR`, and Workshop content lands inside it under `steamapps/workshop/content/108600/`, shared by all servers. So the install and the mod library are *host* state (`GET /api/installation`, `GET /api/mods`, `DELETE /api/mods/:item_id` - no server id), and only the selection is per-server (`GET`/`PUT /api/servers/:id/mods`, writing that server's `WorkshopItems` and `Mods`). `steam.installed_app_state()` reads Steam's own `appmanifest_380870.acf` for the installed build id; `get_app_info` asks Steam for the available one. Comparing the two is the only reliable staleness check.

## Frontend (`frontend/`) - React SPA

React 18 + React Router 6 (Create React App), Nginx in production, dark Bootstrap 5 theme.

- `src/pages/` - `Home`, `SignIn`, `ForgotPassword`, `ResetPassword`, `VerifyEmail`, `Servers`, `Characters`, `Rewards`, `Profile`, `Notifications`, `Reports`, `LegalPage`.
- `src/pages/admin/` - nested routes under `/admin` (`AdminLayout` + `Outlet`): servers (plus detail, logs, config, form), installations, tasks, users, claims, rewards, boxes, give, invitations, reports, jobs, alerts, settings, branding, legal, about, audit. `Installations` owns the game files and the mod library; `Tasks` is the queue and its output, and starts nothing.
- `src/context/` - `AuthContext`, `SiteContext` (branding and legal pages from `/api/site`), `ToastContext`, `PlayerContext`.
- **File extensions**: React files are `.jsx` - components, contexts and hooks, whether or not they contain JSX. Plain modules stay `.js`; `src/services/api.js` is the only one.
- `src/services/api.js` - the API client. `REACT_APP_API_URL` is a **build-time** variable and is not set in compose, so production talks same-origin and Nginx proxies to the backend. `npm start` uses the `proxy` field in `package.json`.

## Running

```bash
docker compose up -d
```

Frontend at <http://localhost:8080>. The first login is `admin` / `admin`, and that account can do nothing but change its own password until it does - the warning is enforced, not just documented.

Locally without Docker:

```bash
cd backend && pip install -r requirements.txt && python -m init_db && python app.py
```

```bash
cd frontend && npm install && npm start
```

## Conventions

- **Game-server modules use flat imports** (`import config`, `import database`) because `src/` is copied to the working directory `/app`. Keep it flat.
- **Backend uses the `src/` package**: new endpoints are blueprints registered in `app.py`, and new tables need an Alembic migration.
- **Console commands go through `commands.py` / `actions.py`.** Nothing else builds a command string.
- **Audit sensitive actions** via `src/utils/audit.py` (`GET /api/admin/audit`).
- **Two independent requirements files** - `backend/` and `game-server/` pin different versions on purpose.
- **Secrets**: `docker-compose.yml` ships dev defaults (`SECRET_KEY`, DB password, `API_TOKEN` / `MANAGER_API_TOKEN`). Override them via `.env` in production and never commit real ones. `.env.example` is the full list.
- **Tests** are stdlib `unittest`, no extra dependencies, covering the pure security-sensitive logic (command building, action catalog, roster parsing, crash-loop and ack handling, mod-library path containment, loot draws, the daily boundary, the Discord relay's URL allowlist, the mail relay's address checks, and alert routing - who hears an event and which parts of a message stay internal). Route and authorization tests do not exist yet; nothing in them needs a running stack any more, since the models and blueprints import cleanly against SQLite.

```bash
cd game-server && python -m unittest discover -s tests
```

```bash
cd backend && python -m unittest discover -s tests
```
