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
