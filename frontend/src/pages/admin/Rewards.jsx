// Admin › Rewards: create / list / delete reward definitions.
//
// The list lives in a card-wrapped table: create a reward from the "Add reward"
// modal, then edit an existing one from its row's pencil. The add/edit form is
// owned by RewardModal.
import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useDialog } from '../../context/DialogContext';
import api from '../../services/api';
import { Spinner } from './helpers';
import RewardModal from './RewardModal';
import Coins from '../../components/Coins';
import { downloadJson, readJsonFile } from '../../utils/jsonTransfer';

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
  const { confirm } = useDialog();
  const admin = isAdmin();
  const [rewards, setRewards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  // false = modal closed; null = creating; a reward object = editing that one.
  const [modalReward, setModalReward] = useState(false);
  const [busy, setBusy] = useState(false);
  const importInput = useRef(null);

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

  // Save from the modal: throws on failure so the modal surfaces it over its own
  // content, and reloads the list on success.
  const saveReward = async (payload) => {
    if (modalReward) {
      await api.admin.rewards.update(token, modalReward.id, payload);
    } else {
      await api.admin.rewards.create(token, payload);
    }
    await loadData();
  };

  const handleDeleteReward = async (rewardId) => {
    if (!(await confirm({ title: 'Delete reward?', message: 'Delete this reward?', confirmLabel: 'Delete' }))) return;
    setError('');
    setNotice('');
    try {
      await api.admin.rewards.delete(token, rewardId);
      loadData();
    } catch (err) {
      console.error('Delete reward error:', err);
      setError(err.message || 'Failed to delete reward');
    }
  };

  const exportRewards = () => {
    // IDs are intentionally excluded: imported rewards get the local database's
    // IDs, while item IDs/names provide stable duplicate detection.
    downloadJson({
      type: 'project-safezone-rewards', version: 1,
      rewards: rewards.map(({ kind, name, description, icon, in_game_id, commands, active, coin_value }) =>
        ({ kind, name, description, icon, in_game_id, commands, active, coin_value }))
    }, 'project-safezone-rewards.json');
  };

  const rewardKey = (reward) => reward?.kind === 'item'
    ? `item:${reward.in_game_id || ''}` : `usable:${String(reward?.name || '').trim().toLowerCase()}`;

  const importRewards = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setError('');
    try {
      const data = await readJsonFile(file);
      if (data?.type !== 'project-safezone-rewards' || data.version !== 1 || !Array.isArray(data.rewards)) {
        throw new Error('Choose a Project Safezone rewards export file.');
      }
      if (data.rewards.length > 500) throw new Error('A rewards import may contain at most 500 rewards.');
      const existing = new Set(rewards.map(rewardKey));
      const incoming = new Set();
      const add = data.rewards.filter((reward) => {
        const key = rewardKey(reward);
        if (existing.has(key) || incoming.has(key)) return false;
        incoming.add(key);
        return true;
      });
      setBusy(true);
      for (const reward of add) await api.admin.rewards.create(token, reward);
      await loadData();
      setError('');
      const skipped = data.rewards.length - add.length;
      window.scrollTo({ top: 0, behavior: 'smooth' });
      setNotice(`Imported ${add.length} reward(s)${skipped ? `; skipped ${skipped} already present.` : '.'}`);
    } catch (err) {
      setError(err.message || 'Could not import rewards.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="d-flex flex-wrap justify-content-between align-items-baseline gap-2">
        <h4 className="font-display mb-1">Rewards</h4>
        {admin && (
          <div className="d-flex gap-2">
            <input ref={importInput} type="file" accept="application/json,.json" className="d-none"
              onChange={importRewards} />
            <button className="btn btn-sm btn-outline-secondary" onClick={() => importInput.current?.click()} disabled={busy}>
              <i className="fas fa-upload me-1"></i> Import
            </button>
            <button className="btn btn-sm btn-outline-secondary" onClick={exportRewards} disabled={busy}>
              <i className="fas fa-download me-1"></i> Export
            </button>
            <button className="btn btn-sm btn-danger" onClick={() => setModalReward(null)} disabled={busy}>
              <i className="fas fa-plus me-1"></i> Add reward
            </button>
          </div>
        )}
      </div>
      <p className="text-body-secondary">
        Define the items and actions that loot boxes can drop. Export JSON to move
        the catalogue between servers; imports add missing rewards and leave existing ones unchanged.
      </p>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      {loading ? <Spinner /> : (
        rewards.length === 0 ? (
          <p className="text-body-secondary">
            No rewards yet.{admin && ' Use “Add reward” to create one.'}
          </p>
        ) : (
          <div className="card">
            <div className="table-responsive">
              <table className="table table-hover align-middle mb-0">
                <thead>
                  <tr>
                    <th style={{ width: '4rem' }}>Icon</th>
                    <th>Name</th>
                    <th style={{ width: '6rem' }}>Kind</th>
                    <th>Item id / Action</th>
                    <th style={{ width: '5rem' }} title="What the reward sells back for, in coins">Value</th>
                    <th style={{ width: '5rem' }}>Active</th>
                    {admin && <th style={{ width: '6rem' }}></th>}
                  </tr>
                </thead>
                <tbody>
                  {rewards.map((r) => (
                    <tr key={r.id}>
                      <td>
                        {r.icon
                          ? <img src={r.icon} alt="" style={{ width: '28px', height: '28px', objectFit: 'contain' }} />
                          : <span className="text-body-secondary">—</span>}
                      </td>
                      <td>
                        <span className="fw-semibold">{r.name}</span>
                        {r.description && <div className="text-body-secondary">{r.description}</div>}
                      </td>
                      <td><span className="badge text-bg-info">{r.kind}</span></td>
                      <td>
                        <code>{r.kind === 'item' ? r.in_game_id : describeUsable(r)}</code>
                      </td>
                      <td><Coins amount={r.coin_value} /></td>
                      <td>{r.active ? 'Yes' : 'No'}</td>
                      {admin && (
                        <td className="text-end">
                          <div className="btn-group btn-group-sm">
                            <button
                              className="btn btn-outline-secondary"
                              onClick={() => setModalReward(r)}
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
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      )}

      {admin && modalReward !== false && (
        <RewardModal
          reward={modalReward}
          onSave={saveReward}
          onClose={() => setModalReward(false)}
        />
      )}
    </>
  );
}

export default Rewards;
