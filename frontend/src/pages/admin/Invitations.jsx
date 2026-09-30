// Admin › Invitations: issue and revoke signup links.
//
// The code is shown exactly once, when it is created — only its hash is stored,
// so it genuinely cannot be recovered afterwards. The UI has to make that clear
// rather than letting someone assume they can come back for it.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useDialog } from '../../context/DialogContext';
import api from '../../services/api';
import { getStatusBadge, Spinner } from './helpers';

const BLANK = { max_uses: '1', expires_in_days: '', note: '' };

function Invitations() {
  const { token } = useAuth();
  const { confirm } = useDialog();
  const [invitations, setInvitations] = useState([]);
  const [form, setForm] = useState(BLANK);
  const [issued, setIssued] = useState(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setError('');
    try {
      const data = await api.invitations.list(token);
      setInvitations(data.invitations || []);
    } catch (err) {
      console.error('Load invitations error:', err);
      setError('Failed to load invitations');
    }
    setLoading(false);
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    setError('');
    setCopied(false);
    try {
      const data = await api.invitations.create(token, {
        max_uses: parseInt(form.max_uses, 10) || 1,
        expires_in_days: form.expires_in_days === '' ? null : parseInt(form.expires_in_days, 10),
        note: form.note.trim()
      });
      setIssued(data);
      setForm(BLANK);
      loadData();
    } catch (err) {
      console.error('Create invitation error:', err);
      setError(err.message || 'Could not create that invitation');
    }
  };

  const handleRevoke = async (id) => {
    if (!(await confirm({
      title: 'Revoke invitation?',
      message: 'Any unused link stops working.',
      confirmLabel: 'Revoke'
    }))) return;
    setError('');
    try {
      await api.invitations.revoke(token, id);
      loadData();
    } catch (err) {
      console.error('Revoke invitation error:', err);
      setError(err.message || 'Could not revoke that invitation');
    }
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(issued.link);
      setCopied(true);
    } catch {
      // Clipboard access can be refused; the link is on screen to copy by hand.
      setCopied(false);
    }
  };

  const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : 'never');

  return (
    <>
      <h4 className="font-display mb-1">Invitations</h4>
      <p className="text-body-secondary">
        An invitation lets someone sign up even when registration is closed.
        Links can be single-use, time-limited, or both.
      </p>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}

      {issued && (
        <div className="alert alert-success">
          <div className="fw-bold mb-2">Copy this link now — it is not shown again.</div>
          <code className="d-block text-break mb-2">{issued.link}</code>
          <button className="btn btn-sm btn-outline-secondary" onClick={copyLink}>
            {copied ? 'Copied' : 'Copy link'}
          </button>
          <button className="btn btn-sm btn-outline-secondary ms-2" onClick={() => setIssued(null)}>
            Dismiss
          </button>
        </div>
      )}

      <div className="card mb-4">
        <div className="card-body">
          <h5 className="card-title font-display mb-3">New invitation</h5>
          <form className="row g-2 align-items-end" onSubmit={handleCreate}>
            <div className="col-md-2">
              <label className="form-label text-body-secondary">Uses</label>
              <input
                type="number"
                min="1"
                max="100"
                className="form-control"
                value={form.max_uses}
                onChange={(e) => setForm({ ...form, max_uses: e.target.value })}
              />
            </div>
            <div className="col-md-3">
              <label className="form-label text-body-secondary">Expires in (days)</label>
              <input
                type="number"
                min="1"
                max="365"
                className="form-control"
                placeholder="never"
                value={form.expires_in_days}
                onChange={(e) => setForm({ ...form, expires_in_days: e.target.value })}
              />
            </div>
            <div className="col-md-5">
              <label className="form-label text-body-secondary">Note (optional)</label>
              <input
                type="text"
                className="form-control"
                placeholder="who it is for"
                value={form.note}
                onChange={(e) => setForm({ ...form, note: e.target.value })}
              />
            </div>
            <div className="col-md-2">
              <button type="submit" className="btn btn-danger w-100">Create</button>
            </div>
          </form>
        </div>
      </div>

      {loading ? <Spinner /> : (
        <div className="table-responsive">
          <table className="table table-striped align-middle">
            <thead>
              <tr>
                <th>ID</th>
                <th>Note</th>
                <th>Issued by</th>
                <th>Uses</th>
                <th>Expires</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {invitations.length === 0 ? (
                <tr><td colSpan="7" className="text-center">No invitations</td></tr>
              ) : (
                invitations.map((inv) => (
                  <tr key={inv.id}>
                    <td>{inv.id}</td>
                    <td className="text-body-secondary">{inv.note || '—'}</td>
                    <td>#{inv.created_by}</td>
                    <td>{inv.uses} / {inv.max_uses}</td>
                    <td>{fmt(inv.expires_at)}</td>
                    <td>
                      <span className={`badge text-bg-${getStatusBadge(inv.status)}`}>
                        {inv.status}
                      </span>
                    </td>
                    <td>
                      {inv.status === 'active' ? (
                        <button
                          className="btn btn-sm btn-outline-danger"
                          onClick={() => handleRevoke(inv.id)}
                        >
                          Revoke
                        </button>
                      ) : (
                        <span className="text-body-secondary">—</span>
                      )}
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

export default Invitations;
