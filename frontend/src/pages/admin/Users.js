// Admin › Users: view accounts and change roles (admin only).
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { getRoleBadge, Spinner } from './helpers';

function Users() {
  const { token, isAdmin } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isAdmin()) return;
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api.admin.users.getAll(token);
      if (data.users) setUsers(data.users);
    } catch (err) {
      console.error('Load users error:', err);
      setError('Failed to load users');
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

  if (!isAdmin()) {
    return (
      <div className="text-center py-5">
        <h4>Access Denied</h4>
        <p className="text-body-secondary">Only administrators can manage users.</p>
      </div>
    );
  }

  return (
    <>
      <h4 className="font-display mb-3">Users</h4>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}

      {loading ? <Spinner /> : (
        <div className="table-responsive">
          <table className="table table-dark table-striped align-middle">
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
                      <span className={`badge text-bg-${getRoleBadge(user.role)}`}>
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
  );
}

export default Users;
