// Choose a reward from the catalog: searched and paged on the server, so it
// stays usable however many rewards there are. Opens on top of whatever form
// asked for it and hands the chosen reward back.
import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import Coins from './Coins';

const PAGE = 20;
// Typing pauses this long before asking, rather than once per keystroke.
const SEARCH_DELAY_MS = 250;

function RewardPickerModal({ title = 'Choose a reward', onSelect, onClose }) {
  const { token } = useAuth();
  const [q, setQ] = useState('');
  const [kind, setKind] = useState('');
  const [page, setPage] = useState(0);
  const [result, setResult] = useState({ rewards: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const searchRef = useRef(null);

  useEffect(() => { searchRef.current?.focus(); }, []);

  // Escape closes this picker only - it sits on top of another dialog.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      onClose();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const id = setTimeout(async () => {
      try {
        const data = await api.admin.rewards.search(token, { q: q.trim(), kind, limit: PAGE, offset: page * PAGE });
        if (!cancelled) {
          setResult({ rewards: data.rewards || [], total: data.pagination?.total || 0 });
          setError('');
        }
      } catch (err) {
        if (!cancelled) setError(err.message || 'Could not load rewards');
      }
      if (!cancelled) setLoading(false);
    }, SEARCH_DELAY_MS);
    return () => { cancelled = true; clearTimeout(id); };
  }, [token, q, kind, page]);

  const pages = Math.max(1, Math.ceil(result.total / PAGE));

  return (
    <div
      className="modal show d-block"
      style={{ backgroundColor: 'rgba(0,0,0,0.6)', zIndex: 1065 }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="reward-picker-title"
    >
      <div className="modal-dialog modal-dialog-centered modal-lg modal-dialog-scrollable"
        onClick={(e) => e.stopPropagation()}>
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title font-display" id="reward-picker-title">{title}</h5>
            <button type="button" className="btn-close" aria-label="Close" onClick={onClose}></button>
          </div>
          <div className="modal-body">
            <div className="row g-2 mb-3">
              <div className="col-md-8">
                <input
                  ref={searchRef}
                  type="search"
                  className="form-control"
                  placeholder="Search by name, item id or description"
                  value={q}
                  onChange={(e) => { setQ(e.target.value); setPage(0); }}
                />
              </div>
              <div className="col-md-4">
                <select className="form-select" value={kind}
                  onChange={(e) => { setKind(e.target.value); setPage(0); }}>
                  <option value="">Items and actions</option>
                  <option value="item">Items only</option>
                  <option value="usable">Actions only</option>
                </select>
              </div>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}
            {!loading && result.rewards.length === 0 ? (
              <p className="text-body-secondary mb-0">No rewards match.</p>
            ) : (
              <div className={`list-group${loading ? ' opacity-50' : ''}`}>
                {result.rewards.map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    className="list-group-item list-group-item-action d-flex align-items-center gap-3"
                    onClick={() => { onSelect(r); onClose(); }}
                  >
                    {r.icon
                      ? <img src={r.icon} alt="" style={{ width: 32, height: 32, objectFit: 'contain' }} />
                      : <i className={`fas ${r.kind === 'usable' ? 'fa-bolt' : 'fa-gift'} text-body-secondary`} style={{ width: 32 }}></i>}
                    <span className="flex-grow-1 text-start">
                      <span className="fw-semibold">{r.name}</span>
                      {!r.active && <span className="badge text-bg-secondary ms-2">inactive</span>}
                      <span className="d-block small text-body-secondary">
                        {r.kind === 'usable' ? 'Action' : <code>{r.in_game_id}</code>}
                        {r.description ? ` · ${r.description}` : ''}
                      </span>
                    </span>
                    <span className="small text-body-secondary text-nowrap" title="Sells back for">
                      <Coins amount={r.coin_value} />
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="modal-footer justify-content-between">
            <span className="small text-body-secondary">
              {result.total} reward{result.total === 1 ? '' : 's'}
            </span>
            <div className="btn-group btn-group-sm">
              <button type="button" className="btn btn-outline-secondary"
                disabled={page === 0 || loading} onClick={() => setPage(page - 1)}>
                <i className="fas fa-chevron-left"></i>
              </button>
              <span className="btn btn-outline-secondary disabled">{page + 1} / {pages}</span>
              <button type="button" className="btn btn-outline-secondary"
                disabled={page + 1 >= pages || loading} onClick={() => setPage(page + 1)}>
                <i className="fas fa-chevron-right"></i>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default RewardPickerModal;
