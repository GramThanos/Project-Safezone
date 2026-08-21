// Admin › Site › Legal Pages: the Markdown behind /terms, /privacy, /cookies.
//
// One document at a time, with a preview, because these are read by people who
// may later hold you to them — worth seeing rendered before it is published.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import Markdown from '../../components/Markdown';
import { Spinner } from './helpers';

const PAGES = [
  { key: 'site_rules', slug: 'rules', label: 'Server Rules' },
  { key: 'site_legal_terms', slug: 'terms', label: 'Terms' },
  { key: 'site_legal_privacy', slug: 'privacy', label: 'Privacy' },
  { key: 'site_legal_cookies', slug: 'cookies', label: 'Cookies' }
];

function LegalPages() {
  const { token } = useAuth();
  const [settings, setSettings] = useState([]);
  const [draft, setDraft] = useState({});
  const [active, setActive] = useState(PAGES[0].key);
  const [preview, setPreview] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setError('');
    try {
      const data = await api.admin.settings.getAll(token);
      const all = data.settings || [];
      setSettings(all);
      const start = {};
      PAGES.forEach(({ key }) => {
        start[key] = all.find((s) => s.key === key)?.value ?? '';
      });
      setDraft(start);
    } catch (err) {
      console.error('Load settings error:', err);
      setError('Failed to load the pages');
    }
    setLoading(false);
  };

  const stored = (key) => settings.find((s) => s.key === key)?.value ?? '';
  const dirty = PAGES.some(({ key }) => draft[key] !== stored(key));

  const handleSave = async () => {
    const changed = {};
    PAGES.forEach(({ key }) => {
      if (draft[key] !== stored(key)) changed[key] = draft[key];
    });
    if (Object.keys(changed).length === 0) {
      setNotice('Nothing to save.');
      return;
    }

    setError('');
    setNotice('');
    setSaving(true);
    try {
      const data = await api.admin.settings.update(token, changed);
      setSettings(data.settings || []);
      setNotice('Saved. The pages are live now.');
    } catch (err) {
      console.error('Save pages error:', err);
      setError(err.message || 'Could not save those changes');
    }
    setSaving(false);
  };

  if (loading) return <Spinner />;

  const current = PAGES.find((p) => p.key === active);

  return (
    <>
      <h4 className="font-display mb-1">Site Pages</h4>
      <p className="text-body-secondary">
        Markdown, linked from every footer. A page left empty says so rather than
        showing boilerplate nobody wrote — an empty policy is better than a
        borrowed one. Supports headings, lists, links, <code>**bold**</code> and{' '}
        <code>*italic*</code>.
      </p>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      <ul className="nav nav-tabs mb-3">
        {PAGES.map((page) => (
          <li className="nav-item" key={page.key}>
            <button
              className={`nav-link${active === page.key ? ' active' : ''}`}
              onClick={() => { setActive(page.key); setPreview(false); }}
            >
              {page.label}
              {draft[page.key] !== stored(page.key) && (
                <span className="badge text-bg-warning ms-2">edited</span>
              )}
            </button>
          </li>
        ))}
      </ul>

      <div className="card mb-3">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-center mb-2">
            <span className="text-body-secondary small">
              Published at <code>/{current.slug}</code>
            </span>
            <div className="btn-group btn-group-sm" role="group">
              <button
                className={`btn btn-outline-secondary${preview ? '' : ' active'}`}
                onClick={() => setPreview(false)}
              >
                Edit
              </button>
              <button
                className={`btn btn-outline-secondary${preview ? ' active' : ''}`}
                onClick={() => setPreview(true)}
              >
                Preview
              </button>
            </div>
          </div>

          {preview ? (
            draft[active] ? (
              <Markdown>{draft[active]}</Markdown>
            ) : (
              <p className="text-body-secondary mb-0">
                Nothing written yet — the page will say so.
              </p>
            )
          ) : (
            <textarea
              className="form-control font-monospace"
              rows="18"
              value={draft[active] ?? ''}
              placeholder={`# ${current.label}\n\nWrite the ${current.label.toLowerCase()} here.`}
              onChange={(e) => setDraft({ ...draft, [active]: e.target.value })}
            ></textarea>
          )}
        </div>
      </div>

      <div className="d-flex gap-2">
        <button className="btn btn-danger" onClick={handleSave} disabled={saving || !dirty}>
          {saving ? 'Saving…' : 'Save changes'}
        </button>
        <button
          className="btn btn-outline-secondary"
          onClick={loadData}
          disabled={saving || !dirty}
        >
          Discard
        </button>
      </div>
    </>
  );
}

export default LegalPages;
