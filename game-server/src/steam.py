#!/usr/bin/env python3
import os
import re
import sys
import pwd
import json
import subprocess

STEAMCMD_BIN = os.path.join(
    os.environ.get("STEAMCMDDIR", "/home/steam/steamcmd/"),
    "steamcmd.sh"
)


def check_steamcmd():
    # Check installation
    if not os.path.exists(STEAMCMD_BIN):
        return f"Error: steamcmd.sh not found"
    # Check permissions
    steamcmd_uid = os.stat(STEAMCMD_BIN).st_uid
    current_uid = os.getuid()
    if current_uid != steamcmd_uid:
        steamcmd_user = pwd.getpwuid(steamcmd_uid).pw_name
        current_user = pwd.getpwuid(current_uid).pw_name
        return f"Error: script is running as {current_user} and not as {steamcmd_user}"
    # No error
    return None


def app_info(appid):
    err = check_steamcmd()
    if err:
        print(err, file=sys.stderr)
        return None

    # Run +app_info_print
    cmd = [
        STEAMCMD_BIN,
        "@ShutdownOnFailedCommand", "1",
        "@NoPromptForPassword", "1",
        "+login", "anonymous",
        "+app_info_update", "1",
        "+app_info_print", str(appid),
        "+quit"
    ]

    # Execute and capture output
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()

    # Get data from response
    match = re.search(rf'"{appid}"\s+{{.*}}', stdout, re.DOTALL)
    if not match:
        return None

    output_text = match.group(0)
    json_str = re.sub(r'(".*?")\s+(".*?"|{)', r'\1: \2', output_text)
    json_str = re.sub(r'(".*?"|})\s+(".*?")', r'\1, \2', json_str)
    try:
        return json.loads(f"{{ {json_str} }}")[str(appid)]
    except json.JSONDecodeError as e:
        return None


def app_update(appid, beta=None, install_dir="/opt/steam-apps/"):
    err = check_steamcmd()
    if err:
        print(err, file=sys.stderr)
        return None

    # Ensure the installation directory exists
    try:
        if not os.path.exists(install_dir):
            os.makedirs(install_dir, exist_ok=True)
            try:
                stats = os.stat(STEAMCMD_BIN)
                os.chown(install_dir, stats.st_uid, stats.st_gid)
            except OSError as e:
                print(f"Warning: Could not set permissions for {install_dir}: {e}", file=sys.stderr)
    except OSError as e:
        print(f"Error: Could not create directory {install_dir}: {e}", file=sys.stderr)
        return False

    # Construct the command
    update_cmd = ["+app_update", str(appid)]
    if beta:
        update_cmd.extend(["-beta", beta])
    update_cmd.append("validate")

    # Construct the full command list
    cmd = [
        STEAMCMD_BIN,
        "@ShutdownOnFailedCommand", "1",
        "@NoPromptForPassword", "1",
        "+force_install_dir", install_dir,
        "+login", "anonymous",
        "+app_info_update", "1"
    ] + update_cmd + ["+quit"]

    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"\nError: SteamCMD exited with error code {e.returncode}", file=sys.stderr)
        return False

'''
if __name__ == "__main__":
    print("SteamCMD wrapper")
    appid = 380870
    beta = "42.13.1"

    # Usage
    print("Getting data")
    data = app_info(appid)
    print(json.dumps(data, indent=4))


    print("Installing app")
    app_update(appid, beta=beta, install_dir="/opt/steam-apps/")
'''
