// API service for backend communication
const API_URL = process.env.REACT_APP_API_URL || '';

// Helper function to handle API responses
const handleResponse = async (response) => {
  // An error response is not always JSON: a 502 from nginx while the backend
  // is still warming, or a rate-limit page, arrives as HTML. Parsing must not
  // throw over that and lose the status the caller needs to react to.
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || 'Request failed');
    error.status = response.status;
    throw error;
  }
  return data;
};

export const api = {
  // Service version and the state of what the API depends on. Public, and
  // deliberately cheap - the admin footer asks for it on every page.
  health: async () => {
    const response = await fetch(`${API_URL}/health`);
    return handleResponse(response);
  },

  // Branding, social links and the legal pages. Public: the site is rendered
  // from this before anyone signs in.
  site: {
    get: async () => {
      const response = await fetch(`${API_URL}/api/site`);
      return handleResponse(response);
    },
    page: async (slug) => {
      const response = await fetch(`${API_URL}/api/site/pages/${slug}`);
      return handleResponse(response);
    }
  },

  // Auth endpoints
  auth: {
    signin: async (username, password) => {
      const response = await fetch(`${API_URL}/api/auth/signin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      return handleResponse(response);
    },
    // `extra` carries whatever gate is configured: a shared registration
    // password, an invite code, or neither.
    signup: async (username, email, password, extra = {}) => {
      const response = await fetch(`${API_URL}/api/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, email, password, ...extra })
      });
      return handleResponse(response);
    },
    // What the sign-up form should ask for, before anyone types anything.
    registrationStatus: async () => {
      const response = await fetch(`${API_URL}/api/auth/registration`);
      return handleResponse(response);
    },
    // Returns { enabled, id, image } — image is raw SVG markup.
    captcha: async () => {
      const response = await fetch(`${API_URL}/api/auth/captcha`);
      return handleResponse(response);
    },
    // Second step of a sign-in that returned { mfa_required, mfa_token }: the
    // challenge token plus a current authenticator code, in exchange for the
    // real session token.
    signinVerify2fa: async (mfaToken, code) => {
      const response = await fetch(`${API_URL}/api/auth/signin/2fa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mfa_token: mfaToken, code })
      });
      return handleResponse(response);
    },
    me: async (token) => {
      const response = await fetch(`${API_URL}/api/auth/me`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    // Two-factor auth. setup mints a secret and returns the otpauth URI to turn
    // into a QR; enable confirms a code to switch it on; disable needs the
    // password and a current code together.
    twofa: {
      setup: async (token, password) => {
        const response = await fetch(`${API_URL}/api/auth/2fa/setup`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ password })
        });
        return handleResponse(response);
      },
      enable: async (token, code) => {
        const response = await fetch(`${API_URL}/api/auth/2fa/enable`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ code })
        });
        return handleResponse(response);
      },
      disable: async (token, password, code) => {
        const response = await fetch(`${API_URL}/api/auth/2fa/disable`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ password, code })
        });
        return handleResponse(response);
      }
    },
    changePassword: async (token, currentPassword, newPassword) => {
      const response = await fetch(`${API_URL}/api/auth/password`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
      });
      return handleResponse(response);
    },
    forgotPassword: async (email) => {
      const response = await fetch(`${API_URL}/api/auth/password/forgot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
      return handleResponse(response);
    },
    // `clearTwoFactor` also strips 2FA as part of the reset — the recovery path
    // for a lost authenticator. Off by default, so an ordinary reset keeps it.
    resetPassword: async (resetToken, newPassword, clearTwoFactor = false) => {
      const response = await fetch(`${API_URL}/api/auth/password/reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: resetToken, new_password: newPassword, clear_2fa: clearTwoFactor })
      });
      return handleResponse(response);
    },
    verifyEmail: async (verifyToken) => {
      const response = await fetch(`${API_URL}/api/auth/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: verifyToken })
      });
      return handleResponse(response);
    },
    requestVerification: async (token) => {
      const response = await fetch(`${API_URL}/api/auth/verify/request`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    changeEmail: async (token, password, email) => {
      const response = await fetch(`${API_URL}/api/auth/email`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ password, email })
      });
      return handleResponse(response);
    },
    logoutEverywhere: async (token) => {
      const response = await fetch(`${API_URL}/api/auth/logout-all`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    exportAccount: async (token) => {
      const response = await fetch(`${API_URL}/api/auth/export`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    deleteAccount: async (token, password) => {
      const response = await fetch(`${API_URL}/api/auth/me`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ password })
      });
      return handleResponse(response);
    }
  },

  reports: {
    // Reachable while banned — an appeal process a banned person cannot reach
    // is not an appeal process.
    listMine: async (token) => {
      const response = await fetch(`${API_URL}/api/reports`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    create: async (token, data) => {
      const response = await fetch(`${API_URL}/api/reports`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(data)
      });
      return handleResponse(response);
    }
  },

  notifications: {
    list: async (token, params = '') => {
      const response = await fetch(`${API_URL}/api/notifications${params}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    // Just the badge number — polled, so it stays cheap.
    unreadCount: async (token) => {
      const response = await fetch(`${API_URL}/api/notifications/unread-count`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    markRead: async (token, id) => {
      const response = await fetch(`${API_URL}/api/notifications/${id}/read`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    // Reading and removing are different acts, so removal is its own call.
    remove: async (token, id) => {
      const response = await fetch(`${API_URL}/api/notifications/${id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    // Clears read ones only: an unread notification is news nobody has seen.
    clearRead: async (token) => {
      const response = await fetch(`${API_URL}/api/notifications/read`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    markAllRead: async (token) => {
      const response = await fetch(`${API_URL}/api/notifications/read-all`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    }
  },

  invitations: {
    list: async (token) => {
      const response = await fetch(`${API_URL}/api/invitations`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    // The code comes back exactly once, in this response.
    create: async (token, data) => {
      const response = await fetch(`${API_URL}/api/invitations`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(data)
      });
      return handleResponse(response);
    },
    revoke: async (token, id) => {
      const response = await fetch(`${API_URL}/api/invitations/${id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    }
  },

  // Character endpoints
  characters: {
    getAll: async (token) => {
      const response = await fetch(`${API_URL}/api/characters`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    get: async (token, id) => {
      const response = await fetch(`${API_URL}/api/characters/${id}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    // No create: characters come only from an approved claim request.
    update: async (token, id, data) => {
      const response = await fetch(`${API_URL}/api/characters/${id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(data)
      });
      return handleResponse(response);
    },
    // Releases the in-game identity: it becomes claimable by anyone again.
    unlink: async (token, id) => {
      const response = await fetch(`${API_URL}/api/characters/${id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    }
  },

  // Server endpoints
  servers: {
    // Public, but the connection details (hostname, ports) come back only when
    // a token is sent - so pass one if the visitor is signed in.
    getAll: async (token) => {
      const response = await fetch(`${API_URL}/api/servers`, {
        headers: token ? { 'Authorization': `Bearer ${token}` } : {}
      });
      return handleResponse(response);
    },
    getStatus: async (token) => {
      const response = await fetch(`${API_URL}/api/servers/status`, {
        headers: token ? { 'Authorization': `Bearer ${token}` } : {}
      });
      return handleResponse(response);
    },
    // Online-player history for the activity chart (public). Defaults to 24h.
    getHistory: async (serverId, hours = 24) => {
      const response = await fetch(`${API_URL}/api/servers/${serverId}/history?hours=${hours}`);
      return handleResponse(response);
    },
    // In-game usernames currently online on a server (auth required).
    getOnline: async (token, serverId) => {
      const response = await fetch(`${API_URL}/api/servers/${serverId}/online`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    }
  },

  // Loot box endpoints
  boxes: {
    // Public: what each box can contain and how likely each reward is.
    odds: async () => {
      const response = await fetch(`${API_URL}/api/boxes/odds`);
      return handleResponse(response);
    },
    // This week's collected days and what they are worth. The weekly bonus
    // was always paid and never shown.
    streak: async (token) => {
      const response = await fetch(`${API_URL}/api/boxes/streak`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    claimDaily: async (token) => {
      const response = await fetch(`${API_URL}/api/boxes/daily`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    list: async (token) => {
      const response = await fetch(`${API_URL}/api/boxes`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    open: async (token, id) => {
      const response = await fetch(`${API_URL}/api/boxes/${id}/open`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    }
  },

  // Inventory endpoints
  inventory: {
    history: async (token) => {
      const response = await fetch(`${API_URL}/api/inventory/history`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    list: async (token) => {
      const response = await fetch(`${API_URL}/api/inventory`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    send: async (token, id, characterId) => {
      const response = await fetch(`${API_URL}/api/inventory/${id}/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ character_id: characterId })
      });
      return handleResponse(response);
    }
  },

  // Claim request endpoints (account ↔ in-game character linking)
  claims: {
    getMine: async (token) => {
      const response = await fetch(`${API_URL}/api/claims`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    create: async (token, data) => {
      const response = await fetch(`${API_URL}/api/claims`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(data)
      });
      return handleResponse(response);
    }
  },

  // Admin endpoints
  admin: {
    users: {
      getAll: async (token, role) => {
        const url = role ? `${API_URL}/api/admin/users?role=${role}` : `${API_URL}/api/admin/users`;
        const response = await fetch(url, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // `extra` carries a ban's reason and duration_days when banning.
      updateRole: async (token, userId, role, extra = {}) => {
        const response = await fetch(`${API_URL}/api/admin/users/${userId}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ role, ...extra })
        });
        return handleResponse(response);
      },
      bans: async (token, userId) => {
        const response = await fetch(`${API_URL}/api/admin/users/${userId}/bans`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Mails a one-time link; the admin never learns the user's password.
      resetPassword: async (token, userId) => {
        const response = await fetch(`${API_URL}/api/admin/users/${userId}/reset-password`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Clears a user's 2FA so a lost-authenticator lockout has a way back in.
      disable2fa: async (token, userId) => {
        const response = await fetch(`${API_URL}/api/admin/users/${userId}/disable-2fa`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      }
    },
    jobs: {
      getAll: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/jobs`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      update: async (token, id, data) => {
        const response = await fetch(`${API_URL}/api/admin/jobs/${id}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(data)
        });
        return handleResponse(response);
      },
      // Moves the next run forward; the scheduler picks it up on its next tick.
      run: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/jobs/${id}/run`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      }
    },
    reports: {
      getAll: async (token, params = '') => {
        const response = await fetch(`${API_URL}/api/admin/reports${params}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      resolve: async (token, id, status, resolution) => {
        const response = await fetch(`${API_URL}/api/admin/reports/${id}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ status, resolution })
        });
        return handleResponse(response);
      }
    },
    // Staff alerts: the event catalog, and the channels events are routed to
    // (Discord webhooks, the staff inbox, ops mail). A webhook's URL never
    // comes back in full — only masked — so an edit that leaves the target
    // blank means "keep the one you have".
    alerts: {
      getAll: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/alerts`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      create: async (token, data) => {
        const response = await fetch(`${API_URL}/api/admin/alerts/channels`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(data)
        });
        return handleResponse(response);
      },
      update: async (token, id, data) => {
        const response = await fetch(`${API_URL}/api/admin/alerts/channels/${id}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(data)
        });
        return handleResponse(response);
      },
      remove: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/alerts/channels/${id}`, {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Sends a sample message and waits for the outcome, so a wrong URL or a
      // mail server that refuses is reported here rather than discovered the
      // next time something happens.
      test: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/alerts/channels/${id}/test`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      }
    },
    settings: {
      getAll: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/settings`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Mails the caller's own address, so a wrong SMTP password is found in
      // ten seconds rather than the next time somebody needs a reset link.
      testMail: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/settings/test-mail`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      update: async (token, values) => {
        const response = await fetch(`${API_URL}/api/admin/settings`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(values)
        });
        return handleResponse(response);
      }
    },
    servers: {
      getAll: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/servers`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      get: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      create: async (token, data) => {
        const response = await fetch(`${API_URL}/api/admin/servers`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(data)
        });
        return handleResponse(response);
      },
      update: async (token, id, data) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(data)
        });
        return handleResponse(response);
      },
      delete: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}`, {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Every key in the file, including commented-out ones. Admin only.
      configRaw: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/config/raw`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      saveConfigRaw: async (token, id, changes, version) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/config/raw`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ changes, version })
        });
        return handleResponse(response);
      },
      // Build a portable template from this server's config (ports, credentials
      // and identity filtered out server-side). Returns the JSON to download.
      exportConfigTemplate: async (token, id, name, description) => {
        const params = new URLSearchParams({ name: name || '', description: description || '' });
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/config/template/export?${params}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Apply a combined template (INI settings and/or SandboxVars) to this
      // server, in one call. `body` is { settings?, sandbox?, version?,
      // sandbox_version? }. Refused unless the server is off.
      importConfigTemplate: async (token, id, body) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/config/template/import`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(body)
        });
        return handleResponse(response);
      },
      // The gameplay-difficulty settings (SandboxVars.lua), separate from the
      // .ini above: water/power shutoff, loot, zombie count, stats decay.
      sandbox: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/config/sandbox`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      saveSandbox: async (token, id, changes, version) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/config/sandbox`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ changes, version })
        });
        return handleResponse(response);
      },
      config: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/config`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      saveConfig: async (token, id, values) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/config`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(values)
        });
        return handleResponse(response);
      },
      // Which mods this server loads, against what is downloaded. The two
      // lists are saved together because they are two halves of one decision:
      // the Workshop ids say what to download, the mod names say what to load.
      mods: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/mods`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      saveMods: async (token, id, workshopIds, modNames) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/mods`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ workshop_ids: workshopIds, mod_names: modNames })
        });
        return handleResponse(response);
      },
      // Queued: SteamCMD takes as long as it takes.
      downloadMods: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/mods/update`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      backups: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/backups`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Both are queued, not run inline: archiving a world takes as long as it
      // takes, and a request that waited would time out in the browser.
      backup: async (token, id, note) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/backups`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ note })
        });
        return handleResponse(response);
      },
      restore: async (token, id, backup) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/restore`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ backup })
        });
        return handleResponse(response);
      },
      // Fetch the archive as a blob so the Authorization header can be sent —
      // a plain <a href> download cannot carry one.
      downloadBackup: async (token, id, name) => {
        const response = await fetch(
          `${API_URL}/api/admin/servers/${id}/backups/${encodeURIComponent(name)}/download`,
          { headers: { 'Authorization': `Bearer ${token}` } }
        );
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          const error = new Error(data.error || 'Could not download the backup');
          error.status = response.status;
          throw error;
        }
        return response.blob();
      },
      deleteBackup: async (token, id, name) => {
        const response = await fetch(
          `${API_URL}/api/admin/servers/${id}/backups/${encodeURIComponent(name)}`,
          { method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` } }
        );
        return handleResponse(response);
      },
      // multipart: the archive rides in a FormData field, not JSON.
      uploadBackup: async (token, id, file) => {
        const body = new FormData();
        body.append('file', file);
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/backups/upload`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` },
          body
        });
        return handleResponse(response);
      },
      // Tail a server's log. The manager already holds the file open to build
      // the online roster; this just surfaces it.
      logs: async (token, id, lines = 200) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/logs?lines=${lines}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Lifecycle control: action is one of 'start' | 'stop' | 'sleep'.
      control: async (token, id, action) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/${action}`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Send a console command to a running server.
      command: async (token, id, command) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}/command`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ command })
        });
        return handleResponse(response);
      }
    },
    // Whitelisted console actions this staff member may run.
    // droppableOnly limits the list to actions that may back a player reward.
    actions: {
      getAll: async (token, droppableOnly) => {
        const url = droppableOnly
          ? `${API_URL}/api/admin/actions?droppable=1`
          : `${API_URL}/api/admin/actions`;
        const response = await fetch(url, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      }
    },
    give: async (token, data) => {
      const response = await fetch(`${API_URL}/api/admin/give`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(data)
      });
      return handleResponse(response);
    },
    rewards: {
      getAll: async (token, kind) => {
        const url = kind ? `${API_URL}/api/admin/rewards?kind=${kind}` : `${API_URL}/api/admin/rewards`;
        const response = await fetch(url, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      create: async (token, data) => {
        const response = await fetch(`${API_URL}/api/admin/rewards`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(data)
        });
        return handleResponse(response);
      },
      update: async (token, id, data) => {
        const response = await fetch(`${API_URL}/api/admin/rewards/${id}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(data)
        });
        return handleResponse(response);
      },
      delete: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/rewards/${id}`, {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      }
    },
    boxPools: {
      getAll: async (token, size) => {
        const url = size ? `${API_URL}/api/admin/box-pools?size=${size}` : `${API_URL}/api/admin/box-pools`;
        const response = await fetch(url, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      add: async (token, data) => {
        const response = await fetch(`${API_URL}/api/admin/box-pools`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(data)
        });
        return handleResponse(response);
      },
      remove: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/box-pools/${id}`, {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Relative drop weight within the pool, not a percentage.
      setWeight: async (token, id, weight) => {
        const response = await fetch(`${API_URL}/api/admin/box-pools/${id}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ weight })
        });
        return handleResponse(response);
      }
    },
    boxTypes: {
      getAll: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/box-types`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      update: async (token, size, data) => {
        const response = await fetch(`${API_URL}/api/admin/box-types/${size}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(data)
        });
        return handleResponse(response);
      }
    },
    // Community loot-box configs: browse the GitHub list, preview one, and
    // apply it to a size's pool. Import also accepts a config parsed from a
    // local file — the backend validates either source the same way.
    rewardBoxes: {
      list: async (token, refresh) => {
        const url = refresh
          ? `${API_URL}/api/admin/reward-boxes?refresh=1`
          : `${API_URL}/api/admin/reward-boxes`;
        const response = await fetch(url, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      get: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/reward-boxes/${id}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      import: async (token, data) => {
        const response = await fetch(`${API_URL}/api/admin/reward-boxes/import`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(data)
        });
        return handleResponse(response);
      },
      // Returns the config JSON for the caller to download.
      export: async (token, { size, name, description }) => {
        const params = new URLSearchParams({ size, name: name || '', description: description || '' });
        const response = await fetch(`${API_URL}/api/admin/reward-boxes/export?${params}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      }
    },
    // Community server-config templates: curated INI presets published on GitHub,
    // fetched by the game-server (the only service with egress) and proxied here.
    serverTemplates: {
      list: async (token, refresh) => {
        const url = refresh
          ? `${API_URL}/api/admin/server-templates?refresh=1`
          : `${API_URL}/api/admin/server-templates`;
        const response = await fetch(url, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      get: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/server-templates/${id}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      }
    },
    audit: {
      getAll: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/audit`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // `olderThanDays` keeps the last N days and deletes what precedes them;
      // omit it to clear the log entirely. Admin only.
      clear: async (token, olderThanDays) => {
        const query = olderThanDays ? `?older_than_days=${olderThanDays}` : '';
        const response = await fetch(`${API_URL}/api/admin/audit${query}`, {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      }
    },
    claims: {
      getAll: async (token, status) => {
        const url = status ? `${API_URL}/api/admin/claims?status=${status}` : `${API_URL}/api/admin/claims`;
        const response = await fetch(url, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Claims are approved automatically on the online check; revoking is the
      // staff lever. It releases the in-game name for anyone to claim again.
      revoke: async (token, id, reason) => {
        const response = await fetch(`${API_URL}/api/admin/claims/${id}/revoke`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ reason })
        });
        return handleResponse(response);
      }
    },
    // The in-game item catalog behind the reward item picker. Reference data,
    // fetched once per page and cached by the caller.
    items: {
      getAll: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/items`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      refresh: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/items/refresh`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      }
    },
    // The shared SteamCMD install and its Workshop content. Host state: one
    // install directory serves every server, so none of this takes a server id.
    installation: {
      get: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/installation`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Both queue a task and return immediately; watch it on Tasks.
      // `beta` is only sent when a branch was actually chosen - omitting it
      // means "the configured branch", which is not the same as public.
      update: async (token, beta) => {
        const response = await fetch(`${API_URL}/api/admin/installation/update`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(beta === undefined ? {} : { beta })
        });
        return handleResponse(response);
      },
      appInfo: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/installation/app-info`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      }
    },
    mods: {
      getAll: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/mods`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // What some pasted ids or URLs actually refer to. Nothing is queued -
      // this is the "is that really the mod you meant" step before a download
      // that takes minutes.
      preview: async (token, items) => {
        const response = await fetch(`${API_URL}/api/admin/mods/preview`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ items })
        });
        return handleResponse(response);
      },
      // `items` are Workshop ids or Workshop page URLs; the manager resolves them.
      install: async (token, items) => {
        const response = await fetch(`${API_URL}/api/admin/mods`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ items })
        });
        return handleResponse(response);
      },
      remove: async (token, itemId) => {
        const response = await fetch(`${API_URL}/api/admin/mods/${itemId}`, {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Collections installed from, each carrying the order its author chose.
      // That order is the whole point of the record.
      collections: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/mods/collections`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      forgetCollection: async (token, collectionId) => {
        const response = await fetch(`${API_URL}/api/admin/mods/collections/${collectionId}`, {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      }
    },
    tasks: {
      getAll: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/tasks`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      create: async (token, data) => {
        const response = await fetch(`${API_URL}/api/admin/tasks`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(data)
        });
        return handleResponse(response);
      },
      get: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/tasks/${id}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      // Only pending or completed tasks can be removed; the worker owns the rest.
      remove: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/tasks/${id}`, {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      clear: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/tasks`, {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      }
    }
  }
};

export default api;
