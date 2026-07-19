// Rewards page: daily loot boxes + inventory delivery
import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';

const SIZE_BADGE = { small: 'secondary', medium: 'info', big: 'warning' };

function Rewards() {
  const { token } = useAuth();
  const [boxes, setBoxes] = useState([]);
  const [inventory, setInventory] = useState([]);
  const [onlinePlayers, setOnlinePlayers] = useState([]);
  const [sendTargets, setSendTargets] = useState({});
  const [reveal, setReveal] = useState(null); // items revealed after opening a box
  const [dailyMsg, setDailyMsg] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const init = async () => {
    try {
      const daily = await api.boxes.claimDaily(token);
      if (daily.granted && daily.box) {
        setDailyMsg(`You received a ${daily.box.size} loot box for logging in today!`);
      }
    } catch (err) {
      console.error('Daily box error:', err);
    }
    await Promise.all([loadBoxes(), loadInventory(), loadPlayersAndOnline()]);
    setLoading(false);
  };

  const loadBoxes = async () => {
    try {
      const data = await api.boxes.list(token);
      setBoxes(data.boxes || []);
    } catch (err) {
      console.error('Load boxes error:', err);
    }
  };

  const loadInventory = async () => {
    try {
      const data = await api.inventory.list(token);
      setInventory(data.inventory || []);
    } catch (err) {
      console.error('Load inventory error:', err);
    }
  };

  // Determine which of the account's linked characters are currently online.
  const loadPlayersAndOnline = async () => {
    try {
      const data = await api.players.getAll(token);
      const deliverable = (data.players || []).filter((p) => p.deliverable);
      const serverIds = [...new Set(deliverable.map((p) => p.server_id))];
      const onlineByServer = {};
      await Promise.all(serverIds.map(async (sid) => {
        try {
          const res = await api.servers.getOnline(token, sid);
          onlineByServer[sid] = new Set(res.online || []);
        } catch {
          onlineByServer[sid] = new Set();
        }
      }));
      setOnlinePlayers(
        deliverable.filter((p) => onlineByServer[p.server_id]?.has(p.in_game_username))
      );
    } catch (err) {
      console.error('Load players error:', err);
    }
  };

  const handleOpen = async (boxId) => {
    setError('');
    try {
      const data = await api.boxes.open(token, boxId);
      setReveal(data.items || []);
      await Promise.all([loadBoxes(), loadInventory()]);
    } catch (err) {
      console.error('Open box error:', err);
      setError(err.message || 'Failed to open box');
    }
  };

  const handleSend = async (itemId) => {
    const playerId = sendTargets[itemId];
    if (!playerId) {
      setError('Pick an online character to send to');
      return;
    }
    setError('');
    try {
      await api.inventory.send(token, itemId, parseInt(playerId, 10));
      loadInventory();
    } catch (err) {
      console.error('Send item error:', err);
      setError(err.message || 'Failed to send item');
    }
  };

  const statusBadge = (status) => {
    const map = { held: 'info', sending: 'warning', delivered: 'success', failed: 'danger' };
    return map[status] || 'secondary';
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
        <h2 className="mb-4 text-uppercase font-display">
          Rewards
        </h2>

        {dailyMsg && <div className="alert alert-success">{dailyMsg}</div>}
        {error && <div className="alert alert-danger">{error}</div>}

        {reveal && (
          <div className="alert alert-info">
            <strong>You opened a box and got:</strong>{' '}
            {reveal.length === 0 ? 'nothing (empty pool)' : reveal.map((i) => i.reward?.name).join(', ')}
            <button className="btn-close float-end" onClick={() => setReveal(null)}></button>
          </div>
        )}

        {/* Loot boxes */}
        <h5 className="font-display mb-3">My Loot Boxes</h5>
        {boxes.length === 0 ? (
          <p className="text-body-secondary">No unopened boxes. Come back tomorrow for another!</p>
        ) : (
          <div className="row g-3 mb-4">
            {boxes.map((box) => (
              <div key={box.id} className="col-md-3">
                <div className="card text-center h-100">
                  <div className="card-body">
                    <i className="fas fa-box-open fa-2x mb-2"></i>
                    <div className="mb-2">
                      <span className={`badge text-bg-${SIZE_BADGE[box.size] || 'secondary'}`}>{box.size}</span>
                    </div>
                    <button className="btn btn-danger btn-sm w-100" onClick={() => handleOpen(box.id)}>
                      Open
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Inventory */}
        <h5 className="font-display mb-3">My Inventory</h5>
        {inventory.length === 0 ? (
          <p className="text-body-secondary">Your inventory is empty. Open a box to win rewards!</p>
        ) : (
          <div className="table-responsive">
            <table className="table table-dark table-striped align-middle">
              <thead>
                <tr>
                  <th>Reward</th>
                  <th>Kind</th>
                  <th>Status</th>
                  <th>Send / Activate</th>
                </tr>
              </thead>
              <tbody>
                {inventory.map((item) => (
                  <tr key={item.id}>
                    <td>
                      {item.reward?.icon && (
                        <img src={item.reward.icon} alt="" style={{ width: '24px', height: '24px', objectFit: 'contain' }} className="me-2" />
                      )}
                      {item.reward?.name || `#${item.reward_id}`}
                    </td>
                    <td>{item.reward?.kind}</td>
                    <td><span className={`badge text-bg-${statusBadge(item.status)}`}>{item.status}</span></td>
                    <td>
                      {(item.status === 'held' || item.status === 'failed') ? (
                        <div className="input-group input-group-sm" style={{ maxWidth: '320px' }}>
                          <select
                            className="form-select"
                            value={sendTargets[item.id] || ''}
                            onChange={(e) => setSendTargets({ ...sendTargets, [item.id]: e.target.value })}
                          >
                            <option value="">
                              {onlinePlayers.length === 0 ? 'No online characters' : 'Select character…'}
                            </option>
                            {onlinePlayers.map((p) => (
                              <option key={p.id} value={p.id}>{p.in_game_username}</option>
                            ))}
                          </select>
                          <button
                            className="btn btn-danger"
                            disabled={onlinePlayers.length === 0}
                            onClick={() => handleSend(item.id)}
                          >
                            {item.reward?.kind === 'usable' ? 'Activate' : 'Send'}
                          </button>
                        </div>
                      ) : (
                        <span className="text-body-secondary">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

export default Rewards;
