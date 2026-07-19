// Players management page
import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';

function Players() {
  const { token } = useAuth();
  const [players, setPlayers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [editingPlayer, setEditingPlayer] = useState(null);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    avatar: ''
  });
  const [servers, setServers] = useState([]);
  const [claims, setClaims] = useState([]);
  const [claimForm, setClaimForm] = useState({ server_id: '', in_game_username: '' });
  const [claimMsg, setClaimMsg] = useState('');

  useEffect(() => {
    loadPlayers();
    loadServers();
    loadClaims();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadPlayers = async () => {
    try {
      const data = await api.players.getAll(token);
      if (data.players) {
        setPlayers(data.players);
      }
      setLoading(false);
    } catch (err) {
      console.error('Load players error:', err);
      setError('Failed to load players');
      setLoading(false);
    }
  };

  const loadServers = async () => {
    try {
      const data = await api.servers.getAll();
      if (data.servers) setServers(data.servers);
    } catch (err) {
      console.error('Load servers error:', err);
    }
  };

  const loadClaims = async () => {
    try {
      const data = await api.claims.getMine(token);
      if (data.claims) setClaims(data.claims);
    } catch (err) {
      console.error('Load claims error:', err);
    }
  };

  const handleClaimSubmit = async (e) => {
    e.preventDefault();
    setClaimMsg('');
    setError('');
    if (!claimForm.server_id || !claimForm.in_game_username.trim()) {
      setError('Pick a server and enter your in-game username');
      return;
    }
    try {
      await api.claims.create(token, {
        server_id: parseInt(claimForm.server_id, 10),
        in_game_username: claimForm.in_game_username.trim()
      });
      setClaimForm({ server_id: '', in_game_username: '' });
      setClaimMsg('Claim request submitted — an admin will review it.');
      loadClaims();
    } catch (err) {
      console.error('Submit claim error:', err);
      setError(err.message || 'Failed to submit claim');
    }
  };

  const claimStatusBadge = (status) => {
    const map = { approved: 'success', pending: 'warning', rejected: 'secondary' };
    return map[status] || 'secondary';
  };

  const serverName = (id) => {
    const s = servers.find((sv) => sv.id === id);
    return s ? s.name : `#${id}`;
  };

  const handleCreate = () => {
    setEditingPlayer(null);
    setFormData({ name: '', description: '', avatar: '' });
    setShowModal(true);
  };

  const handleEdit = (player) => {
    setEditingPlayer(player);
    setFormData({
      name: player.name,
      description: player.description || '',
      avatar: player.avatar || ''
    });
    setShowModal(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    try {
      if (editingPlayer) {
        await api.players.update(token, editingPlayer.id, formData);
      } else {
        await api.players.create(token, formData);
      }
      setShowModal(false);
      loadPlayers();
    } catch (err) {
      console.error('Save player error:', err);
      setError('Failed to save player');
    }
  };

  const handleDelete = async (playerId) => {
    if (!window.confirm('Are you sure you want to delete this player?')) {
      return;
    }

    try {
      await api.players.delete(token, playerId);
      loadPlayers();
    } catch (err) {
      console.error('Delete player error:', err);
      setError('Failed to delete player');
    }
  };

  if (loading) {
    return (
      <section className="py-5" style={{ minHeight: '50vh' }}>
        <div className="container text-center">
          <div className="spinner-border text-light" role="status">
            <span className="visually-hidden">Loading...</span>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="py-5" style={{ minHeight: '50vh' }}>
      <div className="container">
        <div className="d-flex justify-content-between align-items-center mb-4">
          <div>
            <h2 className="text-uppercase font-display">
              My Players
            </h2>
            <p className="text-body-secondary">Manage your game characters</p>
          </div>
          <button className="btn btn-danger" onClick={handleCreate}>
            <i className="fas fa-plus"></i> Create Player
          </button>
        </div>

        {error && (
          <div className="alert alert-danger" role="alert">
            {error}
          </div>
        )}

        {/* Claim an in-game character */}
        <div className="card mb-4">
          <div className="card-body">
          <h5 className="card-title font-display mb-1">Claim a Character</h5>
          <p className="text-body-secondary">
            Link an in-game character to your account so you can receive items.
            You must be <strong>online</strong> on the server when you submit the request.
          </p>
          {claimMsg && <div className="alert alert-success py-2">{claimMsg}</div>}
          <form className="row g-2 align-items-end" onSubmit={handleClaimSubmit}>
            <div className="col-md-5">
              <label className="form-label text-body-secondary">Server</label>
              <select
                className="form-select"
                value={claimForm.server_id}
                onChange={(e) => setClaimForm({ ...claimForm, server_id: e.target.value })}
              >
                <option value="">Select a server…</option>
                {servers.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>
            <div className="col-md-5">
              <label className="form-label text-body-secondary">In-game username</label>
              <input
                type="text"
                className="form-control"
                placeholder="YourInGameName"
                value={claimForm.in_game_username}
                onChange={(e) => setClaimForm({ ...claimForm, in_game_username: e.target.value })}
              />
            </div>
            <div className="col-md-2">
              <button type="submit" className="btn btn-danger w-100">Claim</button>
            </div>
          </form>

          {claims.length > 0 && (
            <div className="mt-3">
              <div className="text-body-secondary mb-2">My claim requests</div>
              <ul className="list-group">
                {claims.map((c) => (
                  <li key={c.id} className="list-group-item d-flex justify-content-between align-items-center">
                    <span>{c.in_game_username} @ {serverName(c.server_id)}</span>
                    <span className={`badge text-bg-${claimStatusBadge(c.status)}`}>{c.status}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          </div>
        </div>

        {players.length === 0 ? (
          <div className="text-center py-5">
            <p className="text-body-secondary mb-3">You don't have any players yet</p>
            <button className="btn btn-danger" onClick={handleCreate}>
              Create Your First Player
            </button>
          </div>
        ) : (
          <div className="row g-4">
            {players.map((player) => (
              <div key={player.id} className="col-md-6 col-lg-4">
                <div className="card h-100">
                  <img
                    className="card-img-top card-banner object-fit-cover"
                    src={player.avatar && player.avatar.startsWith('http')
                      ? player.avatar.replace(/['"]/g, '')
                      : '/assets/images/safezone-banner-1.png'}
                    alt={player.name}
                  />
                  <div className="card-body d-flex flex-column">
                    <h5 className="card-title font-display">
                      {player.name}
                      {player.verified && (
                        <span className="badge text-bg-success ms-2" title="Linked in-game character">
                          <i className="fas fa-check"></i> Linked
                        </span>
                      )}
                    </h5>
                    {player.verified && (
                      <div className="text-body-secondary mb-2">
                        <i className="fas fa-gamepad"></i> {player.in_game_username} @ {serverName(player.server_id)}
                      </div>
                    )}
                    <p className="card-text text-body-secondary flex-grow-1">
                      {player.description || 'No description provided'}
                    </p>
                    <div className="d-flex gap-2">
                      <button
                        className="btn btn-outline-light btn-sm"
                        onClick={() => handleEdit(player)}
                      >
                        <i className="fas fa-edit"></i> Edit
                      </button>
                      <button
                        className="btn btn-outline-danger btn-sm"
                        onClick={() => handleDelete(player.id)}
                      >
                        <i className="fas fa-trash"></i> Delete
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Modal */}
        {showModal && (
          <div className="modal show d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }}>
            <div className="modal-dialog modal-dialog-centered">
              <div className="modal-content">
                <div className="modal-header">
                  <h5 className="modal-title">
                    {editingPlayer ? 'Edit Player' : 'Create Player'}
                  </h5>
                  <button
                    type="button"
                    className="btn-close"
                    onClick={() => setShowModal(false)}
                  ></button>
                </div>
                <form onSubmit={handleSubmit}>
                  <div className="modal-body">
                    <div className="mb-3">
                      <label className="form-label">Player Name</label>
                      <input
                        type="text"
                        className="form-control"
                        value={formData.name}
                        onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                        required
                      />
                    </div>
                    <div className="mb-3">
                      <label className="form-label">Description</label>
                      <textarea
                        className="form-control"
                        rows="3"
                        value={formData.description}
                        onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                      ></textarea>
                    </div>
                    <div className="mb-3">
                      <label className="form-label">Avatar URL (optional)</label>
                      <input
                        type="text"
                        className="form-control"
                        value={formData.avatar}
                        onChange={(e) => setFormData({ ...formData, avatar: e.target.value })}
                      />
                    </div>
                  </div>
                  <div className="modal-footer">
                    <button
                      type="button"
                      className="btn btn-outline-light"
                      onClick={() => setShowModal(false)}
                    >
                      Cancel
                    </button>
                    <button type="submit" className="btn btn-danger">
                      Save
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

export default Players;
