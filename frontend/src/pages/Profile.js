// Profile page
import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';

function Profile() {
  const { user, token } = useAuth();
  const [form, setForm] = useState({ current: '', next: '', confirm: '' });
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');

  const getRoleBadge = (role) => {
    const roleMap = {
      'admin': 'danger',
      'moderator': 'warning',
      'player': 'info',
      'banned': 'secondary'
    };
    return roleMap[role] || 'secondary';
  };

  const handleChangePassword = async (e) => {
    e.preventDefault();
    setMsg('');
    setError('');
    if (!form.current || !form.next) {
      setError('Enter your current and new password');
      return;
    }
    if (form.next.length < 8) {
      setError('New password must be at least 8 characters');
      return;
    }
    if (form.next !== form.confirm) {
      setError('New password and confirmation do not match');
      return;
    }
    try {
      await api.auth.changePassword(token, form.current, form.next);
      setForm({ current: '', next: '', confirm: '' });
      setMsg('Password updated successfully.');
    } catch (err) {
      console.error('Change password error:', err);
      setError(err.message || 'Failed to change password');
    }
  };

  return (
    <section className="py-5" style={{ minHeight: '50vh' }}>
      <div className="container">
        <div className="row justify-content-center">
          <div className="col-md-8 col-lg-6">
            <div className="card">
              <div className="card-body p-4">
              <h2 className="card-title font-display text-center mb-4">User Profile</h2>

              <div className="mb-3">
                <label className="text-body-secondary">Username</label>
                <div className="h5">{user?.username}</div>
              </div>

              <div className="mb-3">
                <label className="text-body-secondary">Email</label>
                <div className="h5">{user?.email}</div>
              </div>

              <div className="mb-3">
                <label className="text-body-secondary">Role</label>
                <div>
                  <span className={`badge text-bg-${getRoleBadge(user?.role)}`}>
                    {user?.role?.toUpperCase()}
                  </span>
                </div>
              </div>

              <div className="mb-3">
                <label className="text-body-secondary">Member Since</label>
                <div>{user?.created_at ? new Date(user.created_at).toLocaleDateString() : 'N/A'}</div>
              </div>

              <hr className="my-4" />

              <h5 className="card-title font-display mb-3">Change Password</h5>
              {msg && <div className="alert alert-success py-2">{msg}</div>}
              {error && <div className="alert alert-danger py-2">{error}</div>}
              <form onSubmit={handleChangePassword}>
                <div className="mb-3">
                  <label className="form-label text-body-secondary">Current password</label>
                  <input
                    type="password"
                    className="form-control"
                    value={form.current}
                    onChange={(e) => setForm({ ...form, current: e.target.value })}
                  />
                </div>
                <div className="mb-3">
                  <label className="form-label text-body-secondary">New password</label>
                  <input
                    type="password"
                    className="form-control"
                    value={form.next}
                    onChange={(e) => setForm({ ...form, next: e.target.value })}
                  />
                </div>
                <div className="mb-3">
                  <label className="form-label text-body-secondary">Confirm new password</label>
                  <input
                    type="password"
                    className="form-control"
                    value={form.confirm}
                    onChange={(e) => setForm({ ...form, confirm: e.target.value })}
                  />
                </div>
                <button type="submit" className="btn btn-danger w-100">Update Password</button>
              </form>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export default Profile;
