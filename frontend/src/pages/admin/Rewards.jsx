// Admin › Rewards: create / list / delete reward definitions.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner, WIKI_COMMANDS, WIKI_ITEMS } from './helpers';
import ItemPicker from '../../components/ItemPicker';
import CommandLibrary from './CommandLibrary';

// One-line summary of what a usable reward will run, for the table. A sequence
// can span several lines; the table shows the first, and how many more there are.
const describeUsable = (reward) => {
  const lines = (reward.commands || '')
    .split(/[\n;]+/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0) {
    // Legacy catalog reward, kept deliverable but authored before free text.
    return reward.action_id || '—';
  }
  return lines.length > 1 ? `${lines[0]} +${lines.length - 1} more` : lines[0];
};

function Rewards() {
  const { token, isAdmin } = useAuth();
  const [rewards, setRewards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [rewardForm, setRewardForm] = useState({
    kind: 'item', name: '', description: '', icon: '', in_game_id: '', count: '1',
    commands: '', active: true
  });
  // null = creating a new reward; an id = editing that existing one.
  const [editingId, setEditingId] = useState(null);
  const [showItemPicker, setShowItemPicker] = useState(false);
  const [showCommandLibrary, setShowCommandLibrary] = useState(false);

  // Drop a picked command onto its own line, so several stack into a sequence.
  const insertCommand = (template) => {
    setRewardForm((current) => {
      const base = current.commands.replace(/\s+$/, '');
      return { ...current, commands: base ? `${base}\n${template}` : template };
    });
  };

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

  const resetForm = () => {
    setEditingId(null);
    setRewardForm({
      kind: 'item', name: '', description: '', icon: '', in_game_id: '', count: '1',
      commands: '', active: true
    });
  };

  // Load an existing reward into the form to edit it in place. The count is a
  // string here because the field is; the payload parses it back on submit.
  const startEdit = (reward) => {
    setEditingId(reward.id);
    setRewardForm({
      kind: reward.kind,
      name: reward.name || '',
      description: reward.description || '',
      icon: reward.icon || '',
      in_game_id: reward.in_game_id || '',
      count: String(reward.count || 1),
      commands: reward.commands || '',
      active: reward.active !== false
    });
    setError('');
    // The form sits below the table; bring it into view when it changes mode.
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
  };

  const handleSubmitReward = async (e) => {
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
      icon: rewardForm.icon.trim(),
      active: rewardForm.active
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
      if (!rewardForm.commands.trim()) {
        setError('Enter at least one command');
        return;
      }
      payload.commands = rewardForm.commands;
    }
    try {
      if (editingId) {
        await api.admin.rewards.update(token, editingId, payload);
      } else {
        await api.admin.rewards.create(token, payload);
      }
      resetForm();
      loadData();
    } catch (err) {
      console.error('Save reward error:', err);
      setError(err.message || 'Failed to save reward');
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
                          <div className="btn-group btn-group-sm">
                            <button
                              className="btn btn-outline-secondary"
                              onClick={() => startEdit(r)}
                              title="Edit this reward"
                            >
                              <i className="fas fa-pen"></i>
                            </button>
                            <button
                              className="btn btn-outline-danger"
                              onClick={() => handleDeleteReward(r.id)}
                              title="Delete this reward"
                            >
                              <i className="fas fa-trash"></i>
                            </button>
                          </div>
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
                  <h5 className="card-title font-display mb-0">
                    {editingId ? 'Edit Reward' : 'Add Reward'}
                  </h5>
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
                <form className="row g-2 align-items-end" onSubmit={handleSubmitReward}>
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
                    <div className="col-12">
                      <div className="d-flex justify-content-between align-items-baseline">
                        <label className="form-label text-body-secondary mb-1">Commands</label>
                        <button
                          type="button"
                          className="btn btn-sm btn-outline-secondary"
                          onClick={() => setShowCommandLibrary(true)}
                        >
                          <i className="fas fa-book me-1"></i> Browse commands
                        </button>
                      </div>
                      <textarea
                        className="form-control font-monospace"
                        rows={4}
                        spellCheck={false}
                        placeholder={'additem "{{USERNAME}}" "Base.Axe" 1\nsleep 0.5\nservermsg "Enjoy your prize!"'}
                        value={rewardForm.commands}
                        onChange={(e) => setRewardForm({ ...rewardForm, commands: e.target.value })}
                      />
                      <div className="form-text">
                        One command per line (or separated by <code>;</code>). Use{' '}
                        <code>{'{{USERNAME}}'}</code> for the recipient. Add{' '}
                        <code>sleep 0.5</code> or <code>wait 2</code> to pause before the
                        next command — pauses run in the panel and are not sent to the server.
                      </div>
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
                    <button type="submit" className="btn btn-danger w-100">
                      {editingId ? 'Save' : 'Add'}
                    </button>
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
                  <div className="col-12 d-flex justify-content-between align-items-center mt-2">
                    <div className="form-check">
                      <input
                        className="form-check-input"
                        type="checkbox"
                        id="reward-active"
                        checked={rewardForm.active}
                        onChange={(e) => setRewardForm({ ...rewardForm, active: e.target.checked })}
                      />
                      <label className="form-check-label text-body-secondary" htmlFor="reward-active">
                        Active (inactive rewards stay in pools but never drop)
                      </label>
                    </div>
                    {editingId && (
                      <button type="button" className="btn btn-outline-secondary" onClick={resetForm}>
                        Cancel
                      </button>
                    )}
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
      {showCommandLibrary && (
        <CommandLibrary
          onInsert={insertCommand}
          onClose={() => setShowCommandLibrary(false)}
        />
      )}
    </>
  );
}

export default Rewards;
