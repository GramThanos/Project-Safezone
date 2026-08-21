#!/usr/bin/env python3
import os
import re
import sys
import pwd
import subprocess
import vdf

# Configuration via Environment or Defaults
STEAMCMD_BIN = os.path.join(
    os.environ.get("STEAMCMDDIR", "/home/steam/steamcmd/"),
    "steamcmd.sh"
)
#DEBUG = os.environ.get("DEBUG", "true")

# ANSI escape sequences (colours, cursor movement, erase-line, hide-cursor, ...).
_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')


# Workshop content lives under Project Zomboid's own app id.
WORKSHOP_APP_ID = "108600"


def clean_console_output(text):
    """Collapse terminal control output into plain, readable log lines.

    SteamCMD reports download progress by rewriting a single line: it prints a
    progress string, emits a carriage return to move the cursor back to column
    0, then prints the next state over the top. Captured to a string that
    becomes one very long line holding every intermediate state.

    For each physical line we keep only the last carriage-return segment - i.e.
    what a terminal would actually be showing once the overwrites are done -
    and drop the superseded ones. ANSI escapes are stripped and runs of blank
    lines are collapsed.
    """
    if not text:
        return ''

    text = _ANSI_RE.sub('', text)

    lines = []
    for raw_line in text.split('\n'):
        # Splitting on '\r' also handles CRLF endings and pure-progress lines.
        segments = [s for s in raw_line.split('\r') if s.strip()]
        lines.append(segments[-1].rstrip() if segments else '')

    # Collapse consecutive blank lines left behind by the removed progress spam.
    cleaned = []
    for line in lines:
        if not line and (not cleaned or not cleaned[-1]):
            continue
        cleaned.append(line)

    return '\n'.join(cleaned).strip()


def check_steamcmd():
    """
    Validates that SteamCMD exists and is being run by the correct user.
    """
    if not os.path.exists(STEAMCMD_BIN):
        return "Error: steamcmd.sh not found at " + STEAMCMD_BIN
    
    try:
        steamcmd_stat = os.stat(STEAMCMD_BIN)
        steamcmd_uid = steamcmd_stat.st_uid
        current_uid = os.getuid()
        
        if current_uid != steamcmd_uid:
            steamcmd_user = pwd.getpwuid(steamcmd_uid).pw_name
            current_user = pwd.getpwuid(current_uid).pw_name
            return f"Error: script is running as '{current_user}' but must run as '{steamcmd_user}'"
    except (OSError, KeyError) as e:
        return f"Error accessing file system or user database: {e}"
    
    return None

def app_info(appid):
    """Fetch app metadata using SteamCMD.

    Returns ``(data, None)`` on success or ``(None, error_message)`` on failure so
    callers can surface the reason instead of a bare False.
    """
    err = check_steamcmd()
    if err:
        print(err, file=sys.stderr)
        return None, err

    # Maybe delete the cache folder first
    # ~/Steam/appcache/

    # We call app_info_print twice. SteamCMD often requires a warm cache
    # to actually output the data to stdout.
    cmd = [
        STEAMCMD_BIN,
        "@ShutdownOnFailedCommand", "1",
        "@NoPromptForPassword", "1",
        "+login", "anonymous",
        "+app_info_update", "1",
        "+app_info_print", str(appid),
        "+app_info_print", str(appid),
        "+logoff",
        "+quit"
    ]

    try:
        # Do NOT use check=True: SteamCMD often exits non-zero even when it
        # printed usable output, so we parse stdout regardless of return code.
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return None, "SteamCMD timed out fetching app info"
    except Exception as e:
        print(e, file=sys.stderr)
        return None, f"SteamCMD could not be executed: {e}"

    stdout = process.stdout or ""

    # Find the start of the VDF block (e.g., "380870" { ... }).
    match = re.search(rf'"{appid}"\s*{{', stdout)
    if not match:
        tail = (process.stderr or stdout).strip()[-400:]
        return None, f"App {appid} info not found in SteamCMD output (rc={process.returncode}). {tail}"

    # Extract only the balanced { ... } block so SteamCMD's trailing output
    # (login messages, prompts) doesn't break the VDF parser.
    brace_start = stdout.index('{', match.start())
    depth = 0
    brace_end = None
    for i in range(brace_start, len(stdout)):
        if stdout[i] == '{':
            depth += 1
        elif stdout[i] == '}':
            depth -= 1
            if depth == 0:
                brace_end = i + 1
                break
    if brace_end is None:
        return None, "Malformed app info (unbalanced braces) from SteamCMD"

    vdf_block = f'"{appid}"\n{stdout[brace_start:brace_end]}'
    try:
        data = vdf.loads(vdf_block)
        return data.get(str(appid)), None
    except Exception as e:
        print(f"Failed to parse app info VDF: {e}", file=sys.stderr)
        print(f"{vdf_block}", file=sys.stderr)
        return None, f"Failed to parse app info VDF: {e}"

def app_update(appid, beta=None, install_dir="/opt/steam-apps/"):
    """Update or install a Steam app, validating files.

    Returns ``(ok, error_message, output)``. ``output`` is the captured SteamCMD
    console text with progress-line overwrites stripped (see
    :func:`clean_console_output`) so it is safe to persist on a task.
    """
    err = check_steamcmd()
    if err:
        return False, err, ''

    # Normalize path and ensure it exists
    install_dir = os.path.abspath(install_dir)
    try:
        os.makedirs(install_dir, exist_ok=True)
    except OSError as e:
        return False, f"Could not create directory {install_dir}: {e}", ''

    # Build update command
    update_params = ["+app_update", str(appid)]
    if beta:
        update_params.extend(["-beta", beta])
    update_params.append("validate")

    cmd = [
        STEAMCMD_BIN,
        "@ShutdownOnFailedCommand", "1",
        "@NoPromptForPassword", "1",
        "+force_install_dir", install_dir,
        "+login", "anonymous",
    ] + update_params + ["+quit"]

    '''
    try:
        # Stream output to the worker log so install progress is visible.
        subprocess.run(cmd, check=True)
        return True, None
    except subprocess.CalledProcessError as e:
        return False, f"SteamCMD update failed for AppID {appid} (rc={e.returncode})"
    except Exception as e:
        return False, f"SteamCMD could not be executed: {e}"
    '''
    try:
        # Capture output (combining stdout and stderr into a single string)
        result = subprocess.run(
            cmd, 
            check=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True
        )
        return True, None, clean_console_output(result.stdout)
    except subprocess.CalledProcessError as e:
        # e.output holds the captured string even if the command fails
        return False, f"SteamCMD update failed for AppID {appid} (rc={e.returncode})", clean_console_output(e.output)
    except Exception as e:
        return False, f"SteamCMD could not be executed: {e}", ""

if __name__ == "__main__":
    # Example usage:
    info, err = app_info(380870)  # Project Zomboid
    if info:
        print(f"Fetched info for: {info.get('common', {}).get('name')}", file=sys.stderr)
    else:
        print(f"app_info failed: {err}", file=sys.stderr)
    # Example update/install
    #ok, err = app_update(380870, beta="42.13.1", install_dir="/opt/steam-apps/")


def workshop_download(item_ids, install_dir="/opt/steam-apps/"):
    """Download or update Workshop items.

    Returns ``(ok, error_message, output)``, same shape as :func:`app_update`.

    All items go in one SteamCMD invocation on purpose: each run pays the login
    and startup cost, and a mod list of twenty would otherwise take minutes of
    pure overhead.
    """
    err = check_steamcmd()
    if err:
        return False, err, ''

    if not item_ids:
        return True, None, 'no Workshop items configured'

    install_dir = os.path.abspath(install_dir)
    try:
        os.makedirs(install_dir, exist_ok=True)
    except OSError as e:
        return False, f"Could not create directory {install_dir}: {e}", ''

    downloads = []
    for item in item_ids:
        # Defensive: these reach a command line. The caller validates too.
        if not str(item).isdigit():
            return False, f"'{item}' is not a Workshop item id", ''
        downloads.extend(["+workshop_download_item", WORKSHOP_APP_ID, str(item)])

    cmd = [
        STEAMCMD_BIN,
        "@ShutdownOnFailedCommand", "1",
        "@NoPromptForPassword", "1",
        "+force_install_dir", install_dir,
        "+login", "anonymous",
    ] + downloads + ["+quit"]

    try:
        result = subprocess.run(
            cmd, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=3600
        )
        return True, None, clean_console_output(result.stdout)
    except subprocess.TimeoutExpired:
        return False, 'SteamCMD timed out downloading Workshop items', ''
    except subprocess.CalledProcessError as e:
        return False, f"Workshop download failed (rc={e.returncode})", clean_console_output(e.output)
    except Exception as e:
        return False, f"SteamCMD could not be executed: {e}", ''


def manifest_path(appid, install_dir):
    """Where SteamCMD records what it installed for an app."""
    return os.path.join(os.path.abspath(install_dir), 'steamapps',
                        f'appmanifest_{appid}.acf')


def installed_app_state(appid, install_dir):
    """What is actually installed, read from Steam's own manifest.

    This is the local half of the "am I up to date?" question - `app_info`
    answers the remote half. Returns ``(state, error)``; ``state`` is None with
    no error when nothing is installed yet, which is a normal first-run answer
    rather than a failure.

    `buildid` is the field that matters: comparing it against the branch's
    buildid from `app_info` is the only reliable way to tell a current install
    from a stale one. Version strings on disk lie after a partial update.
    """
    path = manifest_path(appid, install_dir)
    if not os.path.isfile(path):
        return None, None

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            parsed = vdf.load(handle)
    except Exception as e:
        return None, f"Could not read {path}: {e}"

    app_state = parsed.get('AppState') if isinstance(parsed, dict) else None
    if not isinstance(app_state, dict):
        return None, f"{path} has no AppState block"

    def _int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # The branch is recorded per-config and is absent entirely on `public`,
    # which is why this reports None rather than guessing a name.
    beta = (app_state.get('UserConfig', {}) or {}).get('betakey') \
        or (app_state.get('MountedConfig', {}) or {}).get('betakey') \
        or None

    return {
        'appid': str(app_state.get('appid') or appid),
        'name': app_state.get('name'),
        'buildid': app_state.get('buildid'),
        'branch': beta,
        'install_dir': os.path.abspath(install_dir),
        'size_on_disk': _int(app_state.get('SizeOnDisk')),
        'last_updated': _int(app_state.get('LastUpdated')),
        # 4 means "fully installed"; anything else is mid-update or damaged.
        'state_flags': _int(app_state.get('StateFlags')),
    }, None
