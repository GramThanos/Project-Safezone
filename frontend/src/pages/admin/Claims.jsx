// Admin › Claims: the record of account ↔ in-game character links, and the
// lever to revoke one. Claims are approved automatically — being connected to
// the server is itself the proof that the requester controls the character —
// so this page reviews history rather than working a queue. Below it, the
// characters saved on the servers that nobody is linked to, which an admin can
// link to an account by hand.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { getStatusBadge, Spinner } from './helpers';
import { CharacterGameButton } from '../../components/CharacterGameInfo';
import { formatDateTime } from '../../utils/dates';

function Claims() {
  const { token, isAdmin } = useAuth();
  const [claims, setClaims] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  // The claim being revoked, plus the reason typed for it.
  const [revoking, setRevoking] = useState(null);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  // Saved characters with no account linked, and how each server's save read.
  const [unlinked, setUnlinked] = useState([]);
  const [saves, setSaves] = useState([]);
  const [unlinkedLoading, setUnlinkedLoading] = useState(true);
  const [unlinkedError, setUnlinkedError] = useState('');
  // The character being linked, plus the account username typed for it.
  const [linking, setLinking] = useState(null);
  const [account, setAccount] = useState('');

  useEffect(() => {
    loadData();
    loadUnlinked();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Separate from the claims, since it reads every server's save and is the
  // slower of the two.
  const loadUnlinked = async () => {
    setUnlinkedLoading(true);
    setUnlinkedError('');
    try {
      const data = await api.admin.claims.getUnlinked(token);
      setUnlinked(data.characters || []);
      setSaves(data.servers || []);
    } catch (err) {
      console.error('Load unlinked characters error:', err);
      setUnlinkedError(err.message || 'Failed to load the saved characters');
    }
    setUnlinkedLoading(false);
  };

  const openLink = (character) => {
    setAccount(character.suggested_user?.username || '');
    setError('');
    setNotice('');
    setLinking(character);
  };

  const handleLink = async (e) => {
    e.preventDefault();
    if (!account.trim()) return;
    setSubmitting(true);
    setError('');
    try {
      const data = await api.admin.claims.link(
        token, linking.server_id, linking.username, account.trim());
      setNotice(data.message || `Linked ${linking.username}.`);
      setLinking(null);
      loadData();
      loadUnlinked();
    } catch (err) {
      console.error('Link character error:', err);
      setError(err.message || 'Could not link that character');
    }
    setSubmitting(false);
  };

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
      loadUnlinked();
    } catch (err) {
      console.error('Revoke claim error:', err);
      setError(err.message || 'Could not revoke that link');
    }
    setSubmitting(false);
  };

  const fmt = (ts) => formatDateTime(ts, '—');

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
                        <div className="d-flex gap-2">
                          {claim.character_id && (
                            <CharacterGameButton
                              characterId={claim.character_id}
                              title={claim.in_game_username}
                            />
                          )}
                          <button
                            className="btn btn-sm btn-outline-danger"
                            onClick={() => openRevoke(claim)}
                          >
                            <i className="fas fa-unlink"></i> Revoke
                          </button>
                        </div>
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

      <h5 className="font-display mt-5 mb-1">Unlinked characters</h5>
      <p className="text-body-secondary">
        Characters in the servers' saves that no account is linked to, as of each
        game's last save — offline ones included, which a player cannot claim
        themselves.{isAdmin() && ' Linking one skips the online check, so make sure the account really owns it.'}
      </p>

      {saves.filter((s) => s.error).map((s) => (
        <div key={s.server_id} className="alert alert-warning" role="alert">
          {s.name || `Server #${s.server_id}`}: {s.error}
        </div>
      ))}
      {unlinkedError && <div className="alert alert-danger" role="alert">{unlinkedError}</div>}

      {unlinkedLoading ? <Spinner /> : !unlinkedError && (
        <div className="table-responsive">
          <table className="table table-striped align-middle">
            <thead>
              <tr>
                <th>In-game username</th>
                <th>Character</th>
                <th>Server</th>
                <th>Status</th>
                <th>Zombie kills</th>
                <th>Hours survived</th>
                <th>Matching account</th>
                {isAdmin() && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {unlinked.length === 0 ? (
                <tr>
                  <td colSpan={isAdmin() ? 8 : 7} className="text-center">
                    Every saved character is linked
                  </td>
                </tr>
              ) : (
                unlinked.map((c) => (
                  <tr key={`${c.server_id}:${c.username}`}>
                    <td>{c.username}</td>
                    <td>{c.name || '—'}</td>
                    <td>{c.server_name || `#${c.server_id}`}</td>
                    <td className="text-body-secondary">{c.status || '—'}</td>
                    <td>{c.zombie_kills ?? '—'}</td>
                    <td>{c.hours_survived != null ? Math.round(c.hours_survived) : '—'}</td>
                    <td>
                      {c.suggested_user
                        ? `${c.suggested_user.username} (#${c.suggested_user.id})`
                        : <span className="text-body-secondary">—</span>}
                    </td>
                    {isAdmin() && (
                      <td>
                        {c.linkable ? (
                          <button
                            className="btn btn-sm btn-outline-success"
                            onClick={() => openLink(c)}
                          >
                            <i className="fas fa-link"></i> Link
                          </button>
                        ) : (
                          <span
                            className="text-body-secondary"
                            title="Only letters, digits and underscores can be linked"
                          >
                            Unsupported name
                          </span>
                        )}
                      </td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Link dialog — the account is named by its username. */}
      {linking && (
        <div
          className="modal show d-block"
          style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
          onClick={() => setLinking(null)}
        >
          <div className="modal-dialog modal-dialog-centered" onClick={(e) => e.stopPropagation()}>
            <form className="modal-content" onSubmit={handleLink}>
              <div className="modal-header">
                <h5 className="modal-title font-display">
                  Link {linking.username}
                </h5>
                <button type="button" className="btn-close" onClick={() => setLinking(null)}></button>
              </div>
              <div className="modal-body">
                <p className="text-body-secondary">
                  This links <strong>{linking.username}</strong>
                  {linking.name ? ` (${linking.name})` : ''} on{' '}
                  {linking.server_name || `server #${linking.server_id}`} to an account,
                  as if its owner had claimed it. The player is notified, and only
                  what the character does from now on earns coins.
                </p>
                {error && <div className="alert alert-danger" role="alert">{error}</div>}
                <label className="form-label" htmlFor="link-account">
                  Account username
                </label>
                <input
                  id="link-account"
                  className="form-control"
                  value={account}
                  onChange={(e) => setAccount(e.target.value)}
                  autoComplete="off"
                  required
                />
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-outline-secondary" onClick={() => setLinking(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-success" disabled={submitting || !account.trim()}>
                  {submitting ? 'Linking…' : 'Link character'}
                </button>
              </div>
            </form>
          </div>
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
