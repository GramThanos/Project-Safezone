// API service for backend communication
const API_URL = process.env.REACT_APP_API_URL || '';

// Helper function to handle API responses
const handleResponse = async (response) => {
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || 'Request failed');
  }
  return data;
};

export const api = {
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
    signup: async (username, email, password) => {
      const response = await fetch(`${API_URL}/api/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, email, password })
      });
      return handleResponse(response);
    },
    me: async (token) => {
      const response = await fetch(`${API_URL}/api/auth/me`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
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
    }
  },

  // Player endpoints
  players: {
    getAll: async (token) => {
      const response = await fetch(`${API_URL}/api/players`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    get: async (token, id) => {
      const response = await fetch(`${API_URL}/api/players/${id}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    create: async (token, data) => {
      const response = await fetch(`${API_URL}/api/players`, {
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
      const response = await fetch(`${API_URL}/api/players/${id}`, {
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
      const response = await fetch(`${API_URL}/api/players/${id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    }
  },

  // Server endpoints
  servers: {
    getAll: async () => {
      const response = await fetch(`${API_URL}/api/servers`);
      return handleResponse(response);
    },
    getStatus: async () => {
      const response = await fetch(`${API_URL}/api/servers/status`);
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
    list: async (token) => {
      const response = await fetch(`${API_URL}/api/inventory`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return handleResponse(response);
    },
    send: async (token, id, playerId) => {
      const response = await fetch(`${API_URL}/api/inventory/${id}/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ player_id: playerId })
      });
      return handleResponse(response);
    }
  },

  // Claim request endpoints (account ↔ in-game player linking)
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
      updateRole: async (token, userId, role) => {
        const response = await fetch(`${API_URL}/api/admin/users/${userId}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ role })
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
      delete: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/box-pools/${id}`, {
          method: 'DELETE',
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
      approve: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/claims/${id}/approve`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return handleResponse(response);
      },
      reject: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/claims/${id}/reject`, {
          method: 'POST',
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
      }
    }
  }
};

export default api;
