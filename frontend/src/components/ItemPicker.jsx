// A modal for choosing an in-game item instead of typing its id from memory.
//
// The id is what actually reaches `additem`, and `Base.Hat_BeretArmy` is not
// something anyone recalls correctly. So the list is searched by the name a
// person knows, and the id comes along for the ride.
//
// The catalog is base-game only — it comes from PZwiki's generated item list,
// which knows nothing about Workshop mods. The field behind this button stays
// free text on purpose: this makes the common case easy without shutting the
// door on a modded item.
import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';

// Kept for the life of the page: four thousand rows is one request, and an
// admin adding several rewards should pay for it once.
let catalogCache = null;

// Rendering four thousand rows makes typing feel broken. Enough are shown to
// scroll through, and the count below says what is being left out — which is
// also the nudge to type another word.
const MAX_ROWS = 300;

export const itemIconUrl = (catalog, item) => (
  catalog && catalog.icon_base && item && item.icon
    ? catalog.icon_base + encodeURIComponent(item.icon)
    : null
);

function ItemPicker({ onSelect, onClose }) {
  const { token } = useAuth();
  const [catalog, setCatalog] = useState(catalogCache);
  const [loading, setLoading] = useState(!catalogCache);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const searchRef = useRef(null);

  useEffect(() => {
    if (!catalogCache) load();
    // The search box is the whole point of the modal; start in it.
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
      const data = await api.admin.items.getAll(token);
      catalogCache = data;
      setCatalog(data);
    } catch (err) {
      console.error('Load item catalog error:', err);
      setError(err.message || 'Could not load the item list');
    }
    setLoading(false);
  };

  const items = (catalog && catalog.items) || [];

  // Every word has to match somewhere, so "army beret" finds it whichever way
  // round you type it and without needing the exact display name.
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = terms.length === 0 ? items : items.filter((item) => {
    const haystack = `${item.name} ${item.id} ${item.category || ''}`.toLowerCase();
    return terms.every((term) => haystack.includes(term));
  });

  // A name that starts with what was typed is almost always the one meant, so
  // it goes first; everything else keeps the catalog's own grouping.
  const ranked = terms.length === 0 ? matches : matches.slice().sort((a, b) => {
    const lead = terms[0];
    const score = (item) => {
      const name = item.name.toLowerCase();
      if (item.id.toLowerCase() === lead) return 0;
      if (name === lead) return 1;
      if (name.startsWith(lead)) return 2;
      return 3;
    };
    return score(a) - score(b);
  });

  const shown = ranked.slice(0, MAX_ROWS);

  const choose = (item) => {
    onSelect({ ...item, icon_url: itemIconUrl(catalog, item) });
    onClose();
  };

  // Enter picks the top result, so a keyboard-only add never leaves the box.
  const onSearchKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (shown.length) choose(shown[0]);
    }
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
            <h5 className="modal-title font-display">Choose an item</h5>
            <button type="button" className="btn-close" onClick={onClose}></button>
          </div>

          <div className="modal-body">
            <div className="input-group mb-2">
              <span className="input-group-text"><i className="fas fa-magnifying-glass"></i></span>
              <input
                ref={searchRef}
                type="text"
                className="form-control"
                placeholder="Search by name, id or category…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onSearchKeyDown}
              />
            </div>

            {error && <div className="alert alert-danger" role="alert">{error}</div>}
            {catalog && catalog.stale && (
              <div className="alert alert-warning py-2" role="alert">
                This list could not be refreshed ({catalog.stale}), so it may be
                out of date.
              </div>
            )}

            {loading ? (
              <div className="text-center py-5">
                <div className="spinner-border text-secondary" role="status">
                  <span className="visually-hidden">Loading…</span>
                </div>
              </div>
            ) : (
              <>
                <div className="list-group list-group-flush">
                  {shown.length === 0 && (
                    <p className="text-body-secondary mb-0 py-3">
                      Nothing matches “{query}”. Modded items are not in this
                      list — close this and type the id instead.
                    </p>
                  )}
                  {shown.map((item) => {
                    const url = itemIconUrl(catalog, item);
                    return (
                      <button
                        type="button"
                        key={item.id}
                        className="list-group-item list-group-item-action d-flex align-items-center gap-2"
                        onClick={() => choose(item)}
                      >
                        {url ? (
                          <img
                            src={url}
                            alt=""
                            width="32"
                            height="32"
                            loading="lazy"
                            style={{ objectFit: 'contain' }}
                          />
                        ) : (
                          <span style={{ width: '32px' }}></span>
                        )}
                        <span className="me-auto text-start">
                          <span className="d-block">{item.name}</span>
                          <code className="small text-body-secondary">{item.id}</code>
                        </span>
                        {item.category && (
                          <span className="badge text-bg-secondary">{item.category}</span>
                        )}
                      </button>
                    );
                  })}
                </div>

                {ranked.length > shown.length && (
                  <p className="text-body-secondary mt-2 mb-0">
                    Showing {shown.length} of {ranked.length} matches — narrow the
                    search to see the rest.
                  </p>
                )}
              </>
            )}
          </div>

          <div className="modal-footer justify-content-between">
            <span className="text-body-secondary small">
              {items.length} base-game items
              {catalog && catalog.game_version ? ` · game ${catalog.game_version}` : ''}
            </span>
            <button className="btn btn-outline-secondary" onClick={onClose}>Close</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ItemPicker;
