# Configuration

Configuration lives in three places:

1. **`.env`** — secrets, timezone and mail, read when the stack starts
2. **The admin panel** — everything you may want to change while running, applied immediately
3. **`docker-compose.yml`** — advanced options for the containers themselves

## `.env`

Create it from the template beside `docker-compose.yml`:

```bash
cp .env.example .env
```

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | dev value | Signs session tokens. Anyone who knows it can mint an admin session |
| `DATABASE_PASSWORD` / `DATABASE_ROOT_PASSWORD` | dev values | MariaDB credentials. Set them **before the first start** — MariaDB only reads them when it creates the database |
| `API_TOKEN` | dev value | Shared secret between the backend and the game-server manager |
| `DATABASE_NAME` / `DATABASE_USER` | `safezone` / `safezone` | Also only read on the database's first start |
| `TZ` | `UTC` in `.env.example` | Container clocks, logs, and the times on the Tasks page and player chart. Left unset, it stays `Europe/Athens`, the default of earlier versions, so an upgrade changes nothing. The daily loot reset follows the primary game server's timezone instead |
| `TOKEN_EXPIRY_HOURS` | `24` | Session length. Also editable in the panel |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_TLS` / `SMTP_FROM` | — / `587` / — / — / `true` / — | Outgoing mail. A blank host writes mail to the backend log instead of sending it. Also editable in the panel |

The development defaults for the secrets are published in this repository — replace every one. `openssl rand -hex 32` prints a suitable value. Apply changes with `docker compose up -d`.

## The admin panel

Most settings are changed live, by an admin, with no restart:

| Where | What |
|---|---|
| **Admin → System → Settings** | Registration (open, closed, shared password), invitations, captcha, the site's public URL, session length, the weekly streak, loot expiry, alerts, retention, and mail |
| **Admin → Site → Branding** | The site's name, home page text and footer links |
| **Admin → Site → Pages** | Server rules, terms, privacy and cookie pages |
| **Admin → System → Alerts** | Discord webhooks, the staff feed and ops mailboxes, and which events each one receives |
| **Admin → System → Scheduled Jobs** | The weekly bonus, retention sweeps and server maintenance |
| **Admin → Servers** | Each server's ports, timezone, settings, mods and sleep behaviour |

## `docker-compose.yml`

A few options are set on the containers themselves. The game's memory and garbage collector are already in the compose file, under the `game-server` service:

| Variable | Default | Notes |
|---|---|---|
| `GAME_SERVER_MAX_HEAP` | `auto` | `auto` gives the game half of the available memory, clamped 1–8 GB. Or a size like `4g`, or `keep` to leave the game's own value |
| `GAME_SERVER_GC` | `auto` | `auto` picks by CPU count and heap size. Or `Z`, `G1`, `Parallel`, `Serial`, `keep` |

Others can be added to a service's `environment` list when you need them. The useful ones:

| Variable | Service | Default | Notes |
|---|---|---|---|
| `HTTPS_ENABLED` | `backend` | `false` | Sends strict-transport headers. Set `true` behind a TLS proxy |
| `BACKUP_KEEP` | `game-server` | `10` | World archives kept per server |
| `STEAM_APP_BETA` | `game-server` | public | Default Steam branch of the game. Can also be picked per update in **Installations** |
| `SERVER_SCRIPT` | `game-server` | `/opt/steam-apps/start-server.sh` | Override if a server will not start |
| `WAKE_A2S_THRESHOLD` | `game-server` | `2` | Server-list queries from one address, within a minute, that wake a sleeping server. `1` wakes on first contact. See [wake on demand](features.md#wake-on-demand) |
| `WORKSHOP_METADATA` | `game-server` | `true` | Look up Workshop mod titles on Steam. Set `false` on a host with no outbound HTTP |
| `LOG_FORMAT` | `backend`, `scheduler` | `text` | `json` when something is collecting logs |

The complete list, with comments, is in `backend/src/config.py` and `game-server/src/config.py`.

### Changing the published ports

The website is published on `8080` and the game on UDP `16261-16262`. To bind the website to localhost only, when a reverse proxy runs on the same machine, change the frontend's port line to:

```yaml
    ports:
      - "127.0.0.1:8080:80"
```
