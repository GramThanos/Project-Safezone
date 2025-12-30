#!/usr/bin/env python3
# Actions run module

import config
import steam


def update_server(data):
    res = steam.app_update(config.STEAM_APP_ID, beta=config.STEAM_APP_BETA, install_dir=config.STEAM_INSTALL_DIR)
    return True if res else False

def get_app_info(data):
    info = steam.app_info(config.STEAM_APP_ID)
    if not info:
        return False
    data['data'] = info
    return True

ACTIONS = {
    'update_server': update_server,
    'get_app_info': get_app_info,
}
