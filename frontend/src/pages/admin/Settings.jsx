// Admin › Settings: runtime configuration.
//
// These override environment defaults and take effect without a redeploy, which
// is the point — closing registration is something you do during an incident,
// not at deploy time.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';

function Settings() {
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
      // Operational settings only. The `site` group is the public wording and
      // links, edited on Site › Branding and Site › Legal Pages - a paragraph
      // of Markdown does not belong in a list of retention windows.
      const operational = (data.settings || []).filter((s) => s.group !== 'site');
      setSettings(operational);
      // Secrets come back as "is it set", never as a value, so their draft
      // starts empty and only a typed value is ever submitted.
      const next = {};
      operational.forEach((s) => {
        next[s.key] = s.secret ? '' : s.value;
      });
      setDraft(next);
    } catch (err) {
      console.error('Load settings error:', err);
      setError('Failed to load settings');
    }
    setLoading(false);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setError('');
    setNotice('');
    setSaving(true);

    const payload = {};
    settings.forEach((s) => {
      const value = draft[s.key];
      // An untouched secret field means "leave it alone", not "clear it".
      if (s.secret && value === '') return;
      payload[s.key] = s.type === 'int' ? parseInt(value, 10) : value;
    });

    try {
      const data = await api.admin.settings.update(token, payload);
      setSettings((data.settings || []).filter((s) => s.group !== 'site'));
      setNotice('Settings saved.');
      loadData();
    } catch (err) {
      console.error('Save settings error:', err);
      setError(err.message || 'Could not save settings');
    }
    setSaving(false);
  };

  const field = (s) => {
    if (s.type === 'bool') {
      return (
        <div className="form-check form-switch">
          <input
            className="form-check-input"
            type="checkbox"
            id={s.key}
            checked={!!draft[s.key]}
            onChange={(e) => setDraft({ ...draft, [s.key]: e.target.checked })}
          />
          <label className="form-check-label" htmlFor={s.key}>{s.label}</label>
        </div>
      );
    }

    return (
      <>
        <label className="form-label" htmlFor={s.key}>{s.label}</label>
        <input
          type={s.secret ? 'password' : s.type === 'int' ? 'number' : 'text'}
          className="form-control"
          id={s.key}
          value={draft[s.key] ?? ''}
          placeholder={s.secret ? (s.is_set ? '•••••• (set — type to replace)' : 'not set') : ''}
          onChange={(e) => setDraft({ ...draft, [s.key]: e.target.value })}
        />
      </>
    );
  };

  if (loading) return <Spinner />;

  return (
    <>
      <h4 className="font-display mb-1">Settings</h4>
      <p className="text-body-secondary">
        Changes apply immediately, without restarting anything. Blank values fall
        back to the environment defaults the container was started with.
      </p>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      <form onSubmit={handleSave}>
        {settings.map((s) => (
          <div className="card mb-3" key={s.key}>
            <div className="card-body">
              {field(s)}
              <div className="form-text">{s.help}</div>
            </div>
          </div>
        ))}

        <button type="submit" className="btn btn-danger" disabled={saving}>
          {saving ? 'Saving…' : 'Save settings'}
        </button>
      </form>
    </>
  );
}

export default Settings;
