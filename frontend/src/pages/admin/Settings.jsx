// Admin › Settings: runtime configuration.
//
// These override environment defaults and take effect without a redeploy, which
// is the point — closing registration is something you do during an incident,
// not at deploy time. Everything here is admin-only, and the endpoint enforces
// that rather than trusting the nav to hide the link.
//
// Grouped, because the list stopped being readable at twenty-odd entries and
// because the groups mean different things: mail is credentials, limits are
// numbers you tune under load, and the rest is policy.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';

// Order and wording of the sections. Anything in a group not listed here falls
// under Operations, so a new setting appears somewhere sensible by default.
const GROUPS = [
  {
    key: 'operations',
    title: 'Operations',
    blurb: 'Registration, loot and retention policy.'
  },
  {
    key: 'mail',
    title: 'Mail',
    blurb: 'Leave the host blank to use whatever the game-server container was '
      + 'started with. Filling it in overrides that for every message — which is '
      + 'how you switch providers without a redeploy. Mail is sent by the '
      + 'game-server, because it is the only container with outbound access.'
  },
  {
    key: 'limits',
    title: 'Sessions',
    blurb: 'How long a sign-in lasts. A change applies to tokens issued from '
      + 'now on; "sign out everywhere" is what ends the ones already out there.'
  }
];

function Settings() {
  const { token } = useAuth();
  const [settings, setSettings] = useState([]);
  const [draft, setDraft] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
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

  const handleTestMail = async () => {
    setError('');
    setNotice('');
    setTesting(true);
    try {
      const data = await api.admin.settings.testMail(token);
      setNotice(data.message || 'Test message sent.');
    } catch (err) {
      console.error('Test mail error:', err);
      setError(err.message || 'Could not send the test message');
    }
    setTesting(false);
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
          autoComplete={s.secret ? 'new-password' : 'off'}
          value={draft[s.key] ?? ''}
          placeholder={s.secret ? (s.is_set ? '•••••• (set — type to replace)' : 'not set') : ''}
          onChange={(e) => setDraft({ ...draft, [s.key]: e.target.value })}
        />
      </>
    );
  };

  if (loading) return <Spinner />;

  const known = GROUPS.map((g) => g.key);
  const inGroup = (key) => settings.filter(
    (s) => (known.includes(s.group) ? s.group : 'operations') === key
  );

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
        {GROUPS.map((group) => {
          const rows = inGroup(group.key);
          if (rows.length === 0) return null;
          return (
            <section className="mb-4" key={group.key}>
              <h5 className="font-display mb-1">{group.title}</h5>
              <p className="text-body-secondary small">{group.blurb}</p>

              {rows.map((s) => (
                <div className="card mb-3" key={s.key}>
                  <div className="card-body">
                    {field(s)}
                    {s.help && <div className="form-text">{s.help}</div>}
                  </div>
                </div>
              ))}

              {group.key === 'mail' && (
                <button
                  type="button"
                  className="btn btn-outline-secondary"
                  onClick={handleTestMail}
                  disabled={testing || saving}
                >
                  {testing ? 'Sending…' : 'Send me a test email'}
                </button>
              )}
            </section>
          );
        })}

        <button type="submit" className="btn btn-danger" disabled={saving}>
          {saving ? 'Saving…' : 'Save settings'}
        </button>
        <span className="form-text ms-3">
          Save before testing — the test uses the stored settings, not what is on screen.
        </span>
      </form>
    </>
  );
}

export default Settings;
