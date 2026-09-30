// Create a new loot box: just its identity (name, description, draw count). The
// loot pool is filled in afterwards from the box's Manage view. The parent owns
// the create call; this component collects the fields and shows its own errors.
import React, { useState, useEffect } from 'react';

function BoxCreateModal({ onCreate, onClose }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [draws, setDraws] = useState(1);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  // Escape closes, as it does everywhere else.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const submit = async () => {
    if (!name.trim()) {
      setError('Give the box a name');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await onCreate({
        name: name.trim(),
        description: description.trim(),
        draws: parseInt(draws, 10) || 1
      });
      onClose();
    } catch (err) {
      console.error('Create box error:', err);
      setError(err.message || 'Failed to create that box');
      setBusy(false);
    }
  };

  return (
    <div
      className="modal show d-block"
      style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
      onClick={onClose}
    >
      <div
        className="modal-dialog modal-dialog-centered"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title font-display">New box</h5>
            <button type="button" className="btn-close" onClick={onClose}></button>
          </div>

          <div className="modal-body">
            {error && <div className="alert alert-danger" role="alert">{error}</div>}
            <div className="row g-2">
              <div className="col-12">
                <label className="form-label text-body-secondary small mb-1">Name</label>
                <input
                  className="form-control"
                  placeholder="e.g. Halloween Crate"
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <div className="col-md-9">
                <label className="form-label text-body-secondary small mb-1">Description (optional)</label>
                <input
                  className="form-control"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>
              <div className="col-md-3">
                <label className="form-label text-body-secondary small mb-1">Draws</label>
                <input
                  type="number"
                  min="0"
                  max="20"
                  className="form-control"
                  value={draws}
                  onChange={(e) => setDraws(e.target.value)}
                />
              </div>
            </div>
            <div className="form-text mt-2">
              After creating the box, open its Manage view to fill the loot pool,
              then add it to an event to start granting it.
            </div>
          </div>

          <div className="modal-footer">
            <button className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
            <button className="btn btn-danger" onClick={submit} disabled={busy}>
              {busy ? 'Creating…' : 'Create box'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default BoxCreateModal;
