# Features

The full tour. The [README](../README.md) has the highlights; this page has the detail.

- [Accounts and characters](#accounts-and-characters)
- [Loot economy](#loot-economy)
- [Coins and the shop](#coins-and-the-shop)
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
- **Sessions that last while used**: a sign-in stays alive as long as it keeps being used, and expires a set time after it was last used: a day on the website, a month in the installed app, both adjustable
- **Revocable sessions**: changing a password ends every other session, and "sign out everywhere" is one click. A ban or a demotion takes effect on the very next request
- **Your data is yours**: players can download everything held about their account, or close it permanently
- **Character claims**: a player claims an in-game character by name while that character is online. Being online *is* the proof of ownership, so the link is made immediately instead of waiting for review. Characters exist only through a claim. Removing one is an *unlink* that frees the name for someone else, and staff can revoke a link with a reason the player sees. Staff also see the characters saved on each server that nobody has linked, and an admin can link one to an account by hand, for a character that cannot be online to claim
- **Character sheet**: a linked character's card shows what the game last saved about it - alive or dead, time survived, kills, profession, top skills and where it is, with a map link - and a details dialog with every skill and its health. Read from the server's save and cached for a minute, so it is as fresh as the game's last save; when the game server cannot answer, the last copy is shown marked as possibly out of date. Only the owner sees it, and staff from the character links and user pages. A zombie infection is shown to staff only, since in the game a player does not know until the symptoms show
- **Notifications**: character links, deliveries, bonuses and moderation decisions reach the player in-app

## Loot economy

- **Daily loot box**: every account can collect one box a day. The day boundary follows the primary game server's timezone, not UTC
- **Boxes and events**: a box is a named crate with its own loot pool. *Events* decide which box a player receives, by a weighted pick from the event's line-up of boxes. The daily event is always there; **custom events** add extra boxes on top of it for a limited window, either once or every day while they run — a weekend giveaway, a holiday crate, a server launch
- **Crate reminders**: players can turn on notifications in their profile (or the app's Me tab), per device. Once a day, at a time an admin sets, every device whose player has not claimed today's crate gets a notification that opens Rewards. Works in desktop and Android browsers and the installed app; on iPhone and iPad only once the site is added to the Home Screen. Reminders belong to the sign-in they were turned on in: they stop when it expires or is signed out, and resume when the player signs in on that device again. Switch the `crate_reminder` job on to start sending
- **Weekly streak bonus**: collect enough of the week's seven daily boxes (five by default) and a bonus box is granted the moment the last one needed is collected. Players see their progress on the Rewards page
- **Two kinds of reward**:
  - **Items**, delivered with `additem`, optionally in stacks
  - **Usables**: a sequence of console commands written by an admin — for example spawning a vehicle, granting XP or teleporting the player. `{{USERNAME}}` is replaced with the recipient, and `sleep`/`wait` lines pause between commands. A built-in command library inserts ready-made lines so nobody has to remember the syntax. Only admins can write these, and the recipient's name is validated before anything reaches the console
- **Item picker**: rewards and direct gives are chosen from a searchable list of every base-game item — icon, name and id — instead of typed from memory. The list comes from PZwiki's item list and is refreshed weekly. Modded items are not in it, so their ids are typed by hand
- **Drop weights** per reward in each box, and the number of draws per box, tuned in the panel rather than in code
- **Published odds**: players can see what each box contains and how likely each reward is, and review what they have already received
- **Inventory**: opened rewards wait until the player sends them to one of their own linked characters, which must be online at the time. Each reward is a bundle - the amount it was won in - and getting the same one again stacks it, showing both numbers apart ("3 bundles of 5"). The player picks how many bundles to send, up to 20 at a time (5 for usables), and they go out as one delivery
- **Confirmed delivery**: the manager confirms each command actually reached the running server. If it did not, the item goes back to the player's inventory - and if a delivery stopped part-way, only the bundles that did not arrive come back
- **Optional expiry** for unopened boxes and unsent rewards, off by default
- **Taking loot back**: an admin can remove unopened boxes and held rewards from an account, for mistakes and abuse

## Coins and the shop

Off by default; switch it on under **Settings → Coins**, and switch on the `settle_coins` and `coin_report` jobs under **Scheduled Jobs**.

- **Selling back**: every reward has a sell value in coins (1 by default, 0 means it cannot be sold), paid once per bundle however many items it holds. With coins on, discarding an unsent reward sells it one bundle at a time, and the confirmation shows exactly which bundle, what it pays and how many are left. Hovering a reward in the inventory (or tapping its info button) shows what it is, what each bundle holds, how many bundles there are, what one sells for and when the next expires
- **Coins from playing**: a linked character earns coins for the zombies it kills, at a rate the admin sets (1 coin per 10 kills by default). Kills made before the character was linked never count, and kills left over carry to the next payment. A death is noticed by the character's new name and the new character counts from zero; restoring a world backup never pays its kills again. Kills come from the server's save: characters are checked whenever their data is viewed, and once a day every server with players online is told to save first and all its characters are read in one go. The Characters page shows each character's progress to its next coin and when it was last checked
- **A daily summary**: instead of a message per payment, each player gets one message a day with what they earned the day before and where it came from
- **The shop**: categories of rewards for sale, set up by an admin under **Rewards → Shop**. A listing can appear in several categories and can have a daily limit per player. A new listing's price starts at 20 times what the reward sells back for; the admin can change it, but never below the sell value, so buying and selling back cannot make coins. What a player buys goes to their inventory and is sent like any other reward, with its own expiry setting, which the shop page states
- **The balance** shows in the navbar, on the Rewards page and on the app's Me tab. An admin can add or take coins, with a reason the player sees, from the account's manage page, which also lists every coin the account has gained and each linked character's progress. The coin history and purchase records are trimmed daily to a retention window (90 days by default); balances and totals are unaffected

## Leaderboard

Every living character in a server's save, linked or not, ranked by zombie kills and then by time alive (in-game time). Players see each character's name, profession, kills and time alive, never the account it belongs to; a dead character drops off. An admin decides under **Users → Leaderboard** who can see it - everyone, signed-in players only, or nobody but staff - keeps a list of usernames to leave out, and can hide characters linked to banned accounts (on by default). Staff see the whole board there, hidden characters included and marked why.

## Server management

- **Several servers on one host**, sharing a single game install and mod library
- **Live status**, player counts and a 24-hour activity chart, on the public Servers page and in the panel
- **Start, stop, sleep**, and a free-text console on each server's page. Console commands return what the game printed when RCON is configured, and fall back to the server's standard input otherwise
- **Log viewer**: tail any server's log from the panel, with follow, instead of needing shell access to diagnose a failed start
- **Game install from the panel**: see which build is installed, on which Steam branch, compared with what Steam is currently publishing — and install, update or switch branch from **Admin → Installations** rather than a shell
- **Server settings editor**: the server's INI options and its world (sandbox) settings, edited from the panel, with credential keys write-only and unknown keys preserved. Settings can be exported as a template and imported on another server
- **World backups**: archive a server's save from the panel — the running server is flushed to disk first — with retention pruning, download and upload of archives, and a restore that sets the replaced world aside rather than deleting it
- **Crash-loop protection**: a server that keeps failing to start is marked `failed` and left alone rather than restarted forever, and staff are alerted

### Maintenance

Game and mod updates, applied without anybody having to be awake for them. Configured under **Admin → Installations → Maintenance**.

- **Checks** run on cron schedules of your choosing — one for the game, one for mods — and again whenever a server stops, sleeps or fails, which is the moment an update costs nobody anything. A game check compares the installed build with Steam's latest on the *installed* branch; a mod check compares each Workshop item a server uses with the version on the Workshop. **Check now** does both on demand.
- **Approval** is per kind: by default a game update is planned on its own, while a mod update waits for an admin to review it. The review shows each mod's installed and published dates, its size, the servers using it, the version its `mod.info` declares, and a link to its changelog — the Workshop records dates, not version numbers, so the new version's number cannot be known before downloading it.
- **When it goes out**: as soon as every server is empty or asleep, in a maintenance window (a cron schedule, `0 5 * * *` by default), or after a maximum wait — whichever comes first. Staff can also start it straight away.
- **Players are warned** in game on a configurable countdown — 15, 10 and 5 minutes, then 30, 15 and 5 seconds by default — and the public Servers page shows when the restart is. If everybody leaves during the countdown, it goes at once.
- **Every server goes down** for any update, and shows as `maintenance` meanwhile: they share one install and one mod library, so there is no safe way to update one while another runs. A sleeping server stops listening too, so nobody can wake it onto half-written files. Each server returns to whatever it was doing — running, asleep or stopped — when the update finishes or fails.
- **Moderators can cancel** a planned run up to the moment the files start changing. The same updates are then not planned again on their own until the next maintenance window; anything newer is.
- **Excluding a mod** keeps it out of automatic updates, though it can still be picked by hand. Treat it as temporary: players' Steam clients always fetch a mod's latest version, and a server on an older one can turn them away.
- **Updating by hand** from Installations is refused while any server is running or asleep. Stop them first, or plan it as maintenance.

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
- **Updates**: checked and applied by [maintenance](#maintenance), or brought up to date by hand for one server from the panel

## Moderation

- **Four roles**: `banned` < `player` < `moderator` < `admin`, re-read from the database on every request
- **Timed bans with reasons**, lifted automatically, restoring the role the account held before, with the full ban history kept
- **Bans reach the game**: banning an account kicks and bans its linked characters on every server, reported per server so a failure is visible
- **Reports and appeals**: players can report a problem to staff, and a banned player can still file an appeal — an appeal process a banned person cannot reach is not one
- **Give**: staff can send an item, or run a catalog action such as a kick or a teleport, on an online player without editing any rewards
- **Audit log** of every sensitive action: role changes, bans, server lifecycle and every console command with its text, character link decisions, staff views of a character's game data, reward and loot pool edits, and deliveries

## Staff alerts

One list of events, and as many destinations as you like. A destination is a **Discord webhook**, the in-panel **staff feed**, or an **ops mailbox**, and each one picks what it wants to hear:

- players joining and leaving, servers starting, stopping or giving up
- character links, sign-ups, bans, reports and appeals
- updates found, maintenance planned, starting, finishing, failing or being cancelled
- delivery failures and operational problems, such as the game-server manager becoming unreachable

Server events can be filtered to particular servers, so a per-server Discord channel stays about that server. A cooldown keeps a flapping problem from flooding a channel. A test button sends a sample and shows what came back, a webhook URL is stored like a password and never shown again, and a destination that is gone for good is switched off rather than retried forever. The text of a player's report reaches the staff feed and ops mail, never Discord.

The **staff feed** lists every alert that actually fired, newest first, and is readable by moderators. It is also how you tell "nothing happened" apart from "the Discord webhook was deleted".

## Admin panel

Grouped under `/admin`:

| Group | Screens |
|---|---|
| **Servers** | Servers (status, control, console, logs, settings, backups, mods), Installations (maintenance, game files and the mod library), Tasks (the work queue and its output) |
| **Users** | Users, Character Links, Leaderboard, Invitations, Reports & Appeals |
| **Rewards** | Rewards, Loot Boxes, Shop, Events, Give Item |
| **Site** | Branding, Pages (rules and legal documents) |
| **System** | About, Staff Feed, Audit Log, Scheduled Jobs, Alerts, Settings |

- **Runtime settings**: registration, invitations, loot expiry, coins, retention, session length and mail are editable in the panel and take effect immediately, without a restart
- **Scheduled jobs**: the streak bonus, the crate reminder, kill coins and retention sweeps, each switchable, with its last result on show
- **Branding**: the site's name, home page text and footer links are yours to change, so a community can run it under its own name

### What each role can do

| Role | Can |
|---|---|
| `banned` | File an appeal. Everything else is refused |
| `player` | Claim characters, collect and send loot, invite others (if allowed), file reports, manage their own account |
| `moderator` | Everything a player can, plus: start, stop and sleep servers; **use the free-text server console**; read logs, settings and backups; switch already-downloaded mods on and off; watch and cancel tasks; cancel a planned maintenance; revoke character links and view a linked character's game data; give items and run catalog actions; handle reports; read the staff feed and audit log |
| `admin` | Everything, plus: roles and bans; linking a saved character to an account by hand; creating, editing and deleting servers; server settings, backups and restores; installing the game and mods; the maintenance policy and planning updates; rewards, loot boxes, the shop and events; players' coin balances; branding and pages; alerts, scheduled jobs and settings |

The server console accepts any command, so **making someone a moderator gives them full control of the running game**. Every command they run is recorded in the audit log with its text, but treat the role as the trust decision it is.

## Community presets

Two kinds of ready-made configuration are published in this repository's [`community/`](../community) folder and can be imported from the panel:

- **Loot boxes** (`community/reward-boxes/`): a box's rewards and drop weights. Import them from **Admin → Rewards → Loot Boxes → Import config**
- **Server templates** (`community/server-templates/`): gameplay settings and sandbox options for a style of play, such as *Relaxed*. Apply them from a server's settings page with **Import template**, while the server is stopped

Both can be exported from your own panel, too. If you have a setup worth sharing, add it to `community/` with an entry in that folder's `list.json`, and open a pull request.
