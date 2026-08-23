// Admin › Loot Boxes: the reward pool for each box size, and the two numbers
// that shape the economy — how likely each size is, and how likely each reward
// is within it.
//
// Both used to be hardcoded. The point of this page is that tuning a season no
// longer needs a redeploy.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';
import BoxConfigModal from '../../components/BoxConfigModal';

const pct = (n) => `${(100 * (n || 0)).toFixed(1)}%`;

// A filename slug from a config name — a bare name-slug, no hash.
const slugify = (name) => (name || 'box')
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, '-')
  .replace(/^-+|-+$/g, '') || 'box';

function Boxes() {
  const { token, isAdmin } = useAuth();
  const [boxPools, setBoxPools] = useState([]);
  const [health, setHealth] = useState([]);
  const [boxTypes, setBoxTypes] = useState([]);
  const [rewards, setRewards] = useState([]);
  const [poolAdd, setPoolAdd] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showImport, setShowImport] = useState(false);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setError('');
    try {
      const [poolsData, rewardsData, typesData] = await Promise.all([
        api.admin.boxPools.getAll(token),
        api.admin.rewards.getAll(token),
        api.admin.boxTypes.getAll(token)
      ]);
      setBoxPools(poolsData.pools || []);
      setHealth(poolsData.health || []);
      setRewards(rewardsData.rewards || []);
      setBoxTypes(typesData.box_types || []);
    } catch (err) {
      console.error('Load boxes error:', err);
      setError('Failed to load loot boxes');
    }
    setLoading(false);
  };

  const handleAddPool = async (size) => {
    const rewardId = poolAdd[size];
    if (!rewardId) {
      setError('Select a reward to add');
      return;
    }
    setError('');
    setNotice('');
    try {
      await api.admin.boxPools.add(token, {
        size,
        reward_id: parseInt(rewardId, 10),
        weight: 1
      });
      setPoolAdd({ ...poolAdd, [size]: '' });
      loadData();
    } catch (err) {
      console.error('Add pool error:', err);
      setError(err.message || 'Failed to add reward to pool');
    }
  };

  const handleRemovePool = async (id) => {
    setError('');
    setNotice('');
    try {
      await api.admin.boxPools.remove(token, id);
      loadData();
    } catch (err) {
      console.error('Remove pool error:', err);
      setError(err.message || 'Failed to remove reward from pool');
    }
  };

  const handleReweight = async (entry, input) => {
    const weight = parseFloat(input.value);
    if (Number.isNaN(weight) || weight < 0) {
      // Blanked or nonsense: put the field back, rather than leaving it showing
      // a weight that was never saved.
      input.value = entry.weight;
      return;
    }
    if (weight === entry.weight) return;
    setError('');
    try {
      await api.admin.boxPools.setWeight(token, entry.id, weight);
      loadData();
    } catch (err) {
      console.error('Reweight error:', err);
      setError(err.message || 'Failed to change that weight');
    }
  };

  const handleTypeChange = async (size, patch) => {
    setError('');
    setNotice('');
    try {
      await api.admin.boxTypes.update(token, size, patch);
      setNotice('Box tuning saved. New grants use it immediately.');
      loadData();
    } catch (err) {
      console.error('Box type error:', err);
      setError(err.message || 'Failed to update that box type');
    }
  };

  const handleImported = (summary, size) => {
    setShowImport(false);
    setError('');
    const s = summary || {};
    setNotice(
      `Imported into the ${size} box: ${s.created || 0} reward(s) created, ` +
      `${s.added || 0} added to the pool, ${s.reweighted || 0} reweighted` +
      (s.removed ? `, ${s.removed} removed` : '') + '.'
    );
    loadData();
  };

  // Export one size's pool as a config file. The name and description are the
  // config's own metadata (not stored anywhere), so they are asked for here.
  const handleExport = async (size, label) => {
    const name = window.prompt('Name for this box configuration:', `${label} box`);
    if (name === null) return;
    const description = window.prompt('Short description (optional):', '') || '';
    setError('');
    try {
      const config = await api.admin.rewardBoxes.export(token, { size, name, description });
      const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${slugify(name)}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export box config error:', err);
      setError(err.message || 'Failed to export that box');
    }
  };

  // Entries for one size, with each reward's share of a single draw.
  const poolFor = (size) => {
    const entries = boxPools.filter((p) => p.size === size);
    const total = entries.reduce(
      (sum, e) => sum + (e.reward?.active ? (e.weight || 0) : 0), 0
    );
    return entries.map((e) => ({
      ...e,
      chance: total > 0 && e.reward?.active ? (e.weight || 0) / total : 0
    }));
  };

  if (loading) return <Spinner />;

  return (
    <>
      <div className="d-flex flex-wrap justify-content-between align-items-baseline gap-2">
        <h4 className="font-display mb-1">Loot Boxes</h4>
        {isAdmin() && (
          <button className="btn btn-sm btn-outline-secondary" onClick={() => setShowImport(true)}>
            <i className="fas fa-download me-1"></i> Import config
          </button>
        )}
      </div>
      <p className="text-body-secondary">
        Weights are relative, not percentages: a reward at 10 is ten times as
        likely as one at 1. Setting a weight to 0 keeps a reward in the pool but
        stops it dropping — a way to retire something without losing the record
        of who won it.
      </p>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      {/* Pool health first: an empty pool is a box a player cannot open. */}
      {health.some((h) => h.empty || h.thin) && (
        <div className="alert alert-warning">
          {health.filter((h) => h.empty).map((h) => (
            <div key={h.size}>
              <strong>{h.label}</strong> has nothing that can drop. A player who
              gets this box will not be able to open it.
            </div>
          ))}
          {health.filter((h) => h.thin).map((h) => (
            <div key={h.size}>
              <strong>{h.label}</strong> draws {h.draws} but only {h.droppable}{' '}
              reward{h.droppable === 1 ? '' : 's'} can drop, so it will repeat them.
            </div>
          ))}
        </div>
      )}

      {/* Box tuning */}
      <div className="card mb-4">
        <div className="card-body">
          <h5 className="card-title font-display mb-3">Box types</h5>
          <div className="table-responsive">
            <table className="table align-middle mb-0">
              <thead>
                <tr>
                  <th>Box</th>
                  <th>Rewards per box</th>
                  <th>Daily weight</th>
                  <th>Chance</th>
                  <th>Active</th>
                </tr>
              </thead>
              <tbody>
                {boxTypes.map((t) => (
                  <tr key={t.size}>
                    <td>{t.label}</td>
                    <td style={{ maxWidth: '8rem' }}>
                      <input
                        type="number"
                        min="0"
                        max="20"
                        className="form-control form-control-sm"
                        defaultValue={t.draws}
                        disabled={!isAdmin()}
                        onBlur={(e) => {
                          const draws = parseInt(e.target.value, 10);
                          if (draws !== t.draws) handleTypeChange(t.size, { draws });
                        }}
                      />
                    </td>
                    <td style={{ maxWidth: '8rem' }}>
                      <input
                        type="number"
                        min="0"
                        step="0.1"
                        className="form-control form-control-sm"
                        defaultValue={t.weight}
                        disabled={!isAdmin()}
                        onBlur={(e) => {
                          const weight = parseFloat(e.target.value);
                          if (weight !== t.weight) handleTypeChange(t.size, { weight });
                        }}
                      />
                    </td>
                    <td className="text-body-secondary">
                      {t.weight > 0 ? pct(t.daily_chance) : 'never rolled'}
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        className="form-check-input"
                        checked={t.active}
                        disabled={!isAdmin()}
                        onChange={(e) => handleTypeChange(t.size, { active: e.target.checked })}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="form-text mt-2">
            A weight of 0 means the box is never rolled on login. That is how the
            weekly bonus box exists without being obtainable daily.
          </div>
        </div>
      </div>

      {/* Per-size pools */}
      {boxTypes.map((type) => {
        const entries = poolFor(type.size);
        return (
          <div className="card mb-3" key={type.size}>
            <div className="card-body">
              <div className="d-flex justify-content-between align-items-baseline">
                <h5 className="card-title font-display mb-1">
                  {type.label}
                  <span className="text-body-secondary fs-6 ms-2">
                    {type.draws} reward{type.draws === 1 ? '' : 's'} per box
                  </span>
                </h5>
                {isAdmin() && (
                  <button
                    className="btn btn-sm btn-outline-secondary"
                    onClick={() => handleExport(type.size, type.label)}
                    title="Export this pool as a config file"
                  >
                    <i className="fas fa-upload me-1"></i> Export
                  </button>
                )}
              </div>

              {entries.length === 0 ? (
                <p className="text-body-secondary">Nothing in this pool yet.</p>
              ) : (
                <div className="table-responsive">
                  <table className="table table-sm align-middle mb-2">
                    <thead>
                      <tr>
                        <th>Reward</th>
                        <th style={{ width: '8rem' }}>Weight</th>
                        <th style={{ width: '6rem' }}>Chance</th>
                        <th style={{ width: '5rem' }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {entries.map((entry) => (
                        <tr key={entry.id}>
                          <td>
                            {entry.reward?.name || `#${entry.reward_id}`}
                            {entry.reward && !entry.reward.active && (
                              <span className="badge text-bg-secondary ms-2">inactive</span>
                            )}
                          </td>
                          <td>
                            <input
                              type="number"
                              min="0"
                              step="0.5"
                              className="form-control form-control-sm"
                              defaultValue={entry.weight}
                              disabled={!isAdmin()}
                              onBlur={(e) => handleReweight(entry, e.target)}
                            />
                          </td>
                          <td className="text-body-secondary">
                            {entry.weight > 0 ? pct(entry.chance) : 'never'}
                          </td>
                          <td>
                            {isAdmin() && (
                              <button
                                className="btn btn-sm btn-outline-danger"
                                onClick={() => handleRemovePool(entry.id)}
                              >
                                Remove
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {isAdmin() && (
                <div className="row g-2 align-items-end">
                  <div className="col-md-8">
                    <select
                      className="form-select"
                      value={poolAdd[type.size] || ''}
                      onChange={(e) => setPoolAdd({ ...poolAdd, [type.size]: e.target.value })}
                    >
                      <option value="">Add a reward…</option>
                      {rewards
                        .filter((r) => !entries.some((e) => e.reward_id === r.id))
                        .map((r) => (
                          <option key={r.id} value={r.id}>{r.name}</option>
                        ))}
                    </select>
                  </div>
                  <div className="col-md-4">
                    <button
                      className="btn btn-danger w-100"
                      onClick={() => handleAddPool(type.size)}
                    >
                      Add to pool
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })}

      {showImport && (
        <BoxConfigModal
          sizes={boxTypes.map((t) => ({ size: t.size, label: t.label }))}
          onImported={handleImported}
          onClose={() => setShowImport(false)}
        />
      )}
    </>
  );
}

export default Boxes;
