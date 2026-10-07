# zomboid_db_api

Read Project Zomboid `players.db` files from Python: every character, alive or dead,
with its owner, name, status, time alive, location and all its saved data (health,
skills, traits, kills, clothing, inventory, ...). It can also read the server's account
database and check a user's login, see [Login](#login-authentication).

* Python 3.9 or newer, standard library only. Checking passwords additionally needs the
  `bcrypt` package (`pip install bcrypt`).
* Read-only. The file is opened in SQLite's read-only mode, read in one query and closed
  immediately, so it is safe to use on a running server.
* Works with Build 41 and Build 42 saves.

The example outputs below come from a real Build 42 server save (Steam IDs masked).
The ones about dead or undecodable characters come from a test save, as the real one
has none.

## Setup

Copy this `zomboid_db_api` folder into your project (or anywhere on the Python path) and
import it:

```python
from zomboid_db_api import PlayersDB
```

## Where the files are

| File | Path |
|---|---|
| Characters, server | `Zomboid/Saves/Multiplayer/<servername>/players.db` |
| Characters, single player | `Zomboid/Saves/<game mode>/<save name>/players.db` |
| Server accounts | `Zomboid/db/<servername>.db` |

`Zomboid` is `C:\Users\<you>\Zomboid` on Windows and `~/Zomboid` on Linux.

## Quick start

```python
from zomboid_db_api import PlayersDB

db = PlayersDB("Zomboid/Saves/Multiplayer/servertest/players.db")

for p in db.getPlayers():
    print(p.getOwner(), p.getName(), p.getStatus(), p.getTimeAlive(), p.getLocation())
```

```text
thanos Da Sheep alive 6 days 18 hours 8128,11744,1
...                                  (one line per character)
```

```python
>>> p = db.getPlayer("thanos")      # owner username or character name, any case
>>> p.getZombieKills()
86
>>> p.getProfession()
'base:doctor'
>>> p.getSkillLevel("Doctor")
6
```

One-call shortcuts, without keeping a `PlayersDB` around:

```python
>>> from zomboid_db_api import getPlayers, getPlayer
>>> getPlayer("path/to/players.db", "thanos")
<Player 'Da Sheep' owner='thanos' alive>
>>> getPlayers("path/to/players.db", status="dead")
[]
```

## `PlayersDB(path, worldDictionary=None)`

Reads the file once. The `worldDictionary` argument is explained under
[Item names](#item-names).

| Method | Returns |
|---|---|
| `getPlayers(status=None)` | all characters; `status="alive"` or `"dead"` to filter |
| `getAlivePlayers()`, `getDeadPlayers()` | the same, filtered |
| `getPlayer(name)` | the character whose owner username or character name matches (case-insensitive), or `None` |
| `getPlayersByOwner(owner)` | all characters of an account (split-screen players share an owner) |
| `getPlayersBySteamId(steamId)` | characters of a Steam account |
| `getOwners()` | account usernames that have a character, sorted |
| `getPlayerCount(status=None)` | number of characters |
| `refresh()` | read the file again, to pick up what the game saved since |

`PlayersDB` can also be iterated (`for p in db`) and has a length (`len(db)`).
Single-player characters are included; their `getOwner()` is `None`.

```python
>>> db
<PlayersDB 'players.db' 5 characters>
>>> len(db), db.getPlayerCount("alive"), db.getPlayerCount("dead")
(5, 5, 0)
>>> db.getPlayer("Da Sheep")
<Player 'Da Sheep' owner='thanos' alive>
>>> db.getPlayer("nobody") is None
True
>>> db.getPlayersByOwner("thanos")
[<Player 'Da Sheep' owner='thanos' alive>]
>>> db.getOwners()               # sorted usernames (other players' names left out here)
[..., 'thanos']
```

## `Player`

### From the database row (instant)

| Method | Returns |
|---|---|
| `getOwner()` | account username |
| `getName()` | character name, `"Forename Surname"` |
| `getStatus()`, `isAlive()`, `isDead()` | `"alive"` / `"dead"` |
| `getLocation()` | `"x,y,z"` in whole tiles (the format map.projectzomboid.com and `/teleportto` use) |
| `getX()`, `getY()`, `getZ()` | exact position |
| `getSteamId()`, `getWorld()`, `getSlot()` | Steam ID, world name, split-screen slot (1 = main player) |
| `isSinglePlayer()`, `getWorldVersion()` | single-player row?; save-format version (195 = Build 41, 219+ = Build 42) |

```python
>>> p.getOwner(), p.getName(), p.getStatus(), p.isAlive(), p.isDead()
('thanos', 'Da Sheep', 'alive', True, False)
>>> p.getLocation()
'8128,11744,1'
>>> p.getX(), p.getY(), p.getZ()
(8128.51904296875, 11744.587890625, 1.0)
>>> p.getSteamId(), p.getWorld(), p.getSlot()
('7656119xxxxxxxxxx', 'Alpha', 1)
>>> p.isSinglePlayer(), p.getWorldVersion()
(False, 249)
```

### From the character data

These decode the character's data the first time one of them is called (a few
milliseconds), then use the cached result.

| Method | Returns |
|---|---|
| `getHoursSurvived()` | in-game hours survived; for a dead character, how long it lived |
| `getTimeAlive()` | the same as text, e.g. `"6 days 18 hours"` |
| `getDaysSurvived()` | the same in days |
| `getZombieKills()`, `getSurvivorKills()` | kill counts |
| `getGender()`, `getProfession()`, `getTraits()` | identity |
| `getSkills()` | `{skill: {"level": int, "xp": float}}` |
| `getSkillLevel(skill)` | one skill's level, 0 if never trained |
| `getHealth()` | injuries, all 17 body parts, cold and infection fields |
| `isZombieInfected()` | `True` if the character carries the zombie virus |
| `getStats()` | hunger, thirst, fatigue, panic, stress, ... as stored |
| `getNutrition()` | weight, calories, proteins, lipids, carbohydrates |
| `getWornItems()` | clothing and bags by body slot |
| `getHands()` | items in the primary and secondary hand |
| `getInventory()`, `getItemCount()` | items carried (bags list their `"contents"`); total item count |
| `getKnownRecipes()` | recipe names |
| `getModData()` | the character's Lua `modData` table (game and mod data) |
| `toDict()`, `toJson()` | everything, in the sections below |
| `isDecoded()`, `getDecodeErrors()` | whether the data was decoded completely, and if not, why |
| `getState()` | the decoded objects themselves (`PlayerState`), for advanced use |

Time, kills and identity:

```python
>>> p.getHoursSurvived(), p.getTimeAlive(), p.getDaysSurvived()
(162.04120652316487, '6 days 18 hours', 6.751716938465203)
>>> p.getZombieKills(), p.getSurvivorKills()
(86, 0)
>>> p.getGender(), p.getProfession(), p.getTraits()
('male', 'base:doctor', [])
```

Traits look like `['base:nightowl', 'base:fit']` when a character has them.

Skills:

```python
>>> p.getSkills()
{'Blunt': {'level': 1, 'xp': 179.20386},
 'Carving': {'level': 0, 'xp': 2.5},
 'Doctor': {'level': 6, 'xp': 5799.8994},
 'Farming': {'level': 2, 'xp': 225.0},
 'Fitness': {'level': 5, 'xp': 38025.0},
 'Strength': {'level': 5, 'xp': 40203.0},
 ...}
>>> p.getSkillLevel("Doctor"), p.getSkillLevel("Cooking")
(6, 0)
```

Health and condition:

```python
>>> p.isZombieInfected()
False
>>> h = p.getHealth()
>>> list(h)
['injuries', 'zombie_infected', 'body_parts', 'body', 'thermoregulator']
>>> h["injuries"]                    # an injured part looks like the example below
[]
>>> h["body_parts"][0]
{'name': 'Hand_L', 'health': 100.0, 'bitten': False, 'scratched': False, 'cut': False,
 'bandaged': False, 'bleeding': False, 'deep_wounded': False, 'fake_infected': False,
 'infected': False, ..., 'stitched': False, ..., 'fracture_time': 0.0, 'splint': False, ...,
 'burn_time': 0.0, ..., 'bandage_type': 'Base.AlcoholRippedSheets', ..., 'conditions': []}
>>> p.getStats()
{'anger': 0.0, 'boredom': 1.8341901, 'discomfort': 9.6, 'endurance': 1.0,
 'fatigue': 1.664762e-05, 'hunger': 0.15206946, 'morale': 1.0, 'panic': 0.0,
 'stress': 0.0, 'temperature': 37.09435, 'thirst': 0.057509553, 'zombie_infection': 0.0, ...}
>>> p.getNutrition()
{'calories': -2200.0, 'proteins': -185.11273, 'lipids': -154.90973,
 'carbohydrates': 0.67124003, 'weight': 77.74612}
```

An entry in `injuries` looks like
`{'part': 'Hand_L', 'health': 62.5, 'conditions': ['bitten', 'zombie infection', 'bandaged']}`.

Equipment and inventory:

```python
>>> p.getWornItems()
[{'slot': 'base:belt', 'name': 'Base.Belt2', 'type': 'Base.Belt2', 'item_id': 2026229278},
 {'slot': 'base:hat', 'name': 'Base.Hat_Cowboy', 'type': 'Base.Hat_Cowboy', 'item_id': 548822238},
 ...]
>>> p.getHands()
{'primary_hand': {'name': '<item #1618>', 'type': None, 'item_id': 104229161},
 'secondary_hand': {'name': '<item #1618>', 'type': None, 'item_id': 104229161},
 'two_handed': True}
>>> p.getItemCount()
31
>>> p.getInventory()
[{'name': 'Base.Belt2', 'type': 'Base.Belt2', 'kind': 'Clothing',
  'details': {'last_wetness_update': 205.49533},
  'properties': {'wet_cooldown': 0.0, 'initialised': True},
  'mod_data': {'customName': 'Belt'}, 'registry_id': 2463, 'item_id': 2026229278},
 {'name': 'Base.Tshirt_PoloStripedTINT', 'type': 'Base.Tshirt_PoloStripedTINT', 'kind': 'Clothing',
  'condition': 8, 'details': {'dirtiness': 4.54902, 'last_wetness_update': -1.0},
  'properties': {'wet_cooldown': 0.0, 'initialised': True},
  'mod_data': {'customName': 'T-shirt - Striped Polo'}, 'registry_id': 2264, 'item_id': 63343599},
 ...,
 {'name': 'Base.Bag_WorkerBag', 'type': 'Base.Bag_WorkerBag', 'kind': 'Container',
  'properties': {...}, 'mod_data': {'customName': 'Duffel Bag'},
  'container': {'type': 'Bag_WorkerBag', 'capacity': 18, 'weight_reduction': 65},
  'contents': [
      ...,
      {'name': '<item #4398>', 'type': None, 'kind': 'Weapon',
       'details': {'max_range': 1.1, 'min_damage': 0.5, 'max_damage': 1.0, ...},
       'properties': {...}, 'mod_data': {'customName': 'Claw Hammer'},
       'registry_id': 4398, 'item_id': 1022222072},
      ...],
  'registry_id': 598, 'item_id': 40096483},
 ...]
```

Each item has `name`, `type`, `kind` (Clothing, Container, Weapon, Food, Literature,
Key, ...), `registry_id` and `item_id`. Depending on the item it also has
`count`, `condition`, `uses` and `details` (food age and cooking, weapon stats, clothing
dirt and wetness, fluids, alarm time, pages read, ...).

Recipes and mod data:

```python
>>> p.getKnownRecipes()
['MakePlantainPoultice', 'MakeComfreyPoultice', 'MakeWildGarlicPoultice', 'KnitWoolyHat', ...]
>>> p.getModData()
{'strengthUpTimer': -49710, 'strengthMod': 0, 'fitnessUpTimer': -49740, 'fitnessMod': 0,
 'Fav:Bare Hands': 6, 'hotbar': ['Back', 'SmallBeltLeft', 'SmallBeltRight'], ...}
```

Decoding status:

```python
>>> p.isDecoded(), p.getDecodeErrors()
(True, [])
```

Getters never raise on bad data. If a character's data cannot be decoded, the row
getters still work, the decoded ones return `None` or empty values, and
`getDecodeErrors()` explains what happened:

```python
>>> broken.isDecoded()
False
>>> broken.getTimeAlive(), broken.getLocation()
(None, '10875,9781,1')
>>> broken.getDecodeErrors()
['header section (starting at byte 0): need 4 bytes, 3 left (at byte 6)']
```

## `toDict()` and `toJson()`

A plain, JSON-ready `dict` with these sections:

| Key | Contents |
|---|---|
| `owner` | username, Steam ID, world, split-screen slot, table and row id |
| `character` | name, gender, profession, traits, starting skill bonuses, display name |
| `status` | alive/dead, hours survived, time alive, kills, infected, asleep, on fire, in vehicle |
| `location` | x, y, z, `"x,y,z"`, facing direction, vehicle seat |
| `health` | injuries, every body part (health, bites, scratches, fractures, bandages, ...), body fields |
| `condition` | every stat (for Build 42 with a percentage of the game's range), nutrition, medication effects |
| `skills` | level and XP per skill, XP multipliers |
| `equipment` | worn items by slot, primary and secondary hand |
| `inventory` | items with condition, uses, food state, fluids, alarms, key ids, custom names; bags nested |
| `knowledge` | recipes, books and pages read, magazines, flyers, TV/radio lines heard, craft history |
| `appearance` | hair, beard, skin, blood and dirt per body part, voice |
| `other` | chat tag, admin flags, cheats, timers, fitness |
| `mod_data` | the character's `modData` |
| `decoding` | save version, completeness, errors |

```python
>>> d = p.toDict()
>>> d["owner"]
{'username': 'thanos', 'steam_id': '7656119xxxxxxxxxx', 'world': 'Alpha',
 'split_screen_slot': 1, 'table': 'networkPlayers row 1'}
>>> d["character"]
{'name': 'Da Sheep', 'forename': 'Da', 'surname': 'Sheep', 'gender': 'male',
 'profession': 'base:doctor', 'traits': [],
 'starting_skill_bonuses': {'Doctor': 3, 'SmallBlade': 1, 'Fitness': 3, 'Strength': 3},
 'descriptor_extras': [], 'display_name': 'thanos'}
>>> d["status"]
{'status': 'alive', 'hours_survived': 162.04120652316487, 'time_alive': '6 days 18 hours',
 'days_survived': 6.75, 'zombie_kills': 86, 'survivor_kills': 0, 'zombie_infected': False,
 'asleep': False, 'on_fire': False, 'in_vehicle': False}
>>> d["location"]
{'x': 8128.51904296875, 'y': 11744.587890625, 'z': 1.0, 'location': '8128,11744,1',
 'facing': 'SE', 'vehicle': None}
>>> d["condition"]["stats"]["hunger"], d["condition"]["stats"]["temperature"]
({'value': 0.15206946, 'percent': 15.2}, {'value': 37.09435})
>>> list(d["knowledge"])
['known_recipes', 'skill_books_read', 'literature_read', 'print_media_read',
 'books_finished', 'tv_radio_lines_heard', 'craft_history']
>>> d["knowledge"]["craft_history"][0]
{'recipe': 'RipSheets', 'count': 1, 'last_craft_time': 45.32619819880347}
>>> d["decoding"]
{'world_version': 249, 'build': 'Build 42', 'layout': 'B42 (world version 249)',
 'confidence': 'exact', 'complete': True, 'bytes': 17948, 'errors': [], 'warnings': []}
```

`p.toJson()` returns the same as a JSON string (`toJson(indent=None)` for one line).

## Item names

Items are stored as numeric ids. Their names (`Base.Axe`) are in the save's
`WorldDictionary.bin`, in the same folder as `players.db`:

* By default, `PlayersDB` uses the `WorldDictionary.bin` next to `players.db` if there
  is one.
* `PlayersDB(path, worldDictionary="other/folder/WorldDictionary.bin")` uses that file
  instead.
* `PlayersDB(path, worldDictionary=False)` never uses one.

Without it, items show as `<item #1618>` unless they carry a clothing or custom name.
From the test save, which has a `WorldDictionary.bin` next to its `players.db`:

```python
>>> PlayersDB(path, worldDictionary=False).getPlayer("apo").getHands()["primary_hand"]["name"]
'<item #10>'
>>> PlayersDB(path).getPlayer("apo").getHands()["primary_hand"]["name"]
'Base.Pistol'
```

## Login (authentication)

`ServerDB` reads the server's account database (`Zomboid/db/<servername>.db`) the same
way `PlayersDB` reads characters: read-only, in one go, then the file is closed. It
checks a user's login exactly as the game does. Checking a password needs the `bcrypt`
package (`pip install bcrypt`).

```python
from zomboid_db_api import ServerDB

server = ServerDB("Zomboid/db/servertest.db")

result = server.authenticate("thanos", "secret")
if result:
    print("welcome", result.account.getUsername(), result.account.getRole())
else:
    print("login failed:", result.reason)
```

| Method | Returns |
|---|---|
| `ServerDB(path)` | reads the account database |
| `authenticate(username, password=None, code=None)` | an `AuthResult`; true if the login is valid |
| `getAccount(username)` | the account (case-insensitive, like the game), or `None`; use it to see what to ask for |
| `refresh()` | read the file again, to pick up password, role and ban changes |

`AuthResult` has `authenticated` (also its truth value), `reason` and `account`:

| `reason` | Meaning |
|---|---|
| `"ok"` | valid login |
| `"unknown_user"` | no such account |
| `"wrong_password"` | the password does not match |
| `"no_password_set"` | the account has no password; refused, although the game would let it in |
| `"code_required"`, `"wrong_code"` | the account uses Google Authenticator (Build 42) and `code` is missing or wrong |
| `"banned"` | valid credentials, but the account is banned or its role may not log in |

The `account` (also returned by `getAccount`):

| Method | Returns |
|---|---|
| `getUsername()` | username, as stored |
| `getRole()` | `"admin"`, `"moderator"`, `"user"`, `"banned"`, ... (Build 42: the role's name) |
| `isBanned()`, `getBanReason()` | whether the account may not log in, and why |
| `getAuthMethod()` | `"password"`, `"authenticator"` or `"password+authenticator"`: what to ask the user for |

The password hash is never exposed.

```python
>>> server
<ServerDB 'servertest.db' 10 accounts>
>>> account = server.getAccount("thanos")
>>> account
<Account 'thanos' role='user'>
>>> account.getRole(), account.isBanned(), account.getAuthMethod()
('user', False, 'password')
>>> server.authenticate("thanos", "secret")
AuthResult(authenticated=True, reason='ok', account=<Account 'thanos' role='user'>)
>>> server.authenticate("thanos", "wrong")
AuthResult(authenticated=False, reason='wrong_password', account=<Account 'thanos' role='user'>)
>>> server.authenticate("nobody", "secret")
AuthResult(authenticated=False, reason='unknown_user', account=None)
>>> server.authenticate("griefer", "secret")
AuthResult(authenticated=False, reason='banned', account=<Account 'griefer' role='banned' BANNED>)
>>> server.getAccount("hank").getAuthMethod()
'password+authenticator'
>>> server.authenticate("hank", "secret")
AuthResult(authenticated=False, reason='code_required', account=<Account 'hank' role='user'>)
>>> server.authenticate("hank", "secret", code="287082")
AuthResult(authenticated=True, reason='ok', account=<Account 'hank' role='user'>)
```

(The account examples come from a real server database; the logins from a test
database with known passwords, where the authenticator code was valid for the clock time
used in the test.)

After a successful login, the user's character is one lookup away:

```python
>>> players = PlayersDB("Zomboid/Saves/Multiplayer/servertest/players.db")
>>> players.getPlayer(result.account.getUsername())
<Player 'Da Sheep' owner='thanos' alive>
```

Good to know:

* Passwords are checked the way the game stores them: `bcrypt(md5(password))`. Without
  the `bcrypt` package, `authenticate` raises an `ImportError` that says so. Very old
  Build 41 accounts that still hold a plain-text or plain-MD5 password are checked too.
* Bans are reported only for correct credentials, so a wrong password never reveals
  that an account is banned. Show your users one generic "login failed" message; the
  distinct reasons are for your own logic and logs.
* Unknown usernames take as long to check as real ones, so response time does not
  reveal which usernames exist.
* Each password check takes about 0.2 seconds (the game's bcrypt cost), which slows down
  guessing. Limiting repeated attempts is up to your application.

## Good to know

* **Freshness:** the data is what the game last saved for each character. Call
  `refresh()` to read the file again.
* **Dead characters** keep their row, marked dead, with their time alive and the place
  they died, until their owner creates a new character. The new character overwrites
  the row, so a `players.db` holds one character per account (and split-screen slot),
  not a history of past deaths:

  ```python
  >>> for p in db.getDeadPlayers():
  ...     print(p.getOwner(), p.getName(), "lived", p.getTimeAlive(), "died at", p.getLocation())
  apo Kate Smith lived 1 day 6 hours died at 10875,9781,1
  ```

* **Time alive** is in-game time; how it relates to real time depends on the server's
  day-length setting.

## Advanced

* `p.getState()` returns the full `PlayerState` object:

  ```python
  >>> st = p.getState()
  >>> st.full_name, st.direction, st.complete
  ('Da Sheep', 'SE', True)
  >>> sum(1 for _ in st.inventory.walk())       # every item, including bag contents
  28
  >>> st.body.part("Hand_L").health
  100.0
  ```

* `decode_player(blob, world_version)` decodes a character's raw `data` column directly.
* Save formats change with game updates. The decoder recognises the known ones and
  adapts to small changes on its own; anything it cannot read is reported in
  `getDecodeErrors()`. To describe a new game version's format yourself, use
  `register_layout()` (see `versions.py`):

  ```python
  from zomboid_db_api import register_layout

  register_layout(260, 270, craft_history=True, auto_drink=True)   # world versions 260..270
  ```
