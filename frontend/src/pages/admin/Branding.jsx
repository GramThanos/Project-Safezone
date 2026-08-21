// Admin › Site › Branding: what the public pages say and where they link.
//
// Kept apart from Settings because it is a different job. Settings is retention
// windows and rate limits; this is wording, edited by whoever writes the wording
// — and getting it wrong is embarrassing rather than dangerous.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';

// Which settings appear here, in order, split into cards.
const SECTIONS = [
  {
    title: 'Identity',
    help: 'Shown in the navbar, the footer and the browser tab.',
    keys: ['site_brand_name']
  },
  {
    title: 'Home page',
    help: 'The banner at the top of the front page.',
    keys: ['site_hero_title', 'site_hero_subtitle']
  },
  {
    title: 'Social links',
    help: 'Full URLs. A blank one is left out of the footer rather than shown '
      + 'as an icon that goes nowhere.',
    keys: ['site_social_discord', 'site_social_twitter', 'site_social_youtube',
           'site_social_steam']
  }
];

function Branding() {
  const { token } = useAuth();
  const [settings, setSettings] = useState([]);
  const [draft, setDraft] = useState({});
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
      all.forEach((s) => { start[s.key] = s.value ?? ''; });
      setDraft(start);
    } catch (err) {
      console.error('Load settings error:', err);
      setError('Failed to load the site settings');
    }
    setLoading(false);
  };

  const spec = (key) => settings.find((s) => s.key === key);

  const handleSave = async () => {
    // Only what this page owns, and only what changed - a blind PUT of every
    // key would rewrite settings edited on another screen since the load.
    const mine = SECTIONS.flatMap((s) => s.keys);
    const changed = {};
    mine.forEach((key) => {
      const current = spec(key)?.value ?? '';
      if (draft[key] !== current) changed[key] = draft[key];
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
      setNotice('Saved. The site picks this up within a few seconds.');
    } catch (err) {
      console.error('Save settings error:', err);
      setError(err.message || 'Could not save those changes');
    }
    setSaving(false);
  };

  if (loading) return <Spinner />;

  return (
    <>
      <h4 className="font-display mb-1">Branding</h4>
      <p className="text-body-secondary">
        The words and links on the public side of the site. Everything here has a
        default, so a blank field falls back rather than leaving a gap.
      </p>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      {SECTIONS.map((section) => (
        <div className="card mb-3" key={section.title}>
          <div className="card-body">
            <h5 className="card-title font-display mb-1">{section.title}</h5>
            <p className="text-body-secondary small">{section.help}</p>

            {section.keys.map((key) => {
              const field = spec(key);
              if (!field) return null;
              return (
                <div className="mb-3" key={key}>
                  <label className="form-label text-body-secondary" htmlFor={key}>
                    {field.label}
                  </label>
                  {field.type === 'text' ? (
                    <textarea
                      id={key}
                      className="form-control"
                      rows="3"
                      value={draft[key] ?? ''}
                      onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                    ></textarea>
                  ) : (
                    <input
                      id={key}
                      type="text"
                      className="form-control"
                      value={draft[key] ?? ''}
                      onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                    />
                  )}
                  <div className="form-text">{field.help}</div>
                </div>
              );
            })}
          </div>
        </div>
      ))}

      <div className="d-flex gap-2">
        <button className="btn btn-danger" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save changes'}
        </button>
        <button className="btn btn-outline-secondary" onClick={loadData} disabled={saving}>
          Discard
        </button>
      </div>
    </>
  );
}

export default Branding;
