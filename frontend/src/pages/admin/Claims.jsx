// Admin › Claims: the record of account ↔ in-game character links, and the
// lever to revoke one. Claims are approved automatically — being connected to
// the server is itself the proof that the requester controls the character —
// so this page reviews history rather than working a queue.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { getStatusBadge, Spinner } from './helpers';

function Claims() {
  const { token } = useAuth();
  const [claims, setClaims] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  // The claim being revoked, plus the reason typed for it.
  const [revoking, setRevoking] = useState(null);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api.admin.claims.getAll(token);
      if (data.claims) setClaims(data.claims);
    } catch (err) {
      console.error('Load claims error:', err);
      setError('Failed to load claims');
    }
    setLoading(false);
  };

  const openRevoke = (claim) => {
    setReason('');
    setError('');
    setNotice('');
    setRevoking(claim);
  };

  const handleRevoke = async (e) => {
    e.preventDefault();
    if (!reason.trim()) return;
    setSubmitting(true);
    setError('');
    try {
      await api.admin.claims.revoke(token, revoking.id, reason.trim());
      setNotice(`Released ${revoking.in_game_username}. Anyone can claim that name again.`);
      setRevoking(null);
      loadData();
    } catch (err) {
      console.error('Revoke claim error:', err);
      setError(err.message || 'Could not revoke that link');
    }
    setSubmitting(false);
  };

  const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : '—');

  return (
    <>
      <h4 className="font-display mb-1">Character links</h4>
      <p className="text-body-secondary">
        A claim is approved the moment it is made: the character has to be online
        to be claimed, which only its owner can arrange. Revoking a link deletes
        the character profile and frees the in-game name.
      </p>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      {loading ? <Spinner /> : (
        <div className="table-responsive">
          <table className="table table-striped align-middle">
            <thead>
              <tr>
                <th>ID</th>
                <th>Account</th>
                <th>In-game username</th>
                <th>Server</th>
                <th>Status</th>
                <th>Linked</th>
                <th>Reason</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {claims.length === 0 ? (
                <tr>
                  <td colSpan="8" className="text-center">No character links yet</td>
                </tr>
              ) : (
                claims.map((claim) => (
                  <tr key={claim.id}>
                    <td>{claim.id}</td>
                    <td>#{claim.user_id}</td>
                    <td>{claim.in_game_username}</td>
                    <td>#{claim.server_id}</td>
                    <td>
                      <span className={`badge text-bg-${getStatusBadge(claim.status)}`}>
                        {claim.status}
                      </span>
                    </td>
                    <td>{fmt(claim.created_at)}</td>
                    <td className="text-body-secondary">{claim.reason || '—'}</td>
                    <td>
                      {claim.status === 'approved' ? (
                        <button
                          className="btn btn-sm btn-outline-danger"
                          onClick={() => openRevoke(claim)}
                        >
                          <i className="fas fa-unlink"></i> Revoke
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

      {/* Revoke dialog — the reason is required, because the player sees it. */}
      {revoking && (
        <div
          className="modal show d-block"
          style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
          onClick={() => setRevoking(null)}
        >
          <div className="modal-dialog modal-dialog-centered" onClick={(e) => e.stopPropagation()}>
            <form className="modal-content" onSubmit={handleRevoke}>
              <div className="modal-header">
                <h5 className="modal-title font-display">
                  Revoke {revoking.in_game_username}
                </h5>
                <button type="button" className="btn-close" onClick={() => setRevoking(null)}></button>
              </div>
              <div className="modal-body">
                <p className="text-body-secondary">
                  This deletes the character profile on account #{revoking.user_id} and
                  releases <strong>{revoking.in_game_username}</strong> on server
                  #{revoking.server_id}. It does not ban the account or affect the
                  character in game.
                </p>
                <label className="form-label" htmlFor="revoke-reason">
                  Reason (the player will see this)
                </label>
                <textarea
                  id="revoke-reason"
                  className="form-control"
                  rows="3"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="e.g. claimed a character belonging to another player"
                  required
                />
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-outline-secondary" onClick={() => setRevoking(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-danger" disabled={submitting || !reason.trim()}>
                  {submitting ? 'Revoking…' : 'Revoke link'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

export default Claims;
