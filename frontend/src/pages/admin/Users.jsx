// Admin › Users: view accounts, what loot they hold, and change roles (admin only).
import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { getRoleBadge, Spinner } from './helpers';

function Users() {
  const { token, isAdmin } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  // Banning asks for a reason and a duration rather than being a dropdown pick.
  const [banTarget, setBanTarget] = useState(null);
  const [banForm, setBanForm] = useState({ reason: '', duration_days: '' });
  const [banHistory, setBanHistory] = useState([]);

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

  const openBan = async (user) => {
    setBanForm({ reason: '', duration_days: '' });
    setBanHistory([]);
    setError('');
    setNotice('');
    setBanTarget(user);
    try {
      const data = await api.admin.users.bans(token, user.id);
      setBanHistory(data.bans || []);
    } catch (err) {
      console.error('Load ban history error:', err);
    }
  };

  const handleRoleUpdate = async (user, newRole, extra = {}) => {
    setNotice('');
    setError('');

    // Banning is not a dropdown pick: it needs a reason and a duration, and it
    // reaches people who are mid-session. Divert to the dialog.
    if (newRole === 'banned' && !extra.confirmed) {
      loadData();  // put the select back
      openBan(user);
      return;
    }

    try {
      const data = await api.admin.users.updateRole(token, user.id, newRole, {
        reason: extra.reason,
        duration_days: extra.duration_days
      });
      // Report what actually applied in game rather than assuming it all did:
      // a server that was down is a partial success, not a silent one.
      const inGame = data.in_game || [];
      if (inGame.length) {
        const failed = inGame.filter((line) => line.startsWith('FAILED'));
        if (failed.length) {
          setError(`Role updated, but some servers did not apply it: ${failed.join('; ')}`);
        } else {
          setNotice(`Role updated. In game: ${inGame.join('; ')}.`);
        }
      } else {
        setNotice('Role updated.');
      }
      setBanTarget(null);
      loadData();
    } catch (err) {
      console.error('Update role error:', err);
      setError(err.message || 'Failed to update user role');
    }
  };

  const submitBan = (e) => {
    e.preventDefault();
    handleRoleUpdate(banTarget, 'banned', {
      confirmed: true,
      reason: banForm.reason.trim(),
      duration_days: banForm.duration_days ? parseInt(banForm.duration_days, 10) : null
    });
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
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      {banTarget && (
        <div
          className="modal show d-block"
          style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
          onClick={() => setBanTarget(null)}
        >
          <div className="modal-dialog modal-dialog-centered" onClick={(e) => e.stopPropagation()}>
            <form className="modal-content" onSubmit={submitBan}>
              <div className="modal-header">
                <h5 className="modal-title font-display">Ban {banTarget.username}</h5>
                <button type="button" className="btn-close" onClick={() => setBanTarget(null)}></button>
              </div>
              <div className="modal-body">
                <p className="text-body-secondary">
                  Their linked characters are kicked and banned on every server
                  they are on. The reason is shown to them.
                </p>

                <div className="mb-3">
                  <label className="form-label text-body-secondary">Reason</label>
                  <textarea
                    className="form-control"
                    rows="2"
                    value={banForm.reason}
                    onChange={(e) => setBanForm({ ...banForm, reason: e.target.value })}
                    placeholder="e.g. repeated base griefing"
                  />
                </div>

                <div className="mb-3">
                  <label className="form-label text-body-secondary">Duration (days)</label>
                  <input
                    type="number"
                    min="1"
                    max="3650"
                    className="form-control"
                    value={banForm.duration_days}
                    onChange={(e) => setBanForm({ ...banForm, duration_days: e.target.value })}
                    placeholder="leave blank for permanent"
                  />
                  <div className="form-text">
                    A timed ban lifts itself and restores the role they had before.
                  </div>
                </div>

                {banHistory.length > 0 && (
                  <div className="mt-4">
                    <div className="text-body-secondary small mb-2">
                      Previous bans ({banHistory.length})
                    </div>
                    <ul className="list-group list-group-flush">
                      {banHistory.map((b) => (
                        <li key={b.id} className="list-group-item small">
                          <div className="d-flex justify-content-between">
                            <span>{b.reason || 'no reason recorded'}</span>
                            <span className={`badge text-bg-${b.active ? 'danger' : 'secondary'}`}>
                              {b.active ? 'active' : 'lifted'}
                            </span>
                          </div>
                          <div className="text-body-secondary">
                            {b.created_at ? new Date(b.created_at).toLocaleDateString() : ''}
                            {b.permanent ? ' · permanent' : ` · until ${new Date(b.expires_at).toLocaleDateString()}`}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-outline-secondary" onClick={() => setBanTarget(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-danger">
                  {banForm.duration_days ? `Ban for ${banForm.duration_days} day(s)` : 'Ban permanently'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {loading ? <Spinner /> : (
        <div className="table-responsive">
          <table className="table table-striped align-middle">
            <thead>
              <tr>
                <th>Username</th>
                <th>Email</th>
                <th>Confirmed</th>
                <th>2FA</th>
                <th>Role</th>
                <th>Boxes</th>
                <th>Rewards</th>
                <th>Created</th>
                <th className="text-end">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.length === 0 ? (
                <tr>
                  <td colSpan="9" className="text-center">No users found</td>
                </tr>
              ) : (
                users.map((user) => (
                  <tr key={user.id}>
                    <td>{user.username}</td>
                    <td>{user.email}</td>
                    <td>
                      {user.email_verified
                        ? <span className="badge text-bg-success">yes</span>
                        : <span className="badge text-bg-secondary">no</span>}
                    </td>
                    <td>
                      {user.totp_enabled
                        ? <span className="badge text-bg-success">on</span>
                        : <span className="badge text-bg-secondary">off</span>}
                    </td>
                    <td>
                      <span className={`badge text-bg-${getRoleBadge(user.role)}`}>
                        {user.role}
                      </span>
                    </td>
                    <td>
                      {user.unopened_boxes > 0 ? (
                        <span title={`${user.unopened_boxes} unopened box(es)`} className="text-nowrap">
                          <i className="fas fa-box-open text-warning me-1"></i>{user.unopened_boxes}
                        </span>
                      ) : <span className="text-body-secondary">-</span>}
                    </td>
                    <td>
                      {user.held_rewards > 0 ? (
                        <span title={`${user.held_rewards} undelivered reward(s)`} className="text-nowrap">
                          <i className="fas fa-gift text-warning me-1"></i>{user.held_rewards}
                        </span>
                      ) : <span className="text-body-secondary">-</span>}
                    </td>
                    <td>{user.created_at ? new Date(user.created_at).toLocaleDateString() : 'N/A'}</td>
                    <td>
                      <div className="d-flex align-items-center justify-content-end gap-2">
                        <select
                          className="form-select form-select-sm"
                          value={user.role}
                          onChange={(e) => handleRoleUpdate(user, e.target.value)}
                          style={{ width: 'auto' }}
                        >
                          <option value="player">Player</option>
                          <option value="moderator">Moderator</option>
                          <option value="admin">Admin</option>
                          <option value="banned">Banned</option>
                        </select>
                        <Link
                          to={`/admin/users/${user.id}`}
                          className="btn btn-sm btn-outline-primary text-nowrap"
                        >
                          <i className="fas fa-user-gear me-1"></i>Manage
                        </Link>
                      </div>
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
