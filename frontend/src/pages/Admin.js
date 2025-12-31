// Admin panel page
import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';

function Admin() {
  const { token, isAdmin, isModerator } = useAuth();
  const [activeTab, setActiveTab] = useState('servers');
  const [users, setUsers] = useState([]);
  const [servers, setServers] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isModerator()) {
      return;
    }
    loadData();
  }, [activeTab]);

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      if (activeTab === 'users') {
        const data = await api.admin.users.getAll(token);
        if (data.users) setUsers(data.users);
      } else if (activeTab === 'servers') {
        const data = await api.admin.servers.getAll(token);
        if (data.servers) setServers(data.servers);
      } else if (activeTab === 'tasks') {
        const data = await api.admin.tasks.getAll(token);
        if (data.tasks) setTasks(data.tasks);
      }
    } catch (err) {
      console.error('Load data error:', err);
      setError('Failed to load data');
    }
    setLoading(false);
  };

  const handleRoleUpdate = async (userId, newRole) => {
    try {
      await api.admin.users.updateRole(token, userId, newRole);
      loadData();
    } catch (err) {
      console.error('Update role error:', err);
      setError('Failed to update user role');
    }
  };

  const getRoleBadge = (role) => {
    const roleMap = {
      'admin': 'danger',
      'moderator': 'warning',
      'player': 'info',
      'banned': 'secondary'
    };
    return roleMap[role] || 'secondary';
  };

  const getStatusBadge = (status) => {
    const statusMap = {
      'online': 'success',
      'offline': 'secondary',
      'pending': 'warning',
      'processing': 'info',
      'completed': 'success'
    };
    return statusMap[status?.toLowerCase()] || 'secondary';
  };

  if (!isModerator()) {
    return (
      <section className="py-5" style={{ minHeight: '50vh' }}>
        <div className="container text-center">
          <h2>Access Denied</h2>
          <p className="small-muted">You do not have permission to access the admin panel.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="py-5" style={{ minHeight: '50vh' }}>
      <div className="container">
        <h2 className="mb-4" style={{ fontFamily: "'Oswald', sans-serif", letterSpacing: '0.6px' }}>
          ADMIN PANEL
        </h2>

        {/* Tabs */}
        <ul className="nav nav-tabs mb-4">
          <li className="nav-item">
            <button 
              className={`nav-link ${activeTab === 'servers' ? 'active' : ''}`}
              onClick={() => setActiveTab('servers')}
            >
              Servers
            </button>
          </li>
          <li className="nav-item">
            <button 
              className={`nav-link ${activeTab === 'tasks' ? 'active' : ''}`}
              onClick={() => setActiveTab('tasks')}
            >
              Tasks
            </button>
          </li>
          {isAdmin() && (
            <li className="nav-item">
              <button 
                className={`nav-link ${activeTab === 'users' ? 'active' : ''}`}
                onClick={() => setActiveTab('users')}
              >
                Users
              </button>
            </li>
          )}
        </ul>

        {error && (
          <div className="alert alert-danger" role="alert">
            {error}
          </div>
        )}

        {loading ? (
          <div className="text-center py-5">
            <div className="spinner-border text-light" role="status">
              <span className="visually-hidden">Loading...</span>
            </div>
          </div>
        ) : (
          <>
            {/* Servers Tab */}
            {activeTab === 'servers' && (
              <div className="table-responsive">
                <table className="table table-dark table-striped">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Host</th>
                      <th>Port</th>
                      <th>Status</th>
                      <th>Players</th>
                      <th>Game Day</th>
                    </tr>
                  </thead>
                  <tbody>
                    {servers.length === 0 ? (
                      <tr>
                        <td colSpan="6" className="text-center">No servers found</td>
                      </tr>
                    ) : (
                      servers.map((server) => (
                        <tr key={server.id}>
                          <td>{server.name}</td>
                          <td>{server.host}</td>
                          <td>{server.port}</td>
                          <td>
                            <span className={`badge bg-${getStatusBadge(server.status)}`}>
                              {server.status}
                            </span>
                          </td>
                          <td>{server.active_players} / {server.max_players}</td>
                          <td>{server.game_day}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {/* Tasks Tab */}
            {activeTab === 'tasks' && (
              <div className="table-responsive">
                <table className="table table-dark table-striped">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Action</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tasks.length === 0 ? (
                      <tr>
                        <td colSpan="5" className="text-center">No tasks found</td>
                      </tr>
                    ) : (
                      tasks.map((task) => (
                        <tr key={task.id}>
                          <td>{task.id}</td>
                          <td>{task.action}</td>
                          <td>
                            <span className={`badge bg-${getStatusBadge(task.status)}`}>
                              {task.status}
                            </span>
                          </td>
                          <td>{task.created_at ? new Date(task.created_at).toLocaleString() : 'N/A'}</td>
                          <td>{task.updated_at ? new Date(task.updated_at).toLocaleString() : 'N/A'}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {/* Users Tab (Admin only) */}
            {activeTab === 'users' && isAdmin() && (
              <div className="table-responsive">
                <table className="table table-dark table-striped">
                  <thead>
                    <tr>
                      <th>Username</th>
                      <th>Email</th>
                      <th>Role</th>
                      <th>Created</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.length === 0 ? (
                      <tr>
                        <td colSpan="5" className="text-center">No users found</td>
                      </tr>
                    ) : (
                      users.map((user) => (
                        <tr key={user.id}>
                          <td>{user.username}</td>
                          <td>{user.email}</td>
                          <td>
                            <span className={`badge bg-${getRoleBadge(user.role)}`}>
                              {user.role}
                            </span>
                          </td>
                          <td>{user.created_at ? new Date(user.created_at).toLocaleDateString() : 'N/A'}</td>
                          <td>
                            <select
                              className="form-select form-select-sm"
                              value={user.role}
                              onChange={(e) => handleRoleUpdate(user.id, e.target.value)}
                              style={{ width: 'auto' }}
                            >
                              <option value="player">Player</option>
                              <option value="moderator">Moderator</option>
                              <option value="admin">Admin</option>
                              <option value="banned">Banned</option>
                            </select>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

export default Admin;
