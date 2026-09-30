// Create or edit a reward definition. A reward is either an item (delivered by
// in-game id) or a usable action (a free-text command sequence). The parent owns
// the save call; this modal collects the fields, shows its own errors, and hosts
// the item picker and command library it can open on top of itself.
import React, { useState, useEffect } from 'react';
import { WIKI_COMMANDS, WIKI_ITEMS } from './helpers';
import ItemPicker from '../../components/ItemPicker';
import CommandLibrary from './CommandLibrary';

const emptyForm = {
  kind: 'item', name: '', description: '', icon: '', in_game_id: '',
  commands: '', active: true
};

// Turn an existing reward into form state; falls back to a blank create form.
const formFromReward = (reward) => reward ? {
  kind: reward.kind,
  name: reward.name || '',
  description: reward.description || '',
  icon: reward.icon || '',
  in_game_id: reward.in_game_id || '',
  commands: reward.commands || '',
  active: reward.active !== false
} : { ...emptyForm };

function RewardModal({ reward, onSave, onClose }) {
  const editing = Boolean(reward);
  const [form, setForm] = useState(() => formFromReward(reward));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [showItemPicker, setShowItemPicker] = useState(false);
  const [showCommandLibrary, setShowCommandLibrary] = useState(false);

  // Escape closes, as it does everywhere else — but not while a picker sits on
  // top of us, where Escape should close the picker first.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape' && !showItemPicker && !showCommandLibrary) onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, showItemPicker, showCommandLibrary]);

  // Drop a picked command onto its own line, so several stack into a sequence.
  const insertCommand = (template) => {
    setForm((current) => {
      const base = current.commands.replace(/\s+$/, '');
      return { ...current, commands: base ? `${base}\n${template}` : template };
    });
  };

  // The catalog already knows the display name and has an icon; copying them
  // across saves retyping, and retyping is how a reward ends up named after a
  // different item than the one it delivers. Both stay editable.
  const applyPickedItem = (item) => {
    setForm((current) => ({
      ...current,
      in_game_id: item.id,
      name: current.name.trim() || item.name,
      icon: current.icon.trim() || item.icon_url || ''
    }));
  };

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (!form.name.trim()) {
      setError('Reward name is required');
      return;
    }
    const payload = {
      kind: form.kind,
      name: form.name.trim(),
      description: form.description.trim(),
      icon: form.icon.trim(),
      active: form.active
    };
    if (form.kind === 'item') {
      if (!form.in_game_id.trim()) {
        setError('An item id is required');
        return;
      }
      payload.in_game_id = form.in_game_id.trim();
    } else {
      if (!form.commands.trim()) {
        setError('Enter at least one command');
        return;
      }
      payload.commands = form.commands;
    }
    setBusy(true);
    try {
      await onSave(payload);
      onClose();
    } catch (err) {
      console.error('Save reward error:', err);
      setError(err.message || 'Failed to save reward');
      setBusy(false);
    }
  };

  return (
    <>
      <div
        className="modal show d-block"
        style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
        onClick={onClose}
      >
        <div
          className="modal-dialog modal-dialog-centered modal-lg"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="modal-content">
            <div className="modal-header">
              <h5 className="modal-title font-display">
                {editing ? 'Edit reward' : 'New reward'}
              </h5>
              <button type="button" className="btn-close" onClick={onClose}></button>
            </div>

            <form onSubmit={submit}>
              <div className="modal-body">
                {error && <div className="alert alert-danger" role="alert">{error}</div>}

                <div className="d-flex justify-content-end mb-2">
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

                <div className="row g-2 align-items-end">
                  <div className="col-md-3">
                    <label className="form-label text-body-secondary small mb-1">Kind</label>
                    <select
                      className="form-select"
                      value={form.kind}
                      onChange={(e) => setForm({ ...form, kind: e.target.value })}
                    >
                      <option value="item">Item</option>
                      <option value="usable">Action</option>
                    </select>
                  </div>
                  <div className="col-md-5">
                    <label className="form-label text-body-secondary small mb-1">Name</label>
                    <input
                      type="text"
                      className="form-control"
                      value={form.name}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                    />
                  </div>
                  <div className="col-md-4">
                    <label className="form-label text-body-secondary small mb-1">Icon URL</label>
                    <input
                      type="text"
                      className="form-control"
                      value={form.icon}
                      onChange={(e) => setForm({ ...form, icon: e.target.value })}
                    />
                  </div>

                  {form.kind === 'item' ? (
                    <div className="col-12">
                      <label className="form-label text-body-secondary small mb-1">
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
                          value={form.in_game_id}
                          onChange={(e) => setForm({ ...form, in_game_id: e.target.value })}
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
                  ) : (
                    <div className="col-12">
                      <div className="d-flex justify-content-between align-items-baseline">
                        <label className="form-label text-body-secondary small mb-1">Commands</label>
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
                        value={form.commands}
                        onChange={(e) => setForm({ ...form, commands: e.target.value })}
                      />
                      <div className="form-text">
                        One command per line (or separated by <code>;</code>). Use{' '}
                        <code>{'{{USERNAME}}'}</code> for the recipient. Add{' '}
                        <code>sleep 0.5</code> or <code>wait 2</code> to pause before the
                        next command — pauses run in the panel and are not sent to the server.
                      </div>
                    </div>
                  )}

                  <div className="col-12">
                    <label className="form-label text-body-secondary small mb-1">Description (optional)</label>
                    <input
                      type="text"
                      className="form-control"
                      value={form.description}
                      onChange={(e) => setForm({ ...form, description: e.target.value })}
                    />
                  </div>

                  <div className="col-12">
                    <div className="form-check">
                      <input
                        className="form-check-input"
                        type="checkbox"
                        id="reward-active"
                        checked={form.active}
                        onChange={(e) => setForm({ ...form, active: e.target.checked })}
                      />
                      <label className="form-check-label text-body-secondary" htmlFor="reward-active">
                        Active (inactive rewards stay in pools but never drop)
                      </label>
                    </div>
                  </div>
                </div>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-outline-secondary" onClick={onClose}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-danger" disabled={busy}>
                  {busy ? 'Saving…' : (editing ? 'Save' : 'Add reward')}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>

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

export default RewardModal;
