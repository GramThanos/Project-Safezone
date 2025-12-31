// API service for backend communication
const API_URL = process.env.REACT_APP_API_URL || '';

export const api = {
  // Auth endpoints
  auth: {
    signin: async (username, password) => {
      const response = await fetch(`${API_URL}/api/auth/signin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      return response.json();
    },
    signup: async (username, email, password) => {
      const response = await fetch(`${API_URL}/api/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, email, password })
      });
      return response.json();
    },
    me: async (token) => {
      const response = await fetch(`${API_URL}/api/auth/me`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return response.json();
    }
  },

  // Player endpoints
  players: {
    getAll: async (token) => {
      const response = await fetch(`${API_URL}/api/players`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return response.json();
    },
    get: async (token, id) => {
      const response = await fetch(`${API_URL}/api/players/${id}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return response.json();
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
      return response.json();
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
      return response.json();
    },
    delete: async (token, id) => {
      const response = await fetch(`${API_URL}/api/players/${id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      return response.json();
    }
  },

  // Server endpoints
  servers: {
    getAll: async () => {
      const response = await fetch(`${API_URL}/api/servers`);
      return response.json();
    },
    getStatus: async () => {
      const response = await fetch(`${API_URL}/api/servers/status`);
      return response.json();
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
        return response.json();
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
        return response.json();
      }
    },
    servers: {
      getAll: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/servers`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
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
        return response.json();
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
        return response.json();
      },
      delete: async (token, id) => {
        const response = await fetch(`${API_URL}/api/admin/servers/${id}`, {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
      }
    },
    tasks: {
      getAll: async (token) => {
        const response = await fetch(`${API_URL}/api/admin/tasks`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.json();
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
        return response.json();
      }
    }
  }
};

export default api;
