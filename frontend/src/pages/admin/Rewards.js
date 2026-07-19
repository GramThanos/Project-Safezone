// Admin › Rewards: create / list / delete reward definitions.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';

function Rewards() {
  const { token, isAdmin } = useAuth();
  const [rewards, setRewards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [rewardForm, setRewardForm] = useState({
    kind: 'item', name: '', description: '', icon: '', in_game_id: '', command_template: ''
  });

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api.admin.rewards.getAll(token);
      if (data.rewards) setRewards(data.rewards);
    } catch (err) {
      console.error('Load rewards error:', err);
      setError('Failed to load rewards');
    }
    setLoading(false);
  };

  const handleCreateReward = async (e) => {
    e.preventDefault();
    setError('');
    if (!rewardForm.name.trim()) {
      setError('Reward name is required');
      return;
    }
    const payload = {
      kind: rewardForm.kind,
      name: rewardForm.name.trim(),
      description: rewardForm.description.trim(),
      icon: rewardForm.icon.trim()
    };
    if (rewardForm.kind === 'item') {
      if (!rewardForm.in_game_id.trim()) {
        setError('An item id is required');
        return;
      }
      payload.in_game_id = rewardForm.in_game_id.trim();
    } else {
      if (!rewardForm.command_template.trim()) {
        setError('A command template is required');
        return;
      }
      payload.command_template = rewardForm.command_template.trim();
    }
    try {
      await api.admin.rewards.create(token, payload);
      setRewardForm({ kind: rewardForm.kind, name: '', description: '', icon: '', in_game_id: '', command_template: '' });
      loadData();
    } catch (err) {
      console.error('Create reward error:', err);
      setError(err.message || 'Failed to create reward');
    }
  };

  const handleDeleteReward = async (rewardId) => {
    if (!window.confirm('Delete this reward?')) return;
    setError('');
    try {
      await api.admin.rewards.delete(token, rewardId);
      loadData();
    } catch (err) {
      console.error('Delete reward error:', err);
      setError(err.message || 'Failed to delete reward');
    }
  };

  return (
    <>
      <h4 className="font-display mb-3">Rewards</h4>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}

      {loading ? <Spinner /> : (
        <>
          <div className="table-responsive">
            <table className="table table-dark table-striped align-middle">
              <thead>
                <tr>
                  <th>Icon</th>
                  <th>Name</th>
                  <th>Kind</th>
                  <th>Item id / Command</th>
                  <th>Active</th>
                  {isAdmin() && <th>Manage</th>}
                </tr>
              </thead>
              <tbody>
                {rewards.length === 0 ? (
                  <tr>
                    <td colSpan={isAdmin() ? 6 : 5} className="text-center">No rewards yet</td>
                  </tr>
                ) : (
                  rewards.map((r) => (
                    <tr key={r.id}>
                      <td>
                        {r.icon
                          ? <img src={r.icon} alt="" style={{ width: '28px', height: '28px', objectFit: 'contain' }} />
                          : <span className="text-body-secondary">—</span>}
                      </td>
                      <td>
                        {r.name}
                        {r.description && <div className="text-body-secondary">{r.description}</div>}
                      </td>
                      <td><span className="badge text-bg-info">{r.kind}</span></td>
                      <td><code>{r.kind === 'item' ? r.in_game_id : r.command_template}</code></td>
                      <td>{r.active ? 'Yes' : 'No'}</td>
                      {isAdmin() && (
                        <td>
                          <button className="btn btn-sm btn-outline-danger" onClick={() => handleDeleteReward(r.id)}>
                            <i className="fas fa-trash"></i>
                          </button>
                        </td>
                      )}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {isAdmin() && (
            <div className="card mt-4">
              <div className="card-body">
                <h5 className="card-title font-display mb-3">Add Reward</h5>
                <form className="row g-2 align-items-end" onSubmit={handleCreateReward}>
                  <div className="col-md-2">
                    <label className="form-label text-body-secondary">Kind</label>
                    <select
                      className="form-select"
                      value={rewardForm.kind}
                      onChange={(e) => setRewardForm({ ...rewardForm, kind: e.target.value })}
                    >
                      <option value="item">Item</option>
                      <option value="usable">Usable</option>
                    </select>
                  </div>
                  <div className="col-md-3">
                    <label className="form-label text-body-secondary">Name</label>
                    <input
                      type="text"
                      className="form-control"
                      value={rewardForm.name}
                      onChange={(e) => setRewardForm({ ...rewardForm, name: e.target.value })}
                    />
                  </div>
                  {rewardForm.kind === 'item' ? (
                    <div className="col-md-3">
                      <label className="form-label text-body-secondary">Item id</label>
                      <input
                        type="text"
                        className="form-control"
                        placeholder="Base.Axe"
                        value={rewardForm.in_game_id}
                        onChange={(e) => setRewardForm({ ...rewardForm, in_game_id: e.target.value })}
                      />
                    </div>
                  ) : (
                    <div className="col-md-3">
                      <label className="form-label text-body-secondary">Command (use {'{username}'})</label>
                      <input
                        type="text"
                        className="form-control"
                        placeholder={'godmode "{username}" -true'}
                        value={rewardForm.command_template}
                        onChange={(e) => setRewardForm({ ...rewardForm, command_template: e.target.value })}
                      />
                    </div>
                  )}
                  <div className="col-md-2">
                    <label className="form-label text-body-secondary">Icon URL</label>
                    <input
                      type="text"
                      className="form-control"
                      value={rewardForm.icon}
                      onChange={(e) => setRewardForm({ ...rewardForm, icon: e.target.value })}
                    />
                  </div>
                  <div className="col-md-2">
                    <button type="submit" className="btn btn-danger w-100">Add</button>
                  </div>
                  <div className="col-12">
                    <input
                      type="text"
                      className="form-control mt-2"
                      placeholder="Description (optional)"
                      value={rewardForm.description}
                      onChange={(e) => setRewardForm({ ...rewardForm, description: e.target.value })}
                    />
                  </div>
                </form>
              </div>
            </div>
          )}
        </>
      )}
    </>
  );
}

export default Rewards;
