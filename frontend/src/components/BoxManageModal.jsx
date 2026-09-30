// Manage a single loot box in a modal: its identity (name, description, draws)
// and its loot pool (which rewards can drop, their quantities and weights). The
// parent owns the box data and the API calls; this component is the editing
// surface and shows its own errors so they sit over the box being edited.
import React, { useState, useEffect } from 'react';
import { useDialog } from '../context/DialogContext';

const pct = (n) => `${(100 * (n || 0)).toFixed(1)}%`;

// Each pool entry with its share of a single draw. Inactive rewards and
// zero-weight entries contribute nothing to the total.
const poolFor = (box) => {
  const entries = box.pool || [];
  const total = entries.reduce(
    (sum, e) => sum + (e.reward?.active ? (e.weight || 0) : 0), 0
  );
  return entries.map((e) => ({
    ...e,
    chance: total > 0 && e.reward?.active ? (e.weight || 0) / total : 0
  }));
};

function BoxManageModal({
  box, rewards, admin,
  onUpdateField, onDelete, onExport,
  onAddPool, onRemovePool, onReweight, onRecount,
  onClose
}) {
  const { confirm } = useDialog();
  const [error, setError] = useState('');
  const [addReward, setAddReward] = useState('');
  const [addCount, setAddCount] = useState('');

  // Escape closes, as it does everywhere else.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const entries = poolFor(box);

  // Wrap a throwing parent action so its error lands inside this modal.
  const run = (fn) => async (...args) => {
    setError('');
    try {
      await fn(...args);
    } catch (err) {
      console.error('Box manage action error:', err);
      setError(err.message || 'That action failed');
    }
  };

  const saveField = run(async (patch) => onUpdateField(box, patch));

  const handleAdd = run(async () => {
    if (!addReward) throw new Error('Select a reward to add');
    await onAddPool(box, {
      reward_id: parseInt(addReward, 10),
      count: parseInt(addCount, 10) || 1
    });
    setAddReward('');
    setAddCount('');
  });

  const handleDelete = run(async () => {
    if (!(await confirm({
      title: 'Delete box?',
      message: `Delete the "${box.name}" box? Its loot pool goes with it, and it is `
        + 'removed from any events it belongs to.',
      confirmLabel: 'Delete'
    }))) {
      return;
    }
    await onDelete(box);
  });

  const handleReweight = (entry, input) => {
    const weight = parseFloat(input.value);
    if (Number.isNaN(weight) || weight < 0) {
      input.value = entry.weight;
      return;
    }
    if (weight === entry.weight) return;
    run(() => onReweight(entry.id, weight))();
  };

  const handleRecount = (entry, input) => {
    const count = parseInt(input.value, 10);
    if (!Number.isInteger(count) || count < 1 || count > 1000) {
      input.value = entry.count;
      return;
    }
    if (count === entry.count) return;
    run(() => onRecount(entry.id, count))();
  };

  return (
    <div
      className="modal show d-block"
      style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
      onClick={onClose}
    >
      <div
        className="modal-dialog modal-dialog-centered modal-lg modal-dialog-scrollable"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title font-display">Manage box</h5>
            <button type="button" className="btn-close" onClick={onClose}></button>
          </div>

          <div className="modal-body">
            {error && <div className="alert alert-danger" role="alert">{error}</div>}

            {box.health && (box.health.empty || box.health.thin) && (
              <div className="alert alert-warning py-2">
                {box.health.empty
                  ? 'Nothing in this box can drop. A player who gets it will not be able to open it.'
                  : `This box draws ${box.health.draws} but only ${box.health.droppable} ` +
                    `reward${box.health.droppable === 1 ? '' : 's'} can drop, so it will repeat them.`}
              </div>
            )}

            {/* Identity */}
            <div className="row g-2 mb-3">
              <div className="col-md-6">
                <label className="form-label text-body-secondary small mb-1">Name</label>
                <input
                  className="form-control form-control-sm"
                  defaultValue={box.name}
                  disabled={!admin}
                  onBlur={(e) => {
                    const name = e.target.value.trim();
                    if (name && name !== box.name) saveField({ name });
                  }}
                />
              </div>
              <div className="col-md-4">
                <label className="form-label text-body-secondary small mb-1">Description</label>
                <input
                  className="form-control form-control-sm"
                  defaultValue={box.description}
                  disabled={!admin}
                  onBlur={(e) => {
                    const description = e.target.value.trim();
                    if (description !== (box.description || '')) saveField({ description });
                  }}
                />
              </div>
              <div className="col-md-2">
                <label className="form-label text-body-secondary small mb-1">Draws</label>
                <input
                  type="number"
                  min="0"
                  max="20"
                  className="form-control form-control-sm"
                  defaultValue={box.draws}
                  disabled={!admin}
                  onBlur={(e) => {
                    // A cleared field parses to NaN, which JSON sends as null
                    // and the API rejects. Put the current value back instead
                    // of turning a stray blur into an error banner.
                    const draws = parseInt(e.target.value, 10);
                    if (!Number.isInteger(draws) || draws < 0 || draws > 20) {
                      e.target.value = box.draws;
                      return;
                    }
                    if (draws !== box.draws) saveField({ draws });
                  }}
                />
              </div>
            </div>

            <h6 className="font-display mb-2">
              Loot pool
              <span className="text-body-secondary fw-normal ms-2">
                {box.draws} reward{box.draws === 1 ? '' : 's'} per open
              </span>
            </h6>

            {entries.length === 0 ? (
              <p className="text-body-secondary">Nothing in this pool yet.</p>
            ) : (
              <div className="table-responsive">
                <table className="table table-sm align-middle mb-2">
                  <thead>
                    <tr>
                      <th>Reward</th>
                      <th style={{ width: '7rem' }}>Qty</th>
                      <th style={{ width: '8rem' }}>Weight</th>
                      <th style={{ width: '6rem' }}>Chance</th>
                      <th style={{ width: '5rem' }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((entry) => (
                      <tr key={entry.id}>
                        <td>
                          <div className="d-flex align-items-center gap-2">
                            {entry.reward?.icon ? (
                              <img
                                src={entry.reward.icon}
                                alt=""
                                style={{ width: '28px', height: '28px', objectFit: 'contain' }}
                              />
                            ) : (
                              <span className="text-body-secondary" style={{ width: '28px', textAlign: 'center' }}>—</span>
                            )}
                            <span>
                              {entry.reward?.name || `#${entry.reward_id}`}
                              {entry.reward && !entry.reward.active && (
                                <span className="badge text-bg-secondary ms-2">inactive</span>
                              )}
                            </span>
                          </div>
                        </td>
                        <td>
                          {entry.reward?.kind === 'item' ? (
                            <input
                              type="number"
                              min="1"
                              max="1000"
                              className="form-control form-control-sm"
                              defaultValue={entry.count}
                              disabled={!admin}
                              onBlur={(e) => handleRecount(entry, e.target)}
                              title="How many of this item drop when it is picked"
                            />
                          ) : (
                            <span className="text-body-secondary" title="Quantity applies to items only">—</span>
                          )}
                        </td>
                        <td>
                          <input
                            type="number"
                            min="0"
                            step="0.5"
                            className="form-control form-control-sm"
                            defaultValue={entry.weight}
                            disabled={!admin}
                            onBlur={(e) => handleReweight(entry, e.target)}
                          />
                        </td>
                        <td className="text-body-secondary">
                          {entry.weight > 0 ? pct(entry.chance) : 'never'}
                        </td>
                        <td>
                          {admin && (
                            <button
                              className="btn btn-sm btn-outline-danger"
                              onClick={() => run(() => onRemovePool(entry.id))()}
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

            {admin && (
              <div className="row g-2 align-items-end">
                <div className="col-md-7">
                  <select
                    className="form-select"
                    value={addReward}
                    onChange={(e) => setAddReward(e.target.value)}
                  >
                    <option value="">Add a reward…</option>
                    {rewards
                      .filter((r) => !entries.some((e) => e.reward_id === r.id))
                      .map((r) => (
                        // An inactive reward can still be added - it is how you
                        // stage a pool before switching the reward on - but it
                        // says so, because it will not drop until you do.
                        <option key={r.id} value={r.id}>
                          {r.name}{r.active === false ? ' (inactive)' : ''}
                        </option>
                      ))}
                  </select>
                </div>
                <div className="col-md-2">
                  <input
                    type="number"
                    min="1"
                    max="1000"
                    className="form-control"
                    placeholder="Qty"
                    title="Item quantity (ignored for actions)"
                    value={addCount}
                    onChange={(e) => setAddCount(e.target.value)}
                  />
                </div>
                <div className="col-md-3">
                  <button className="btn btn-danger w-100" onClick={handleAdd}>
                    Add to pool
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* A moderator gets the footer too, so the read-only view has a way
              out other than the corner X. Delete and Export stay admin-only -
              the export endpoint is @admin_required, and a button that always
              403s is worse than no button. */}
          <div className="modal-footer justify-content-between">
            {admin ? (
              <button
                className="btn btn-outline-danger"
                onClick={handleDelete}
              >
                <i className="fas fa-trash me-1"></i> Delete box
              </button>
            ) : <span />}
            <div className="d-flex gap-2">
              {admin && (
                <button
                  className="btn btn-outline-secondary"
                  onClick={() => run(() => onExport(box))()}
                  title="Export this pool as a config file"
                >
                  <i className="fas fa-download me-1"></i> Export
                </button>
              )}
              <button className="btn btn-secondary" onClick={onClose}>
                <i className="fas fa-check me-1"></i> {admin ? 'Done' : 'Close'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default BoxManageModal;
