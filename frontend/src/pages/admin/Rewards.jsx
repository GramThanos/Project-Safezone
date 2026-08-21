// Admin › Rewards: create / list / delete reward definitions.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner, WIKI_COMMANDS, WIKI_ITEMS } from './helpers';
import ItemPicker from '../../components/ItemPicker';
import ActionPicker, { cleanParams } from './ActionPicker';

// One-line summary of what a usable reward will run, for the table.
const describeUsable = (reward) => {
  if (!reward.action_id) return '—';
  const params = Object.entries(reward.action_params || {})
    .map(([k, v]) => `${k}=${v}`)
    .join(' ');
  return params ? `${reward.action_id} ${params}` : reward.action_id;
};

function Rewards() {
  const { token, isAdmin } = useAuth();
  const [rewards, setRewards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [action, setAction] = useState(null);
  const [rewardForm, setRewardForm] = useState({
    kind: 'item', name: '', description: '', icon: '', in_game_id: '', count: '1',
    action_id: '', action_params: {}
  });
  const [showItemPicker, setShowItemPicker] = useState(false);

  // The catalog already knows the display name and has an icon; copying them
  // across saves retyping, and retyping is how a reward ends up named after a
  // different item than the one it delivers. Both stay editable.
  const applyPickedItem = (item) => {
    setRewardForm((current) => ({
      ...current,
      in_game_id: item.id,
      name: current.name.trim() || item.name,
      icon: current.icon.trim() || item.icon_url || ''
    }));
  };

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
      const count = parseInt(rewardForm.count, 10);
      if (!Number.isInteger(count) || count < 1 || count > 1000) {
        setError('Quantity must be a whole number between 1 and 1000');
        return;
      }
      payload.count = count;
    } else {
      if (!rewardForm.action_id) {
        setError('Select an action');
        return;
      }
      payload.action_id = rewardForm.action_id;
      payload.action_params = cleanParams(action, rewardForm.action_params);
    }
    try {
      await api.admin.rewards.create(token, payload);
      setRewardForm({
        kind: rewardForm.kind, name: '', description: '', icon: '', in_game_id: '', count: '1',
        action_id: '', action_params: {}
      });
      setAction(null);
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
            <table className="table table-striped align-middle">
              <thead>
                <tr>
                  <th>Icon</th>
                  <th>Name</th>
                  <th>Kind</th>
                  <th>Item id / Action</th>
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
                      <td>
                        <code>{r.kind === 'item' ? r.in_game_id : describeUsable(r)}</code>
                        {r.kind === 'item' && r.count > 1 && (
                          <span className="badge text-bg-secondary ms-2">×{r.count}</span>
                        )}
                      </td>
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
                <div className="d-flex flex-wrap justify-content-between align-items-baseline gap-2 mb-3">
                  <h5 className="card-title font-display mb-0">Add Reward</h5>
                  <span className="small">
                    <a
                      className="link-secondary"
                      href={WIKI_ITEMS}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Item list <i className="fas fa-arrow-up-right-from-square"></i>
                    </a>
                    <span className="text-body-secondary mx-2">&middot;</span>
                    <a
                      className="link-secondary"
                      href={WIKI_COMMANDS}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Admin commands <i className="fas fa-arrow-up-right-from-square"></i>
                    </a>
                  </span>
                </div>
                <form className="row g-2 align-items-end" onSubmit={handleCreateReward}>
                  <div className="col-md-2">
                    <label className="form-label text-body-secondary">Kind</label>
                    <select
                      className="form-select"
                      value={rewardForm.kind}
                      onChange={(e) => setRewardForm({ ...rewardForm, kind: e.target.value })}
                    >
                      <option value="item">Item</option>
                      <option value="usable">Action</option>
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
                    <>
                      <div className="col-md-3">
                        <label className="form-label text-body-secondary">
                          Item id
                          <a
                            className="link-secondary ms-2"
                            href={WIKI_ITEMS}
                            target="_blank"
                            rel="noopener noreferrer"
                            title="Look up item ids on PZwiki"
                          >
                            <i className="fas fa-circle-question"></i>
                          </a>
                        </label>
                        <div className="input-group">
                          <input
                            type="text"
                            className="form-control"
                            placeholder="Base.Axe"
                            value={rewardForm.in_game_id}
                            onChange={(e) => setRewardForm({ ...rewardForm, in_game_id: e.target.value })}
                          />
                          <button
                            type="button"
                            className="btn btn-outline-secondary"
                            onClick={() => setShowItemPicker(true)}
                            title="Browse the in-game item list"
                          >
                            <i className="fas fa-magnifying-glass"></i>
                          </button>
                        </div>
                      </div>
                      <div className="col-md-2">
                        <label className="form-label text-body-secondary">Quantity</label>
                        <input
                          type="number"
                          min="1"
                          max="1000"
                          className="form-control"
                          value={rewardForm.count}
                          onChange={(e) => setRewardForm({ ...rewardForm, count: e.target.value })}
                        />
                      </div>
                    </>
                  ) : (
                    <ActionPicker
                      droppableOnly
                      actionId={rewardForm.action_id}
                      params={rewardForm.action_params}
                      onChange={({ action_id, action_params, action: picked }) => {
                        setAction(picked);
                        setRewardForm({ ...rewardForm, action_id, action_params });
                      }}
                    />
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
      {showItemPicker && (
        <ItemPicker
          onSelect={applyPickedItem}
          onClose={() => setShowItemPicker(false)}
        />
      )}
    </>
  );
}

export default Rewards;
