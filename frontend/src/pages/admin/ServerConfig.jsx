// Admin › Servers › config editor.
//
// Two tabs on purpose. "Settings" is the everyday screen: declared keys, typed
// inputs, validation. "Advanced" is the whole file — every key including ones
// this panel has never heard of — where you can also disable a key by
// commenting it out.
//
// Editing is refused while the server is running, because Project Zomboid
// rewrites this file on shutdown and would silently discard anything saved
// here. The form goes read-only rather than letting somebody type into a screen
// that will reject the save.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';
import ServerTemplateModal from '../../components/ServerTemplateModal';

function ServerConfig({ server, onClose }) {
  const { token } = useAuth();
  const [tab, setTab] = useState('simple');
  const [showTemplates, setShowTemplates] = useState(false);

  const [simple, setSimple] = useState([]);
  const [simpleDraft, setSimpleDraft] = useState({});

  const [raw, setRaw] = useState(null);
  const [rawDraft, setRawDraft] = useState({});
  const [newKey, setNewKey] = useState({ key: '', value: '' });

  // World difficulty (SandboxVars.lua) — its own file, edited independently.
  const [sandbox, setSandbox] = useState(null);
  const [sandboxDraft, setSandboxDraft] = useState({});

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [server.id]);

  const loadAll = async () => {
    setError('');
    setNotice('');
    try {
      const [simpleData, rawData, sandboxData] = await Promise.all([
        api.admin.servers.config(token, server.id),
        api.admin.servers.configRaw(token, server.id),
        api.admin.servers.sandbox(token, server.id)
      ]);

      setSimple(simpleData.settings || []);
      const draft = {};
      (simpleData.settings || []).forEach((s) => {
        // A secret's value is never sent to the browser, so its field starts
        // empty and only a typed value is ever submitted.
        draft[s.key] = s.type === 'secret' ? '' : s.value;
      });
      setSimpleDraft(draft);

      setRaw(rawData);
      const rawStart = {};
      (rawData.entries || []).forEach((e) => {
        rawStart[e.key] = { value: e.secret ? '' : (e.value ?? ''), disabled: e.disabled };
      });
      setRawDraft(rawStart);

      setSandbox(sandboxData);
      const sbStart = {};
      (sandboxData.entries || []).forEach((e) => { sbStart[e.key] = e.value; });
      setSandboxDraft(sbStart);
    } catch (err) {
      console.error('Load config error:', err);
      setError(err.message || 'Could not read the config');
    }
    setLoading(false);
  };

  const editable = !!raw?.editable;
  const sandboxEditable = !!sandbox?.editable;

  const saveSimple = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    setNotice('');
    const payload = {};
    simple.forEach((s) => {
      const value = simpleDraft[s.key];
      if (s.type === 'secret' && value === '') return;   // untouched secret
      if (value === null || value === undefined) return;
      payload[s.key] = value;
    });
    try {
      const data = await api.admin.servers.saveConfig(token, server.id, payload);
      setNotice(data.message || 'Saved.');
      loadAll();
    } catch (err) {
      console.error('Save config error:', err);
      setError(err.message || 'Could not save');
    }
    setSaving(false);
  };

  const saveRaw = async () => {
    setSaving(true);
    setError('');
    setNotice('');

    // Only send what actually differs, so an unrelated key is never rewritten.
    const changes = {};
    (raw.entries || []).forEach((e) => {
      const draft = rawDraft[e.key];
      if (!draft) return;
      const valueChanged = e.secret
        ? draft.value !== ''                       // blank means "leave it"
        : String(draft.value ?? '') !== String(e.value ?? '');
      if (valueChanged || draft.disabled !== e.disabled) {
        changes[e.key] = { value: draft.value, disabled: draft.disabled };
      }
    });
    Object.entries(rawDraft).forEach(([key, draft]) => {
      if (!(raw.entries || []).some((e) => e.key === key)) changes[key] = draft;
    });

    if (Object.keys(changes).length === 0) {
      setNotice('Nothing changed.');
      setSaving(false);
      return;
    }

    try {
      const data = await api.admin.servers.saveConfigRaw(token, server.id, changes, raw.version);
      setNotice(`${data.message} (${(data.changed || []).join(', ')})`);
      loadAll();
    } catch (err) {
      console.error('Save raw config error:', err);
      setError(err.message || 'Could not save');
    }
    setSaving(false);
  };

  const addKey = () => {
    const key = newKey.key.trim();
    if (!key) return;
    if (rawDraft[key]) {
      setError(`${key} is already in the file`);
      return;
    }
    setRawDraft({ ...rawDraft, [key]: { value: newKey.value, disabled: false } });
    setNewKey({ key: '', value: '' });
  };

  const saveSandbox = async () => {
    setSaving(true);
    setError('');
    setNotice('');

    // Only send what actually changed, so an untouched key is never rewritten.
    const changes = {};
    (sandbox?.entries || []).forEach((e) => {
      if (e.type === null) return;   // unmodelled value: shown, not editable
      const next = sandboxDraft[e.key];
      // A cleared numeric field is not a value; leave the key as it was rather
      // than writing an empty string over a number.
      if ((e.type === 'int' || e.type === 'float') && (next === '' || Number.isNaN(next))) return;
      if (next !== e.value) changes[e.key] = next;
    });

    if (Object.keys(changes).length === 0) {
      setNotice('Nothing changed.');
      setSaving(false);
      return;
    }

    try {
      const data = await api.admin.servers.saveSandbox(token, server.id, changes, sandbox.version);
      setNotice(`${data.message} (${(data.changed || []).join(', ')})`);
      loadAll();
    } catch (err) {
      console.error('Save sandbox error:', err);
      setError(err.message || 'Could not save');
    }
    setSaving(false);
  };

  // Download the current server as a portable template: both the INI settings
  // and the SandboxVars in one file. Excluded keys (ports/credentials/identity
  // for the INI, VERSION for the sandbox) are filtered out by the backend, so
  // what lands in the file is safe to publish.
  const downloadTemplate = async () => {
    setError('');
    setNotice('');
    try {
      const tpl = await api.admin.servers.exportConfigTemplate(token, server.id, server.name);
      const blob = new Blob([JSON.stringify(tpl, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${server.name}-template.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export template error:', err);
      setError(err.message || 'Could not export');
    }
  };

  const onTemplateImported = (result) => {
    setShowTemplates(false);
    setNotice(result.message || 'Template applied.');
    if (result.error) setError(result.error);
    loadAll();
  };

  const sandboxField = (e) => {
    const value = sandboxDraft[e.key];
    if (e.type === 'bool') {
      return (
        <div className="form-check form-switch">
          <input
            className="form-check-input"
            type="checkbox"
            id={`sb-${e.key}`}
            disabled={!sandboxEditable}
            checked={!!value}
            onChange={(ev) => setSandboxDraft({ ...sandboxDraft, [e.key]: ev.target.checked })}
          />
          <label className="form-check-label" htmlFor={`sb-${e.key}`}><code>{e.key}</code></label>
        </div>
      );
    }
    const numeric = e.type === 'int' || e.type === 'float';
    return (
      <>
        <label className="form-label" htmlFor={`sb-${e.key}`}>
          <code>{e.key}</code>
          {e.type === null && (
            <span className="badge text-bg-secondary ms-2" title="This value's type isn't recognised, so it can't be edited here">
              read-only
            </span>
          )}
        </label>
        <input
          id={`sb-${e.key}`}
          type={numeric ? 'number' : 'text'}
          step={e.type === 'float' ? 'any' : undefined}
          className="form-control"
          disabled={!sandboxEditable || e.type === null}
          value={value ?? ''}
          onChange={(ev) => {
            const raw = ev.target.value;
            const next = e.type === 'int' ? (raw === '' ? '' : parseInt(raw, 10))
              : e.type === 'float' ? (raw === '' ? '' : parseFloat(raw))
                : raw;
            setSandboxDraft({ ...sandboxDraft, [e.key]: next });
          }}
        />
      </>
    );
  };

  const simpleField = (s) => {
    if (s.type === 'bool') {
      return (
        <div className="form-check form-switch">
          <input
            className="form-check-input"
            type="checkbox"
            id={`s-${s.key}`}
            disabled={!editable}
            checked={!!simpleDraft[s.key]}
            onChange={(e) => setSimpleDraft({ ...simpleDraft, [s.key]: e.target.checked })}
          />
          <label className="form-check-label" htmlFor={`s-${s.key}`}>{s.key}</label>
        </div>
      );
    }
    return (
      <>
        <label className="form-label" htmlFor={`s-${s.key}`}>{s.key}</label>
        <input
          id={`s-${s.key}`}
          type={s.type === 'secret' ? 'password' : s.type === 'int' ? 'number' : 'text'}
          className="form-control"
          disabled={!editable}
          value={simpleDraft[s.key] ?? ''}
          placeholder={s.type === 'secret' ? (s.is_set ? '•••••• (set — type to replace)' : 'not set') : ''}
          onChange={(e) => setSimpleDraft({ ...simpleDraft, [s.key]: e.target.value })}
        />
      </>
    );
  };

  if (loading) return <Spinner />;

  return (
    <>
    <div className="modal show d-block" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }} onClick={onClose}>
      <div
        className="modal-dialog modal-dialog-centered modal-xl modal-dialog-scrollable"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title font-display">{server.name} &mdash; configuration</h5>
            <button type="button" className="btn-close" onClick={onClose}></button>
          </div>

          <div className="modal-body">
            {!editable && (
              <div className="alert alert-warning">
                This server is <strong>{raw?.state || 'in an unknown state'}</strong>, so the
                config is read-only. Project Zomboid rewrites its files when it
                shuts down, so anything saved now would be lost. Stop the server
                to edit it &mdash; editable states are{' '}
                {(raw?.editable_states || []).join(', ')}.
              </div>
            )}

            {error && <div className="alert alert-danger">{error}</div>}
            {notice && <div className="alert alert-success">{notice}</div>}

            <ul className="nav nav-tabs mb-3">
              <li className="nav-item">
                <button
                  className={`nav-link ${tab === 'simple' ? 'active' : ''}`}
                  onClick={() => setTab('simple')}
                >
                  Settings
                </button>
              </li>
              <li className="nav-item">
                <button
                  className={`nav-link ${tab === 'raw' ? 'active' : ''}`}
                  onClick={() => setTab('raw')}
                >
                  Advanced ({(raw?.entries || []).length} keys)
                </button>
              </li>
              <li className="nav-item">
                <button
                  className={`nav-link ${tab === 'sandbox' ? 'active' : ''}`}
                  onClick={() => setTab('sandbox')}
                >
                  World ({(sandbox?.entries || []).length})
                </button>
              </li>
            </ul>

            {tab === 'simple' ? (
              <form onSubmit={saveSimple}>
                {simple.map((s) => (
                  <div className="mb-3" key={s.key}>
                    {simpleField(s)}
                    <div className="form-text">{s.help}</div>
                  </div>
                ))}
                <button type="submit" className="btn btn-danger" disabled={!editable || saving}>
                  {saving ? 'Saving…' : 'Save settings'}
                </button>
              </form>
            ) : tab === 'raw' ? (
              <>
                <p className="text-body-secondary">
                  Every key in the file, including ones this panel does not know
                  about. Unticking <em>Enabled</em> comments the key out, which
                  makes the game fall back to its own default &mdash; that is not
                  the same as clearing the value. The previous value is kept in
                  the comment, so re-enabling restores it.
                </p>

                <div className="table-responsive">
                  <table className="table table-sm align-middle">
                    <thead>
                      <tr>
                        <th style={{ width: '30%' }}>Key</th>
                        <th>Value</th>
                        <th style={{ width: '6rem' }}>Enabled</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(raw?.entries || []).map((e) => (
                        <tr key={e.key} className={rawDraft[e.key]?.disabled ? 'opacity-50' : ''}>
                          <td>
                            <code>{e.key}</code>
                            {!e.type && (
                              <span className="badge text-bg-secondary ms-2" title="Not a key this panel knows">
                                unknown
                              </span>
                            )}
                          </td>
                          <td>
                            <input
                              type={e.secret ? 'password' : 'text'}
                              className="form-control form-control-sm"
                              disabled={!editable}
                              value={rawDraft[e.key]?.value ?? ''}
                              placeholder={e.secret ? (e.is_set ? '•••••• (set — type to replace)' : 'not set') : ''}
                              onChange={(ev) => setRawDraft({
                                ...rawDraft,
                                [e.key]: { ...rawDraft[e.key], value: ev.target.value }
                              })}
                            />
                          </td>
                          <td className="text-center">
                            <input
                              type="checkbox"
                              className="form-check-input"
                              disabled={!editable}
                              checked={!rawDraft[e.key]?.disabled}
                              onChange={(ev) => setRawDraft({
                                ...rawDraft,
                                [e.key]: { ...rawDraft[e.key], disabled: !ev.target.checked }
                              })}
                            />
                          </td>
                        </tr>
                      ))}
                      {Object.entries(rawDraft)
                        .filter(([key]) => !(raw?.entries || []).some((e) => e.key === key))
                        .map(([key, draft]) => (
                          <tr key={key} className="table-active">
                            <td><code>{key}</code> <span className="badge text-bg-success ms-2">new</span></td>
                            <td>
                              <input
                                type="text"
                                className="form-control form-control-sm"
                                disabled={!editable}
                                value={draft.value}
                                onChange={(ev) => setRawDraft({
                                  ...rawDraft, [key]: { ...draft, value: ev.target.value }
                                })}
                              />
                            </td>
                            <td className="text-center">
                              <button
                                className="btn btn-sm btn-outline-danger"
                                onClick={() => {
                                  const next = { ...rawDraft };
                                  delete next[key];
                                  setRawDraft(next);
                                }}
                              >
                                ×
                              </button>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>

                <div className="row g-2 align-items-end mb-3">
                  <div className="col-md-4">
                    <label className="form-label text-body-secondary">Add a key</label>
                    <input
                      type="text"
                      className="form-control form-control-sm"
                      placeholder="SettingName"
                      disabled={!editable}
                      value={newKey.key}
                      onChange={(e) => setNewKey({ ...newKey, key: e.target.value })}
                    />
                  </div>
                  <div className="col-md-6">
                    <input
                      type="text"
                      className="form-control form-control-sm"
                      placeholder="value"
                      disabled={!editable}
                      value={newKey.value}
                      onChange={(e) => setNewKey({ ...newKey, value: e.target.value })}
                    />
                  </div>
                  <div className="col-md-2">
                    <button className="btn btn-sm btn-outline-secondary w-100" disabled={!editable} onClick={addKey}>
                      Add
                    </button>
                  </div>
                  <div className="col-12">
                    <div className="form-text">
                      A misspelled key is accepted silently by the game and simply
                      does nothing. Check the spelling against the wiki.
                    </div>
                  </div>
                </div>

                <button className="btn btn-danger" onClick={saveRaw} disabled={!editable || saving}>
                  {saving ? 'Saving…' : 'Save file'}
                </button>
              </>
            ) : (
              <>
                <p className="text-body-secondary">
                  Gameplay difficulty from <code>SandboxVars.lua</code>: how long
                  until water and power cut, how much loot spawns, how many
                  zombies, how fast hunger and thirst climb. These are separate
                  from the settings above. Nested groups and unrecognised values
                  are not shown here &mdash; use a template or edit the file
                  directly for those.
                </p>

                {(sandbox?.entries || []).length === 0 ? (
                  <p className="text-body-secondary py-3 mb-0">
                    No sandbox settings were found in this server's file.
                  </p>
                ) : (
                  <>
                    {(sandbox?.entries || []).map((e) => (
                      <div className="mb-3" key={e.key}>
                        {sandboxField(e)}
                      </div>
                    ))}
                    <button className="btn btn-danger" onClick={saveSandbox} disabled={!sandboxEditable || saving}>
                      {saving ? 'Saving…' : 'Save world settings'}
                    </button>
                  </>
                )}
              </>
            )}
          </div>

          <div className="modal-footer">
            <span className="text-body-secondary small me-auto">
              {tab === 'sandbox' ? sandbox?.path : raw?.path}
            </span>
            <button
              className="btn btn-outline-secondary"
              onClick={() => setShowTemplates(true)}
              disabled={!editable}
              title={editable ? 'Apply a template (config + world) from the community or a file'
                              : 'Stop the server to apply a template'}
            >
              <i className="fas fa-download"></i> Import template
            </button>
            <button className="btn btn-outline-secondary" onClick={downloadTemplate}>
              <i className="fas fa-upload"></i> Export template
            </button>
            <button className="btn btn-outline-secondary" onClick={loadAll}>Reload</button>
            <button className="btn btn-outline-secondary" onClick={onClose}>Close</button>
          </div>
        </div>
      </div>
    </div>

    {showTemplates && (
      <ServerTemplateModal
        server={server}
        versions={{ ini: raw?.version, sandbox: sandbox?.version }}
        onImported={onTemplateImported}
        onClose={() => setShowTemplates(false)}
      />
    )}
    </>
  );
}

export default ServerConfig;
