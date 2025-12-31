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
    """
    Fetches app metadata using SteamCMD and parses it via the vdf library.
    """
    err = check_steamcmd()
    if err:
        print(err, file=sys.stderr)
        return None

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
        process = subprocess.run(cmd, capture_output=True, text=True, check=True)
        stdout = process.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error: SteamCMD failed with return code {e.returncode}", file=sys.stderr)
        return None

    # Find the start of the VDF block (e.g., "123456" { ... })
    match = re.search(rf'"{appid}"\s*{{', stdout, re.DOTALL)
    if not match:
        print(f"Error: Could not find app {appid} info in SteamCMD output.", file=sys.stderr)
        return None

    # Extract the string starting from the match
    vdf_content = stdout[match.start():]
    
    try:
        # Use the official Valve Data Format parser
        data = vdf.loads(vdf_content)
        return data.get(str(appid))
    except Exception as e:
        print(f"Error: Failed to parse VDF data: {e}", file=sys.stderr)
        return None

def app_update(appid, beta=None, install_dir="/opt/steam-apps/"):
    """
    Updates or Installs a Steam app. 
    Handles directory creation and validation.
    """
    err = check_steamcmd()
    if err:
        print(err, file=sys.stderr)
        return False

    # Normalize path and ensure it exists
    install_dir = os.path.abspath(install_dir)
    try:
        os.makedirs(install_dir, exist_ok=True)
    except OSError as e:
        print(f"Error: Could not create directory {install_dir}: {e}", file=sys.stderr)
        return False

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

    try:
        # We don't capture_output here so the user can see progress in the terminal
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error: Update failed for AppID {appid}. Code: {e.returncode}", file=sys.stderr)
        return False

if __name__ == "__main__":
    # Example usage:
    info = app_info(380870) # Project Zomboid
    if info:
        print(f"Fetched info for: {info.get('common', {}).get('name')}")
    # Example update/install
    # success = app_update(380870, beta="42.13.1", install_dir="/opt/steam-apps/")
