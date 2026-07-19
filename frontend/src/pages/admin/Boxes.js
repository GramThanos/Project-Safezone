// Admin › Loot Boxes: configure the reward pool for each box size.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';

const BOX_SIZES = [
  { size: 'small', draws: 1, weight: '60%' },
  { size: 'medium', draws: 2, weight: '30%' },
  { size: 'big', draws: 3, weight: '10%' }
];

function Boxes() {
  const { token, isAdmin } = useAuth();
  const [boxPools, setBoxPools] = useState([]);
  const [rewards, setRewards] = useState([]);
  const [poolAdd, setPoolAdd] = useState({ small: '', medium: '', big: '' });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      const [poolsData, rewardsData] = await Promise.all([
        api.admin.boxPools.getAll(token),
        api.admin.rewards.getAll(token)
      ]);
      if (poolsData.pools) setBoxPools(poolsData.pools);
      if (rewardsData.rewards) setRewards(rewardsData.rewards);
    } catch (err) {
      console.error('Load boxes error:', err);
      setError('Failed to load loot boxes');
    }
    setLoading(false);
  };

  const handleAddPool = async (size) => {
    const reward_id = poolAdd[size];
    if (!reward_id) {
      setError('Select a reward to add');
      return;
    }
    setError('');
    try {
      await api.admin.boxPools.add(token, { size, reward_id: parseInt(reward_id, 10) });
      setPoolAdd({ ...poolAdd, [size]: '' });
      loadData();
    } catch (err) {
      console.error('Add pool error:', err);
      setError(err.message || 'Failed to add reward to pool');
    }
  };

  const handleRemovePool = async (id) => {
    setError('');
    try {
      await api.admin.boxPools.delete(token, id);
      loadData();
    } catch (err) {
      console.error('Remove pool error:', err);
      setError(err.message || 'Failed to remove from pool');
    }
  };

  return (
    <>
      <h4 className="font-display mb-3">Loot Boxes</h4>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}

      {loading ? <Spinner /> : (
        <div className="row g-3">
          {BOX_SIZES.map(({ size, draws, weight }) => {
            const entries = boxPools.filter((p) => p.size === size);
            return (
              <div key={size} className="col-md-4">
                <div className="card h-100">
                  <div className="card-body">
                    <h5 className="card-title font-display text-capitalize mb-1">{size} box</h5>
                    <p className="text-body-secondary">Drops {draws} · grant chance {weight}</p>
                    <ul className="list-group list-group-flush mb-3">
                      {entries.length === 0 ? (
                        <li className="list-group-item text-body-secondary">
                          No rewards in this pool
                        </li>
                      ) : (
                        entries.map((e) => (
                          <li key={e.id} className="list-group-item d-flex justify-content-between align-items-center">
                            <span>{e.reward?.name || `#${e.reward_id}`}{' '}
                              <span className="badge text-bg-info">{e.reward?.kind}</span>
                            </span>
                            {isAdmin() && (
                              <button className="btn btn-sm btn-outline-danger" onClick={() => handleRemovePool(e.id)}>
                                <i className="fas fa-times"></i>
                              </button>
                            )}
                          </li>
                        ))
                      )}
                    </ul>
                    {isAdmin() && (
                      <div className="input-group input-group-sm">
                        <select
                          className="form-select"
                          value={poolAdd[size]}
                          onChange={(e) => setPoolAdd({ ...poolAdd, [size]: e.target.value })}
                        >
                          <option value="">Add reward…</option>
                          {rewards.map((r) => (
                            <option key={r.id} value={r.id}>{r.name} ({r.kind})</option>
                          ))}
                        </select>
                        <button className="btn btn-danger" onClick={() => handleAddPool(size)}>Add</button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

export default Boxes;
