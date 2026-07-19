// Admin › Give Item: manually deliver an item/usable to an online player.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';

function Give() {
  const { token } = useAuth();
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [giveMsg, setGiveMsg] = useState('');
  const [onlinePlayers, setOnlinePlayers] = useState([]);
  const [giveForm, setGiveForm] = useState({
    server_id: '', in_game_username: '', kind: 'item', in_game_id: '', command_template: '', count: 1
  });

  useEffect(() => {
    loadServers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadServers = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api.admin.servers.getAll(token);
      if (data.servers) setServers(data.servers);
    } catch (err) {
      console.error('Load servers error:', err);
      setError('Failed to load servers');
    }
    setLoading(false);
  };

  const handleGiveServerChange = async (serverId) => {
    setGiveForm({ ...giveForm, server_id: serverId, in_game_username: '' });
    setOnlinePlayers([]);
    if (!serverId) return;
    try {
      const data = await api.servers.getOnline(token, serverId);
      setOnlinePlayers(data.online || []);
    } catch (err) {
      console.error('Load online players error:', err);
    }
  };

  const handleGiveSubmit = async (e) => {
    e.preventDefault();
    setGiveMsg('');
    setError('');
    if (!giveForm.server_id || !giveForm.in_game_username.trim()) {
      setError('Server and in-game username are required');
      return;
    }
    const payload = {
      server_id: parseInt(giveForm.server_id, 10),
      in_game_username: giveForm.in_game_username.trim(),
      kind: giveForm.kind
    };
    if (giveForm.kind === 'usable') {
      if (!giveForm.command_template.trim()) {
        setError('A command template is required for usables');
        return;
      }
      payload.command_template = giveForm.command_template.trim();
    } else {
      if (!giveForm.in_game_id.trim()) {
        setError('An item id is required');
        return;
      }
      payload.in_game_id = giveForm.in_game_id.trim();
      payload.count = parseInt(giveForm.count, 10) || 1;
    }
    try {
      await api.admin.give(token, payload);
      setGiveMsg('Delivery task created. The item is sent if the player is online.');
      setGiveForm({ ...giveForm, in_game_username: '', in_game_id: '', command_template: '' });
    } catch (err) {
      console.error('Give reward error:', err);
      setError(err.message || 'Failed to give reward');
    }
  };

  return (
    <>
      <h4 className="font-display mb-3">Give Item</h4>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}

      {loading ? <Spinner /> : (
        <div className="card" style={{ maxWidth: '640px' }}>
          <div className="card-body">
            <h5 className="card-title font-display mb-1">Give Item / Usable</h5>
            <p className="text-body-secondary">
              Send an item or run a usable for an in-game player. The player must be
              <strong> online</strong> on the selected server.
            </p>
            {giveMsg && <div className="alert alert-success py-2">{giveMsg}</div>}
            <form onSubmit={handleGiveSubmit}>
              <div className="row g-2">
                <div className="col-md-6">
                  <label className="form-label text-body-secondary">Server</label>
                  <select
                    className="form-select"
                    value={giveForm.server_id}
                    onChange={(e) => handleGiveServerChange(e.target.value)}
                  >
                    <option value="">Select a server…</option>
                    {servers.map((s) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </select>
                </div>
                <div className="col-md-6">
                  <label className="form-label text-body-secondary">Online player</label>
                  <select
                    className="form-select"
                    value={giveForm.in_game_username}
                    onChange={(e) => setGiveForm({ ...giveForm, in_game_username: e.target.value })}
                    disabled={!giveForm.server_id || onlinePlayers.length === 0}
                  >
                    <option value="">
                      {!giveForm.server_id
                        ? 'Select a server first…'
                        : onlinePlayers.length === 0
                          ? 'No players online'
                          : 'Select a player…'}
                    </option>
                    {onlinePlayers.map((name) => (
                      <option key={name} value={name}>{name}</option>
                    ))}
                  </select>
                </div>
                <div className="col-md-4">
                  <label className="form-label text-body-secondary">Kind</label>
                  <select
                    className="form-select"
                    value={giveForm.kind}
                    onChange={(e) => setGiveForm({ ...giveForm, kind: e.target.value })}
                  >
                    <option value="item">Item</option>
                    <option value="usable">Usable</option>
                  </select>
                </div>
                {giveForm.kind === 'item' ? (
                  <>
                    <div className="col-md-5">
                      <label className="form-label text-body-secondary">Item id</label>
                      <input
                        type="text"
                        className="form-control"
                        placeholder="Base.Axe"
                        value={giveForm.in_game_id}
                        onChange={(e) => setGiveForm({ ...giveForm, in_game_id: e.target.value })}
                      />
                    </div>
                    <div className="col-md-3">
                      <label className="form-label text-body-secondary">Count</label>
                      <input
                        type="number"
                        min="1"
                        className="form-control"
                        value={giveForm.count}
                        onChange={(e) => setGiveForm({ ...giveForm, count: e.target.value })}
                      />
                    </div>
                  </>
                ) : (
                  <div className="col-md-8">
                    <label className="form-label text-body-secondary">Command template (use {'{username}'})</label>
                    <input
                      type="text"
                      className="form-control"
                      placeholder={'godmode "{username}" -true'}
                      value={giveForm.command_template}
                      onChange={(e) => setGiveForm({ ...giveForm, command_template: e.target.value })}
                    />
                  </div>
                )}
                <div className="col-12 mt-3">
                  <button type="submit" className="btn btn-danger">Send</button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

export default Give;
