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

    Returns ``(True, None)`` on success or ``(False, error_message)`` on failure.
    """
    err = check_steamcmd()
    if err:
        return False, err

    # Normalize path and ensure it exists
    install_dir = os.path.abspath(install_dir)
    try:
        os.makedirs(install_dir, exist_ok=True)
    except OSError as e:
        return False, f"Could not create directory {install_dir}: {e}"

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
        return True, None, result.stdout
    except subprocess.CalledProcessError as e:
        # e.output holds the captured string even if the command fails
        return False, f"SteamCMD update failed for AppID {appid} (rc={e.returncode})", e.output
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
