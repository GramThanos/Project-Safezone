// Import a loot-box configuration into a box's pool — from the community list on
// GitHub, or from a local file exported earlier. Both sources produce the same
// config shape; the backend validates and applies either identically, creating
// any missing rewards and setting the pool's weights.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';

// A one-line summary of a config reward for the preview table.
const describeReward = (r) => {
  if (r.kind === 'item') return r.in_game_id || '—';
  const lines = (r.commands || '')
    .split(/[\n;]+/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0) return '—';
  return lines.length > 1 ? `${lines[0]} +${lines.length - 1} more` : lines[0];
};

// Sentinel target: create a brand-new box for this config rather than importing
// into an existing one. This is the default so an operator can bootstrap a box
// straight from a config without creating it first.
const NEW_BOX = '__new__';

// A config carries the box's draw count alongside its pool, so a three-draw box
// exported and re-imported is still a three-draw box. Older configs (and the
// community ones written before the field existed) have none, so fall back to
// one rather than guessing. Bounded to what the API accepts.
const configDraws = (cfg) => {
  const draws = parseInt(cfg?.draws, 10);
  if (!Number.isInteger(draws) || draws < 0) return 1;
  return Math.min(draws, 20);
};

function BoxConfigModal({ boxes, onCreateBox, onDiscardBox, onImported, onClose }) {
  const { token } = useAuth();
  const [tab, setTab] = useState('community');

  const [list, setList] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [listStale, setListStale] = useState('');

  const [config, setConfig] = useState(null);   // the loaded config being previewed
  const [targetBox, setTargetBox] = useState(NEW_BOX);
  const [newBoxName, setNewBoxName] = useState('');
  const [replace, setReplace] = useState(false);

  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    loadList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Escape closes, as it does everywhere else.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const loadList = async () => {
    setListLoading(true);
    setError('');
    try {
      const data = await api.admin.rewardBoxes.list(token);
      setList(data.boxes || []);
      setListStale(data.stale || '');
    } catch (err) {
      console.error('Load community boxes error:', err);
      setError(err.message || 'Could not load the community list');
    }
    setListLoading(false);
  };

  // A config is size-agnostic; the admin chooses which box it lands in. Prefill
  // the new-box name from the config so the common "create a box from this" path
  // is one click.
  const adoptConfig = (cfg) => {
    setConfig(cfg);
    setNewBoxName(cfg.name || '');
    setError('');
  };

  const chooseCommunity = async (id) => {
    setBusy(true);
    setError('');
    try {
      const data = await api.admin.rewardBoxes.get(token, id);
      adoptConfig(data.config);
    } catch (err) {
      console.error('Load community box error:', err);
      setError(err.message || 'Could not load that box config');
    }
    setBusy(false);
  };

  const chooseFile = (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const cfg = JSON.parse(reader.result);
        if (!cfg || !Array.isArray(cfg.rewards)) {
          setError('That file is not a box config (no rewards list).');
          return;
        }
        adoptConfig(cfg);
      } catch (err) {
        setError('That file is not valid JSON.');
      }
    };
    reader.readAsText(file);
  };

  const doImport = async () => {
    if (!config || !targetBox) return;
    setBusy(true);
    setError('');
    // Tracked so a failed pool import does not strand the box it just made.
    let createdBox = null;
    try {
      let boxId = targetBox;
      let boxName;
      if (targetBox === NEW_BOX) {
        const name = newBoxName.trim();
        if (!name) {
          setError('Give the new box a name');
          setBusy(false);
          return;
        }
        createdBox = await onCreateBox({
          name,
          description: config.description || '',
          draws: configDraws(config)
        });
        boxId = createdBox.id;
        boxName = createdBox.name;
      } else {
        boxName = boxes.find((b) => String(b.id) === String(targetBox))?.name || 'box';
      }
      const data = await api.admin.rewardBoxes.import(token, {
        box_id: boxId, config, replace
      });
      onImported(data.summary, boxName);
    } catch (err) {
      console.error('Import box config error:', err);
      // The two steps are one action to the operator, so a failure in the
      // second undoes the first: otherwise a retry hits "a box with that name
      // already exists" and an empty box is left behind either way. The box is
      // seconds old and cannot have been granted, so this always succeeds.
      if (createdBox && onDiscardBox) {
        try {
          await onDiscardBox(createdBox);
        } catch (cleanupErr) {
          console.error('Could not remove the half-created box:', cleanupErr);
        }
      }
      setError(err.message || 'Failed to import that config');
      setBusy(false);
    }
  };

  const rewards = (config && config.rewards) || [];

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
            <h5 className="modal-title font-display">Import box configuration</h5>
            <button type="button" className="btn-close" onClick={onClose}></button>
          </div>

          <div className="modal-body">
            {error && <div className="alert alert-danger" role="alert">{error}</div>}

            {!config ? (
              <>
                <ul className="nav nav-tabs mb-3">
                  <li className="nav-item">
                    <button
                      className={`nav-link ${tab === 'community' ? 'active' : ''}`}
                      onClick={() => setTab('community')}
                    >
                      Community
                    </button>
                  </li>
                  <li className="nav-item">
                    <button
                      className={`nav-link ${tab === 'file' ? 'active' : ''}`}
                      onClick={() => setTab('file')}
                    >
                      From file
                    </button>
                  </li>
                </ul>

                {tab === 'community' ? (
                  <>
                    {listStale && (
                      <div className="alert alert-warning py-2" role="alert">
                        This list could not be refreshed ({listStale}), so it may
                        be out of date.
                      </div>
                    )}
                    {listLoading ? (
                      <div className="text-center py-5">
                        <div className="spinner-border text-secondary" role="status">
                          <span className="visually-hidden">Loading…</span>
                        </div>
                      </div>
                    ) : list.length === 0 ? (
                      <p className="text-body-secondary py-3 mb-0">
                        No community box configurations are available.
                      </p>
                    ) : (
                      <div className="list-group list-group-flush">
                        {list.map((box) => (
                          <button
                            type="button"
                            key={box.id}
                            className="list-group-item list-group-item-action"
                            disabled={busy}
                            onClick={() => chooseCommunity(box.id)}
                          >
                            <div className="d-flex justify-content-between align-items-baseline">
                              <span className="fw-semibold">{box.name || box.id}</span>
                              {typeof box.rewards === 'number' && (
                                <span className="badge text-bg-secondary">
                                  {box.rewards} reward{box.rewards === 1 ? '' : 's'}
                                </span>
                              )}
                            </div>
                            {box.description && (
                              <div className="text-body-secondary small">{box.description}</div>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <div>
                    <label className="form-label text-body-secondary">
                      Choose a box config JSON file
                    </label>
                    <input
                      type="file"
                      accept="application/json,.json"
                      className="form-control"
                      onChange={chooseFile}
                    />
                    <div className="form-text">
                      Same format as the community configs — the kind you get from
                      a box's Export.
                    </div>
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="d-flex justify-content-between align-items-baseline mb-2">
                  <h6 className="mb-0">{config.name || 'Box configuration'}</h6>
                  <button
                    type="button"
                    className="btn btn-sm btn-link p-0"
                    onClick={() => setConfig(null)}
                  >
                    Choose a different one
                  </button>
                </div>
                {config.description && (
                  <p className="text-body-secondary small">{config.description}</p>
                )}

                <div className="table-responsive">
                  <table className="table table-sm align-middle">
                    <thead>
                      <tr>
                        <th>Reward</th>
                        <th>Kind</th>
                        <th>Item id / Action</th>
                        <th style={{ width: '5rem' }}>Weight</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rewards.map((r, i) => (
                        <tr key={i}>
                          <td>{r.name}{r.kind === 'item' && r.count > 1 ? ` ×${r.count}` : ''}</td>
                          <td><span className="badge text-bg-info">{r.kind}</span></td>
                          <td><code>{describeReward(r)}</code></td>
                          <td>{r.weight != null ? r.weight : 1}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="row g-2 align-items-end">
                  <div className="col-md-6">
                    <label className="form-label text-body-secondary">Import into box</label>
                    <select
                      className="form-select"
                      value={targetBox}
                      onChange={(e) => setTargetBox(e.target.value)}
                    >
                      <option value={NEW_BOX}>Create a new box…</option>
                      {boxes.length > 0 && (
                        <optgroup label="Existing boxes">
                          {boxes.map((b) => (
                            <option key={b.id} value={b.id}>{b.name}</option>
                          ))}
                        </optgroup>
                      )}
                    </select>
                  </div>
                  {targetBox === NEW_BOX ? (
                    <div className="col-md-6">
                      <label className="form-label text-body-secondary">New box name</label>
                      <input
                        className="form-control"
                        value={newBoxName}
                        onChange={(e) => setNewBoxName(e.target.value)}
                        placeholder="e.g. Halloween Crate"
                      />
                    </div>
                  ) : (
                    <div className="col-md-6">
                      <div className="form-check">
                        <input
                          className="form-check-input"
                          type="checkbox"
                          id="box-import-replace"
                          checked={replace}
                          onChange={(e) => setReplace(e.target.checked)}
                        />
                        <label className="form-check-label" htmlFor="box-import-replace">
                          Replace the pool (remove rewards not in this config)
                        </label>
                      </div>
                    </div>
                  )}
                </div>
                <div className="form-text mt-2">
                  {targetBox === NEW_BOX
                    ? `A new box is created with this config’s pool, drawing `
                      + `${configDraws(config)} reward`
                      + `${configDraws(config) === 1 ? '' : 's'} per open. `
                    : ''}
                  Rewards missing from the catalog are created; existing ones
                  (matched by name) are reused.
                  {targetBox === NEW_BOX
                    ? ''
                    : ' Leaving Replace off merges: it adds and reweights without removing anything.'}
                </div>
              </>
            )}
          </div>

          <div className="modal-footer">
            <button className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
            {config && (
              <button
                className="btn btn-danger"
                onClick={doImport}
                disabled={busy || !targetBox || (targetBox === NEW_BOX && !newBoxName.trim())}
              >
                {busy
                  ? (targetBox === NEW_BOX ? 'Creating…' : 'Importing…')
                  : (targetBox === NEW_BOX ? 'Create box' : 'Import')}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default BoxConfigModal;
