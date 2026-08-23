// A modal cheat-sheet of the whitelisted admin commands, for the free-text
// reward editor. Each entry inserts a ready-to-edit console line (with the
// {{USERNAME}} placeholder and {param} slots) into the command box, so an admin
// building a custom reward does not have to remember exact syntax. The templates
// come straight from the game-server's own command builders, so they always
// match what will actually run.
import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { WIKI_COMMANDS } from './helpers';

function CommandLibrary({ onInsert, onClose }) {
  const { token } = useAuth();
  const [actions, setActions] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [inserted, setInserted] = useState('');
  const searchRef = useRef(null);

  useEffect(() => {
    load();
    if (searchRef.current) searchRef.current.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Escape closes, as it does everywhere else.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      // droppable=1: only commands that are safe to hand a player as a reward.
      const data = await api.admin.actions.getAll(token, true);
      setActions(data.actions || []);
      setCategories(data.categories || []);
    } catch (err) {
      console.error('Load command library error:', err);
      setError(err.message || 'Could not load the command list');
    }
    setLoading(false);
  };

  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = terms.length === 0 ? actions : actions.filter((a) => {
    const haystack = `${a.label} ${a.flavor || ''} ${a.description || ''} ${a.template || ''}`.toLowerCase();
    return terms.every((term) => haystack.includes(term));
  });

  // Keep the game-server's own grouping; drop empty groups after filtering.
  const groups = categories
    .map((c) => ({ ...c, items: matches.filter((a) => a.category === c.id) }))
    .filter((g) => g.items.length > 0);

  const choose = (action) => {
    onInsert(action.template || action.command);
    // Stay open so several commands can be stacked into one reward; a brief note
    // confirms what landed.
    setInserted(action.label);
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
            <h5 className="modal-title font-display">Insert a command</h5>
            <button type="button" className="btn-close" onClick={onClose}></button>
          </div>

          <div className="modal-body">
            <p className="text-body-secondary small">
              Pick a command to drop it into the reward, then edit the
              {' '}<code>{'{...}'}</code> slots. Keep
              {' '}<code>{'{{USERNAME}}'}</code> where the reward's recipient should go.
              {' '}
              <a className="link-secondary" href={WIKI_COMMANDS} target="_blank" rel="noopener noreferrer">
                Full reference <i className="fas fa-arrow-up-right-from-square"></i>
              </a>
            </p>

            <div className="input-group mb-2">
              <span className="input-group-text"><i className="fas fa-magnifying-glass"></i></span>
              <input
                ref={searchRef}
                type="text"
                className="form-control"
                placeholder="Search commands…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>

            {inserted && (
              <div className="alert alert-success py-2" role="alert">
                Added <strong>{inserted}</strong> to the reward.
              </div>
            )}
            {error && <div className="alert alert-danger" role="alert">{error}</div>}

            {loading ? (
              <div className="text-center py-5">
                <div className="spinner-border text-secondary" role="status">
                  <span className="visually-hidden">Loading…</span>
                </div>
              </div>
            ) : (
              <>
                {groups.length === 0 && (
                  <p className="text-body-secondary mb-0 py-3">Nothing matches “{query}”.</p>
                )}
                {groups.map((g) => (
                  <div key={g.id} className="mb-3">
                    <h6 className="text-body-secondary text-uppercase small mb-2">{g.label}</h6>
                    <div className="list-group list-group-flush">
                      {g.items.map((a) => (
                        <button
                          type="button"
                          key={a.id}
                          className="list-group-item list-group-item-action"
                          onClick={() => choose(a)}
                          title={a.description}
                        >
                          <div className="d-flex justify-content-between align-items-baseline gap-2">
                            <span className="fw-semibold">{a.label}</span>
                            {a.flavor && <span className="badge text-bg-secondary">{a.flavor}</span>}
                          </div>
                          <code className="small text-body-secondary d-block text-truncate">
                            {a.template || a.command}
                          </code>
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </>
            )}
          </div>

          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={onClose}>Done</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default CommandLibrary;
