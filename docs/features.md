# Features

The full tour. The [README](../README.md) has the highlights; this page has the detail.

- [Accounts and characters](#accounts-and-characters)
- [Loot economy](#loot-economy)
- [Server management](#server-management)
- [Workshop mods](#workshop-mods)
- [Moderation](#moderation)
- [Staff alerts](#staff-alerts)
- [Admin panel](#admin-panel)
- [Community presets](#community-presets)

## Accounts and characters

- **Sign up and sign in**, with a self-hosted captcha on sign-up
- **Two-factor authentication**: players and staff can turn on TOTP two-factor from their profile, using any authenticator app. An admin can switch it off for someone who has lost their device
- **Controllable registration**: open, closed, behind a shared password, or by invitation. These are independent switches, all editable in the panel without a redeploy
- **Invitation links**, single-use and/or time-limited. Players can issue them too, within a quota, if you allow it
- **Account recovery**: email confirmation, self-service password reset, and an admin-issued reset link for people whose self-service fails
- **Revocable sessions**: changing a password ends every other session, and "sign out everywhere" is one click. A ban or a demotion takes effect on the very next request
- **Your data is yours**: players can download everything held about their account, or close it permanently
- **Character claims**: a player claims an in-game character by name while that character is online. Being online *is* the proof of ownership, so the link is made immediately instead of waiting for review. Characters exist only through a claim. Removing one is an *unlink* that frees the name for someone else, and staff can revoke a link with a reason the player sees
- **Notifications**: character links, deliveries, bonuses and moderation decisions reach the player in-app

## Loot economy

- **Daily loot box**: every account can collect one box a day. The day boundary follows the primary game server's timezone, not UTC
- **Boxes and events**: a box is a named crate with its own loot pool. *Events* decide which box a player receives, by a weighted pick from the event's line-up of boxes. The daily event is always there; **custom events** add extra boxes on top of it for a limited window, either once or every day while they run — a weekend giveaway, a holiday crate, a server launch
- **Weekly streak bonus**: collect enough of the week's seven daily boxes (five by default) and a bonus box is granted automatically. Players see their progress on the Rewards page
- **Two kinds of reward**:
  - **Items**, delivered with `additem`, optionally in stacks
  - **Usables**: a sequence of console commands written by an admin — for example spawning a vehicle, granting XP or teleporting the player. `{{USERNAME}}` is replaced with the recipient, and `sleep`/`wait` lines pause between commands. A built-in command library inserts ready-made lines so nobody has to remember the syntax. Only admins can write these, and the recipient's name is validated before anything reaches the console
- **Item picker**: rewards and direct gives are chosen from a searchable list of every base-game item — icon, name and id — instead of typed from memory. The list comes from PZwiki's item list and is refreshed weekly. Modded items are not in it, so their ids are typed by hand
- **Drop weights** per reward in each box, and the number of draws per box, tuned in the panel rather than in code
- **Published odds**: players can see what each box contains and how likely each reward is, and review what they have already received
- **Inventory**: opened rewards wait until the player sends them to one of their own linked characters, which must be online at the time
- **Confirmed delivery**: the manager confirms each command actually reached the running server. If it did not, the item goes back to the player's inventory
- **Optional expiry** for unopened boxes and unsent rewards, off by default
- **Taking loot back**: an admin can remove unopened boxes and held rewards from an account, for mistakes and abuse

## Server management

- **Several servers on one host**, sharing a single game install and mod library
- **Live status**, player counts and a 24-hour activity chart, on the public Servers page and in the panel
- **Start, stop, sleep**, and a free-text console on each server's page. Console commands return what the game printed when RCON is configured, and fall back to the server's standard input otherwise
- **Log viewer**: tail any server's log from the panel, with follow, instead of needing shell access to diagnose a failed start
- **Game install from the panel**: see which build is installed, on which Steam branch, compared with what Steam is currently publishing — and install, update or switch branch from **Admin → Installations** rather than a shell
- **Server settings editor**: the server's INI options and its world (sandbox) settings, edited from the panel, with credential keys write-only and unknown keys preserved. Settings can be exported as a template and imported on another server
- **World backups**: archive a server's save from the panel — the running server is flushed to disk first — with retention pruning, download and upload of archives, and a restore that sets the replaced world aside rather than deleting it
- **Crash-loop protection**: a server that keeps failing to start is marked `failed` and left alone rather than restarted forever, and staff are alerted

### Wake on demand

A server can be put to **sleep**: the game process stops, but the server stays in the in-game server browser, so it costs nothing while idle and still looks joinable.

- A **direct-IP connection** wakes it outright.
- A **Steam join** never reaches the server itself — Steam brokers it — so waking relies on a heuristic: repeated server-info queries from the same address within a minute count as somebody on the connect screen. Browsing the server list can occasionally wake a server too; that is accepted by design. The threshold is [configurable](configuration.md#docker-composeyml).
- **Sleep when empty**: set a per-server timeout and a running server with nobody on it goes back to sleep by itself. The countdown starts only once the world has finished loading, and resets the moment anyone joins. Off by default.

## Workshop mods

- **One shared mod library**, managed from **Admin → Installations**. Paste a Workshop item id or URL and it is looked up on Steam first, so you see the mod's title, thumbnail and description — and a typo fails in a second instead of after a several-minute download that fetched nothing
- **Collections expand**: paste a Workshop *collection* URL and it becomes every mod in it, in the order its author arranged them, previewed before anything downloads. The collection is remembered, so enabling it on a server is one click that keeps that order
- **Per-server checklist**: each server picks what it loads from what is actually on disk. Mod names come from each mod's `mod.info`, so the name is chosen from a list rather than typed
- **Load order is editable, and checked**: each mod's declared requirements are checked against the order, flagging a dependency that is switched off or loads too late
- **Updates**: bring a server's mods up to date from the panel

## Moderation

- **Four roles**: `banned` < `player` < `moderator` < `admin`, re-read from the database on every request
- **Timed bans with reasons**, lifted automatically, restoring the role the account held before, with the full ban history kept
- **Bans reach the game**: banning an account kicks and bans its linked characters on every server, reported per server so a failure is visible
- **Reports and appeals**: players can report a problem to staff, and a banned player can still file an appeal — an appeal process a banned person cannot reach is not one
- **Give**: staff can send an item, or run a catalog action such as a kick or a teleport, on an online player without editing any rewards
- **Audit log** of every sensitive action: role changes, bans, server lifecycle and every console command with its text, character link decisions, reward and loot pool edits, and deliveries

## Staff alerts

One list of events, and as many destinations as you like. A destination is a **Discord webhook**, the in-panel **staff feed**, or an **ops mailbox**, and each one picks what it wants to hear:

- players joining and leaving, servers starting, stopping or giving up
- character links, sign-ups, bans, reports and appeals
- delivery failures and operational problems, such as the game-server manager becoming unreachable

Server events can be filtered to particular servers, so a per-server Discord channel stays about that server. A cooldown keeps a flapping problem from flooding a channel. A test button sends a sample and shows what came back, a webhook URL is stored like a password and never shown again, and a destination that is gone for good is switched off rather than retried forever. The text of a player's report reaches the staff feed and ops mail, never Discord.

The **staff feed** lists every alert that actually fired, newest first, and is readable by moderators. It is also how you tell "nothing happened" apart from "the Discord webhook was deleted".

## Admin panel

Grouped under `/admin`:

| Group | Screens |
|---|---|
| **Servers** | Servers (status, control, console, logs, settings, backups, mods), Installations (game files and the mod library), Tasks (the work queue and its output) |
| **Users** | Users, Character Links, Invitations, Reports & Appeals |
| **Rewards** | Rewards, Loot Boxes, Events, Give Item |
| **Site** | Branding, Pages (rules and legal documents) |
| **System** | About, Staff Feed, Audit Log, Scheduled Jobs, Alerts, Settings |

- **Runtime settings**: registration, invitations, loot expiry, retention, session length and mail are editable in the panel and take effect immediately, without a restart
- **Scheduled jobs**: the streak bonus, retention sweeps and recurring server maintenance, each switchable, with its last result on show
- **Branding**: the site's name, home page text and footer links are yours to change, so a community can run it under its own name

### What each role can do

| Role | Can |
|---|---|
| `banned` | File an appeal. Everything else is refused |
| `player` | Claim characters, collect and send loot, invite others (if allowed), file reports, manage their own account |
| `moderator` | Everything a player can, plus: start, stop and sleep servers; **use the free-text server console**; read logs, settings and backups; switch already-downloaded mods on and off; watch and cancel tasks; revoke character links; give items and run catalog actions; handle reports; read the staff feed and audit log |
| `admin` | Everything, plus: roles and bans; creating, editing and deleting servers; server settings, backups and restores; installing the game and mods; rewards, loot boxes and events; branding and pages; alerts, scheduled jobs and settings |

The server console accepts any command, so **making someone a moderator gives them full control of the running game**. Every command they run is recorded in the audit log with its text, but treat the role as the trust decision it is.

## Community presets

Two kinds of ready-made configuration are published in this repository's [`community/`](../community) folder and can be imported from the panel:

- **Loot boxes** (`community/reward-boxes/`): a box's rewards and drop weights. Import them from **Admin → Rewards → Loot Boxes → Import config**
- **Server templates** (`community/server-templates/`): gameplay settings and sandbox options for a style of play, such as *Relaxed*. Apply them from a server's settings page with **Import template**, while the server is stopped

Both can be exported from your own panel, too. If you have a setup worth sharing, add it to `community/` with an entry in that folder's `list.json`, and open a pull request.
