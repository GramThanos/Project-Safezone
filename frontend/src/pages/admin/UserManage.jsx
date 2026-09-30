// Admin › Users › Manage: one account, its characters, and the loot it still
// holds - with the account actions and the means to take loot away (admin only).
import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useDialog } from '../../context/DialogContext';
import api from '../../services/api';
import { getRoleBadge, getStatusBadge, RewardIcon, Spinner } from './helpers';

const formatDate = (iso) => (iso ? new Date(iso).toLocaleString() : '-');

// A card listing one kind of loot, with per-row, selected and "all" removal.
// Boxes and rewards remove the same way, so they share the table and only
// differ in their columns.
function LootTable({ title, icon, rows, columns, emptyText, busy, onRemove }) {
  const [selected, setSelected] = useState([]);

  // Drop selections for rows that are no longer there after a reload.
  useEffect(() => {
    setSelected((current) => current.filter((id) => rows.some((r) => r.id === id)));
  }, [rows]);

  const allSelected = rows.length > 0 && selected.length === rows.length;
  const toggle = (id) => setSelected((current) => (
    current.includes(id) ? current.filter((x) => x !== id) : [...current, id]
  ));

  return (
    <div className="card mb-4">
      <div className="card-header d-flex flex-wrap align-items-center gap-2">
        <span className="fw-semibold me-auto">
          <i className={`fas ${icon} me-2`}></i>{title}
          <span className="badge text-bg-secondary ms-2">{rows.length}</span>
        </span>
        <button
          className="btn btn-sm btn-outline-danger"
          disabled={busy || selected.length === 0}
          onClick={() => onRemove(selected)}
        >
          Remove selected{selected.length ? ` (${selected.length})` : ''}
        </button>
        <button
          className="btn btn-sm btn-danger"
          disabled={busy || rows.length === 0}
          onClick={() => onRemove(null)}
        >
          <i className="fas fa-trash me-1"></i>Remove all
        </button>
      </div>
      {rows.length === 0 ? (
        <div className="card-body text-body-secondary">{emptyText}</div>
      ) : (
        <div className="table-responsive">
          <table className="table table-sm table-striped align-middle mb-0">
            <thead>
              <tr>
                <th style={{ width: '2rem' }}>
                  <input
                    type="checkbox"
                    className="form-check-input"
                    checked={allSelected}
                    onChange={() => setSelected(allSelected ? [] : rows.map((r) => r.id))}
                    aria-label="Select all"
                  />
                </th>
                {columns.map((c) => <th key={c.label}>{c.label}</th>)}
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <input
                      type="checkbox"
                      className="form-check-input"
                      checked={selected.includes(row.id)}
                      onChange={() => toggle(row.id)}
                      aria-label="Select"
                    />
                  </td>
                  {columns.map((c) => <td key={c.label}>{c.render(row)}</td>)}
                  <td className="text-end">
                    <button
                      className="btn btn-sm btn-outline-danger"
                      disabled={busy}
                      onClick={() => onRemove([row.id])}
                      title="Remove"
                    >
                      <i className="fas fa-trash"></i>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const BOX_COLUMNS = [
  { label: 'Box', render: (b) => <><i className="fas fa-box-open text-warning me-2"></i>{b.box_name || `Box #${b.box_id}`}</> },
  { label: 'Source', render: (b) => <span className="badge text-bg-secondary">{b.source}</span> },
  { label: 'Granted', render: (b) => formatDate(b.granted_at) },
  { label: 'Expires', render: (b) => (b.expires_at ? formatDate(b.expires_at) : 'never') }
];

const REWARD_COLUMNS = [
  {
    label: 'Reward',
    render: (i) => (
      <span className="d-inline-flex align-items-center gap-2">
        <RewardIcon reward={i.reward} size={24} />
        {i.reward?.name || `Reward #${i.reward_id}`}
      </span>
    )
  },
  { label: 'Kind', render: (i) => i.reward?.kind || '-' },
  { label: 'Qty', render: (i) => `×${i.count}` },
  { label: 'Status', render: (i) => <span className={`badge text-bg-${getStatusBadge(i.status)}`}>{i.status}</span> },
  { label: 'Won', render: (i) => formatDate(i.created_at) },
  { label: 'Expires', render: (i) => (i.expires_at ? formatDate(i.expires_at) : 'never') }
];

function UserManage() {
  const { userId } = useParams();
  const { token, isAdmin } = useAuth();
  const { confirm } = useDialog();
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    if (!isAdmin()) return;
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const loadData = async () => {
    setError('');
    try {
      setDetail(await api.admin.users.get(token, userId));
    } catch (err) {
      console.error('Load user error:', err);
      setError(err.message || 'Failed to load user');
    }
    setLoading(false);
  };

  // Every action here reports through the same notice/error pair and reloads,
  // so the counts in the header always match the tables below.
  const run = async (question, action, fallback) => {
    if (!(await confirm({ message: question }))) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const data = await action();
      setNotice(data.message || 'Done.');
      await loadData();
    } catch (err) {
      console.error(fallback, err);
      setError(err.message || fallback);
    }
    setBusy(false);
  };

  if (!isAdmin()) {
    return (
      <div className="text-center py-5">
        <h4>Access Denied</h4>
        <p className="text-body-secondary">Only administrators can manage users.</p>
      </div>
    );
  }

  const back = (
    <Link to="/admin/users" className="btn btn-sm btn-outline-secondary mb-3">
      <i className="fas fa-arrow-left me-1"></i>Users
    </Link>
  );

  if (loading) return <>{back}<Spinner /></>;
  if (!detail) {
    return <>{back}<div className="alert alert-danger">{error || 'User not found'}</div></>;
  }

  const { user, characters, boxes, inventory } = detail;

  // Mails a one-time link rather than setting a password: an admin should never
  // learn a user's credentials.
  const resetPassword = () => run(
    `Email a password reset link to ${user.username}?`,
    () => api.admin.users.resetPassword(token, user.id),
    'Could not send the reset link'
  );

  // The way back in for a user who lost their authenticator: with no recovery
  // codes, an admin clearing the factor is the only key left.
  const disable2fa = () => run(
    `Turn off two-factor authentication for ${user.username}?`,
    () => api.admin.users.disable2fa(token, user.id),
    'Could not turn off two-factor auth'
  );

  const removeBoxes = (ids) => run(
    ids
      ? `Remove ${ids.length} unopened box(es) from ${user.username}? They cannot be given back.`
      : `Remove ALL of ${user.username}'s unopened boxes? They cannot be given back.`,
    () => api.admin.users.removeBoxes(token, user.id, ids),
    'Could not remove the boxes'
  );

  const removeInventory = (ids) => run(
    ids
      ? `Delete ${ids.length} undelivered reward(s) from ${user.username}? This cannot be undone.`
      : `Delete ALL of ${user.username}'s undelivered rewards? This cannot be undone.`,
    () => api.admin.users.removeInventory(token, user.id, ids),
    'Could not remove the rewards'
  );

  return (
    <>
      {back}
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      <div className="card mb-4">
        <div className="card-body">
          <div className="d-flex flex-wrap align-items-start gap-3">
            <div className="me-auto">
              <h4 className="font-display mb-1">
                {user.username}
                <span className={`badge text-bg-${getRoleBadge(user.role)} ms-2 align-middle fs-6`}>
                  {user.role}
                </span>
              </h4>
              <div className="text-body-secondary">{user.email}</div>
              <div className="small text-body-secondary mt-2">
                Joined {user.created_at ? new Date(user.created_at).toLocaleDateString() : 'N/A'}
                {' · '}email {user.email_verified ? 'confirmed' : 'not confirmed'}
                {' · '}2FA {user.totp_enabled ? 'on' : 'off'}
              </div>
            </div>
            <div className="d-flex gap-4 text-center">
              <div>
                <div className="fs-4 fw-semibold">
                  <i className="fas fa-box-open text-warning me-2"></i>{user.unopened_boxes}
                </div>
                <div className="small text-body-secondary">unopened boxes</div>
              </div>
              <div>
                <div className="fs-4 fw-semibold">
                  <i className="fas fa-gift me-2"></i>{user.held_rewards}
                </div>
                <div className="small text-body-secondary">undelivered rewards</div>
              </div>
            </div>
          </div>

          <div className="d-flex flex-wrap gap-2 mt-3">
            <button className="btn btn-sm btn-outline-secondary" disabled={busy} onClick={resetPassword}>
              Send reset link
            </button>
            {user.totp_enabled && (
              <button className="btn btn-sm btn-outline-warning" disabled={busy} onClick={disable2fa}>
                Disable 2FA
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="card mb-4">
        <div className="card-header fw-semibold">
          <i className="fas fa-user me-2"></i>Characters
          <span className="badge text-bg-secondary ms-2">{characters.length}</span>
        </div>
        {characters.length === 0 ? (
          <div className="card-body text-body-secondary">No linked characters.</div>
        ) : (
          <ul className="list-group list-group-flush">
            {characters.map((c) => (
              <li key={c.id} className="list-group-item d-flex justify-content-between">
                <span>{c.in_game_username || c.name}</span>
                <span className="small text-body-secondary">
                  server {c.server_id ?? '-'} · last seen {formatDate(c.last_seen_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <LootTable
        title="Unopened boxes"
        icon="fa-box-open"
        rows={boxes}
        columns={BOX_COLUMNS}
        emptyText="No unopened boxes."
        busy={busy}
        onRemove={removeBoxes}
      />

      <LootTable
        title="Undelivered rewards"
        icon="fa-gift"
        rows={inventory}
        columns={REWARD_COLUMNS}
        emptyText="No undelivered rewards. Rewards on their way into the game cannot be removed."
        busy={busy}
        onRemove={removeInventory}
      />
    </>
  );
}

export default UserManage;
