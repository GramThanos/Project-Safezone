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

  useEffect(() => {
    loadPlayers();
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
            <h2 style={{ fontFamily: "'Oswald', sans-serif", letterSpacing: '0.6px' }}>
              MY PLAYERS
            </h2>
            <p className="small-muted">Manage your game characters</p>
          </div>
          <button className="btn btn-accent" onClick={handleCreate}>
            <i className="fas fa-plus"></i> Create Player
          </button>
        </div>

        {error && (
          <div className="alert alert-danger" role="alert">
            {error}
          </div>
        )}

        {players.length === 0 ? (
          <div className="text-center py-5">
            <p className="small-muted mb-3">You don't have any players yet</p>
            <button className="btn btn-accent" onClick={handleCreate}>
              Create Your First Player
            </button>
          </div>
        ) : (
          <div className="row g-4">
            {players.map((player) => (
              <div key={player.id} className="col-md-6 col-lg-4">
                <div className="character-card">
                  <div>
                    <div 
                      className="avatar" 
                      style={{ 
                        backgroundImage: player.avatar && player.avatar.startsWith('http') 
                          ? `url(${player.avatar.replace(/['"]/g, '')})` 
                          : "url('./assets/images/safezone-banner-1.png')" 
                      }}
                    ></div>
                    <div className="character-title">{player.name}</div>
                    <div className="character-desc">
                      {player.description || 'No description provided'}
                    </div>
                  </div>
                  <div className="mt-3 d-flex gap-2">
                    <button 
                      className="btn btn-light btn-sm"
                      onClick={() => handleEdit(player)}
                    >
                      <i className="fas fa-edit"></i> Edit
                    </button>
                    <button 
                      className="btn btn-outline-light btn-sm"
                      onClick={() => handleDelete(player.id)}
                    >
                      <i className="fas fa-trash"></i> Delete
                    </button>
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
              <div className="modal-content" style={{ backgroundColor: 'var(--card)', color: '#e6e6e6' }}>
                <div className="modal-header border-0">
                  <h5 className="modal-title">
                    {editingPlayer ? 'Edit Player' : 'Create Player'}
                  </h5>
                  <button 
                    type="button" 
                    className="btn-close btn-close-white" 
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
                  <div className="modal-footer border-0">
                    <button 
                      type="button" 
                      className="btn btn-outline-light" 
                      onClick={() => setShowModal(false)}
                    >
                      Cancel
                    </button>
                    <button type="submit" className="btn btn-accent">
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
