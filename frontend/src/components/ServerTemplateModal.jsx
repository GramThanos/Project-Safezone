// Apply a combined template to a server — from the community list on GitHub, or
// from a local file exported earlier. One template carries two halves:
//
//   settings - non-gameplay server settings (.ini): PvP, safehouse, max players
//   sandbox  - gameplay difficulty (SandboxVars.lua): water/power shutoff, loot,
//              zombie population, stats decay
//
// Either half may be present; both are applied in one import. The game-server
// re-filters each half against its own blacklist before writing, so the skip
// markers in the preview only set expectations, they are never the enforcement.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';

// The blacklists, replicated for the preview. Authoritative copies are
// server_config.is_template_excluded and sandbox_config.is_template_excluded.
const INI_EXCLUDED = new Set(['PublicName', 'PublicDescription', 'ResetID', 'ServerPlayerID']);
const iniExcluded = (key) =>
  INI_EXCLUDED.has(key) || key.endsWith('Port') || key.endsWith('Password');
const sandboxExcluded = (key) => key === 'VERSION';

// One preview table for a section, splitting keys into applied vs skipped.
function Section({ title, values, isExcluded, skipNote }) {
  const pairs = Object.entries(values || {});
  if (pairs.length === 0) return null;
  const applied = pairs.filter(([k]) => !isExcluded(k));
  const skipped = pairs.filter(([k]) => isExcluded(k));
  return (
    <div className="mb-3">
      <h6 className="mb-2">{title} <span className="text-body-secondary fw-normal">({applied.length})</span></h6>
      <div className="table-responsive">
        <table className="table table-sm align-middle mb-1">
          <tbody>
            {applied.map(([k, v]) => (
              <tr key={k}>
                <td style={{ width: '55%' }}><code>{k}</code></td>
                <td><code>{String(v)}</code></td>
              </tr>
            ))}
            {skipped.map(([k, v]) => (
              <tr key={k} className="opacity-50">
                <td>
                  <code>{k}</code>
                  <span className="badge text-bg-secondary ms-2" title={skipNote}>skipped</span>
                </td>
                <td><code>{String(v)}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {skipped.length > 0 && (
        <div className="form-text">{skipped.length} excluded ({skipNote}).</div>
      )}
    </div>
  );
}

function ServerTemplateModal({ server, versions, onImported, onClose }) {
  const { token } = useAuth();

  const [tab, setTab] = useState('community');
  const [list, setList] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [listStale, setListStale] = useState('');
  const [template, setTemplate] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    loadList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const loadList = async () => {
    setListLoading(true);
    setError('');
    try {
      const data = await api.admin.serverTemplates.list(token);
      setList(data.templates || []);
      setListStale(data.stale || '');
    } catch (err) {
      console.error('Load community templates error:', err);
      setError(err.message || 'Could not load the community list');
    }
    setListLoading(false);
  };

  const adoptTemplate = (tpl) => {
    setTemplate(tpl);
    setError('');
  };

  const chooseCommunity = async (id) => {
    setBusy(true);
    setError('');
    try {
      const data = await api.admin.serverTemplates.get(token, id);
      adoptTemplate(data.template);
    } catch (err) {
      console.error('Load community template error:', err);
      setError(err.message || 'Could not load that template');
    }
    setBusy(false);
  };

  const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v);

  const chooseFile = (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const tpl = JSON.parse(reader.result);
        if (!tpl || (!isObj(tpl.settings) && !isObj(tpl.sandbox))) {
          setError('That file is not a template (no settings or sandbox object).');
          return;
        }
        adoptTemplate(tpl);
      } catch (err) {
        setError('That file is not valid JSON.');
      }
    };
    reader.readAsText(file);
  };

  const doImport = async () => {
    if (!template) return;
    setBusy(true);
    setError('');
    try {
      const data = await api.admin.servers.importConfigTemplate(token, server.id, {
        settings: isObj(template.settings) ? template.settings : undefined,
        sandbox: isObj(template.sandbox) ? template.sandbox : undefined,
        version: versions?.ini,
        sandbox_version: versions?.sandbox,
      });
      onImported(data);
    } catch (err) {
      console.error('Import template error:', err);
      setError(err.message || 'Failed to apply that template');
      setBusy(false);
    }
  };

  const settings = isObj(template?.settings) ? template.settings : {};
  const sandbox = isObj(template?.sandbox) ? template.sandbox : {};
  const applicableCount =
    Object.keys(settings).filter((k) => !iniExcluded(k)).length +
    Object.keys(sandbox).filter((k) => !sandboxExcluded(k)).length;

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
            <h5 className="modal-title font-display">Apply a template</h5>
            <button type="button" className="btn-close" onClick={onClose}></button>
          </div>

          <div className="modal-body">
            {error && <div className="alert alert-danger" role="alert">{error}</div>}

            {!template ? (
              <>
                <ul className="nav nav-tabs mb-3">
                  <li className="nav-item">
                    <button
                      className={`nav-link ${tab === 'community' ? 'active' : ''}`}
                      onClick={() => setTab('community')}
                    >
                      Community
                    </button>
                  </li>
                  <li className="nav-item">
                    <button
                      className={`nav-link ${tab === 'file' ? 'active' : ''}`}
                      onClick={() => setTab('file')}
                    >
                      From file
                    </button>
                  </li>
                </ul>

                {tab === 'community' ? (
                  <>
                    {listStale && (
                      <div className="alert alert-warning py-2" role="alert">
                        This list could not be refreshed ({listStale}), so it may
                        be out of date.
                      </div>
                    )}
                    {listLoading ? (
                      <div className="text-center py-5">
                        <div className="spinner-border text-secondary" role="status">
                          <span className="visually-hidden">Loading…</span>
                        </div>
                      </div>
                    ) : list.length === 0 ? (
                      <p className="text-body-secondary py-3 mb-0">
                        No community templates are available.
                      </p>
                    ) : (
                      <div className="list-group list-group-flush">
                        {list.map((tpl) => (
                          <button
                            type="button"
                            key={tpl.id}
                            className="list-group-item list-group-item-action"
                            disabled={busy}
                            onClick={() => chooseCommunity(tpl.id)}
                          >
                            <div className="d-flex justify-content-between align-items-baseline">
                              <span className="fw-semibold">{tpl.name || tpl.id}</span>
                              <span className="text-body-secondary small">
                                {typeof tpl.settings === 'number' && `${tpl.settings} config`}
                                {typeof tpl.settings === 'number' && typeof tpl.sandbox === 'number' && ' · '}
                                {typeof tpl.sandbox === 'number' && `${tpl.sandbox} world`}
                              </span>
                            </div>
                            {tpl.description && (
                              <div className="text-body-secondary small">{tpl.description}</div>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <div>
                    <label className="form-label text-body-secondary">
                      Choose a template JSON file
                    </label>
                    <input
                      type="file"
                      accept="application/json,.json"
                      className="form-control"
                      onChange={chooseFile}
                    />
                    <div className="form-text">
                      Same format as the community templates — the kind you get
                      from Export.
                    </div>
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="d-flex justify-content-between align-items-baseline mb-2">
                  <h6 className="mb-0">{template.name || 'Template'}</h6>
                  <button
                    type="button"
                    className="btn btn-sm btn-link p-0"
                    onClick={() => setTemplate(null)}
                  >
                    Choose a different one
                  </button>
                </div>
                {template.description && (
                  <p className="text-body-secondary small">{template.description}</p>
                )}

                <Section
                  title="Config (.ini)"
                  values={settings}
                  isExcluded={iniExcluded}
                  skipNote="ports, credentials and identity are never applied from a template"
                />
                <Section
                  title="World (SandboxVars)"
                  values={sandbox}
                  isExcluded={sandboxExcluded}
                  skipNote="the sandbox schema version is never applied from a template"
                />

                <div className="form-text">
                  {applicableCount} setting{applicableCount === 1 ? '' : 's'} will be
                  written across the two files; any already present are overwritten,
                  everything else is left untouched.
                </div>
              </>
            )}
          </div>

          <div className="modal-footer">
            <button className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
            {template && (
              <button
                className="btn btn-danger"
                onClick={doImport}
                disabled={busy || applicableCount === 0}
              >
                {busy ? 'Applying…' : 'Apply template'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default ServerTemplateModal;
