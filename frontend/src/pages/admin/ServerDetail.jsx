// Admin › Servers › one server: everything about a single machine.
//
// The list is deliberately thin — name, state, start/stop — because that is
// what an admin scans. Everything that needs room to breathe lives here: the
// connection details, the console, backups, the config editor, and the
// destructive buttons. The log has a page of its own (`ServerLogs`), linked
// from here — it wants the whole window.
import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useDialog } from '../../context/DialogContext';
import api from '../../services/api';
import { getStatusBadge, Spinner } from './helpers';
import ServerConfig from './ServerConfig';
import ServerForm from './ServerForm';
import ServerModsEditor from './ServerModsEditor';
import { formatDateTime } from '../../utils/dates';

const humanBytes = (n) => {
  if (!n) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
};

// A backup's label as the manager will store it: `[A-Za-z0-9_-]`, at most 32
// characters. Anything else becomes a hyphen as it is typed, so the field shows
// the name that will actually be written.
const BACKUP_LABEL_MAX = 32;
const labelChars = (text) => text.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/-{2,}/g, '-');
const finishLabel = (text) => labelChars(text).replace(/^-+|-+$/g, '')
  .slice(0, BACKUP_LABEL_MAX).replace(/-+$/, '');
const slugify = (name) => finishLabel(String(name || '').toLowerCase());

// The archive name's `YYYYMMDD-HHMMSS` in UTC - the manager's format.
const backupStamp = (date) => {
  const iso = date.toISOString();
  return `${iso.slice(0, 10).replace(/-/g, '')}-${iso.slice(11, 19).replace(/:/g, '')}`;
};

// The stamp is taken by the manager at the moment the archive is written - the
// newest-first order and pruning depend on it - so it is shown ticking rather
// than offered for editing. Its own component so only it re-renders each second.
function BackupStamp({ withSeparator }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  return `${backupStamp(now)}${withSeparator ? '-' : ''}`;
}

function ServerDetail() {
  const { serverId } = useParams();
  const navigate = useNavigate();
  const { token, isAdmin } = useAuth();
  const { confirm } = useDialog();

  const [server, setServer] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [command, setCommand] = useState('');
  const [commandOutput, setCommandOutput] = useState(null);
  const [commandSuggestions, setCommandSuggestions] = useState([]);
  const [commandSuggestionsError, setCommandSuggestionsError] = useState('');
  const [commandFocused, setCommandFocused] = useState(false);

  // Backups.
  const [backupList, setBackupList] = useState([]);
  const [backupNote, setBackupNote] = useState('');
  const [backupBusy, setBackupBusy] = useState(false);
  const [backupMsg, setBackupMsg] = useState('');
  const [backupError, setBackupError] = useState('');
  const uploadInput = useRef(null);

  const [showConfig, setShowConfig] = useState(false);
  const [showEdit, setShowEdit] = useState(false);

  useEffect(() => {
    setCommandOutput(null);
    loadServer();
    loadCommandSuggestions();
    if (isAdmin()) fetchBackups();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverId]);

  // The catalog is supplied by the manager, then filtered by the backend for
  // this staff member's role. Keeping suggestions on that same source means a
  // moderator is never prompted with a command they cannot otherwise run.
  const loadCommandSuggestions = async () => {
    try {
      const data = await api.admin.actions.getAll(token);
      setCommandSuggestions(data.actions || []);
      setCommandSuggestionsError('');
    } catch (err) {
      console.error('Load console command suggestions error:', err);
      // The console remains useful if the catalog cannot be reached. Do not
      // surface a distracting page-level error for an optional convenience.
      setCommandSuggestionsError('Command suggestions are unavailable.');
    }
  };

  // Default the backup label to the server's name, so a downloaded archive says
  // which server it came from. Keyed on the name rather than every reload, so a
  // label being typed survives a start/stop refreshing the server.
  const serverName = server && server.name;
  useEffect(() => {
    setBackupNote(slugify(serverName));
  }, [serverName]);

  const loadServer = async () => {
    setError('');
    try {
      const data = await api.admin.servers.get(token, serverId);
      setServer(data.server);
    } catch (err) {
      console.error('Load server error:', err);
      setError(err.message || 'Failed to load this server');
    }
    setLoading(false);
  };

  const handleControl = async (action) => {
    setError('');
    try {
      await api.admin.servers.control(token, serverId, action);
      // Give the orchestrator a moment to react, then read the live state back.
      setTimeout(loadServer, 1500);
    } catch (err) {
      console.error('Server control error:', err);
      setError(err.message || `Failed to ${action} server`);
    }
  };

  const handleSendCommand = async () => {
    const text = command.trim();
    if (!text) return;
    setError('');
    try {
      const data = await api.admin.servers.command(token, serverId, text);
      setCommand('');
      // With RCON the console answers; over stdin it does not. Show whichever
      // happened rather than implying a result that was never returned.
      setCommandOutput(data.output
        ? { text: data.output, via: data.via }
        : { text: null, via: data.via || 'stdin' });
    } catch (err) {
      console.error('Send command error:', err);
      setError(err.message || 'Failed to send command');
    }
  };

  const commandTerms = command.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const matchingCommands = commandTerms.length === 0 ? [] : commandSuggestions
    .filter((action) => {
      const haystack = [action.command, action.template, action.label, action.description]
        .filter(Boolean).join(' ').toLowerCase();
      return commandTerms.every((term) => haystack.includes(term));
    })
    .slice(0, 7);

  const chooseCommandSuggestion = (action) => {
    setCommand(action.template || action.command);
    setCommandFocused(true);
  };

  const handleDelete = async () => {
    if (!(await confirm({
      title: 'Delete server?',
      message: `Delete ${server.name}? This cannot be undone.`,
      confirmLabel: 'Delete'
    }))) return;
    try {
      await api.admin.servers.delete(token, serverId);
      navigate('/admin/servers');
    } catch (err) {
      console.error('Delete server error:', err);
      setError(err.message || 'Failed to delete server');
    }
  };

  const fetchBackups = async () => {
    try {
      const data = await api.admin.servers.backups(token, serverId);
      setBackupList(data.backups || []);
      setBackupError('');
    } catch (err) {
      console.error('Load backups error:', err);
      setBackupError(err.message || 'Could not list backups');
    }
  };

  const handleBackup = async () => {
    setBackupBusy(true);
    setBackupError('');
    setBackupMsg('');
    try {
      await api.admin.servers.backup(token, serverId, finishLabel(backupNote));
      // The task runs in the background, so the list will not have it yet.
      setBackupMsg('Backup queued. It will appear here once the task finishes — '
        + 'watch Tasks for progress.');
      setBackupNote(slugify(serverName));
    } catch (err) {
      console.error('Backup error:', err);
      setBackupError(err.message || 'Could not queue the backup');
    }
    setBackupBusy(false);
  };

  const handleDownloadBackup = async (name) => {
    setBackupError('');
    try {
      const blob = await api.admin.servers.downloadBackup(token, serverId, name);
      // Hand the blob to the browser as a save: an object URL clicked once, then
      // revoked so it does not leak.
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Download backup error:', err);
      setBackupError(err.message || 'Could not download the backup');
    }
  };

  const handleDeleteBackup = async (name) => {
    if (!(await confirm({
      title: 'Delete backup?',
      message: `Delete ${name}? This permanently removes the archive.`,
      confirmLabel: 'Delete'
    }))) return;
    setBackupBusy(true);
    setBackupError('');
    setBackupMsg('');
    try {
      await api.admin.servers.deleteBackup(token, serverId, name);
      setBackupMsg(`Deleted ${name}.`);
      fetchBackups();
    } catch (err) {
      console.error('Delete backup error:', err);
      setBackupError(err.message || 'Could not delete the backup');
    }
    setBackupBusy(false);
  };

  const handleUploadBackup = async (e) => {
    const file = e.target.files && e.target.files[0];
    // Let the same file be picked again after an error by clearing the input.
    e.target.value = '';
    if (!file) return;
    setBackupBusy(true);
    setBackupError('');
    setBackupMsg('');
    try {
      const data = await api.admin.servers.uploadBackup(token, serverId, file);
      setBackupMsg(data.message || `Uploaded ${file.name}.`);
      fetchBackups();
    } catch (err) {
      console.error('Upload backup error:', err);
      setBackupError(err.message || 'Could not upload the backup');
    }
    setBackupBusy(false);
  };

  const handleRestore = async (name) => {
    if (!(await confirm({
      title: 'Restore backup?',
      message: `Restore ${name}? This replaces the current world on ${server.name}. `
        + 'The server must be stopped. The world being replaced is kept aside, not deleted.',
      confirmLabel: 'Restore'
    }))) return;
    setBackupBusy(true);
    setBackupError('');
    setBackupMsg('');
    try {
      await api.admin.servers.restore(token, serverId, name);
      setBackupMsg('Restore queued. Watch Tasks for the result before starting the server.');
    } catch (err) {
      console.error('Restore error:', err);
      setBackupError(err.message || 'Could not queue the restore');
    }
    setBackupBusy(false);
  };

  if (loading) return <Spinner />;

  if (!server) {
    return (
      <>
        <Link to="/admin/servers" className="btn btn-sm btn-outline-secondary mb-3">
          <i className="fas fa-arrow-left"></i> All servers
        </Link>
        <div className="alert alert-danger">{error || 'Server not found'}</div>
      </>
    );
  }

  const state = server.state || server.default_state;

  return (
    <>
      <Link to="/admin/servers" className="btn btn-sm btn-outline-secondary mb-3">
        <i className="fas fa-arrow-left"></i> All servers
      </Link>

      <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
        <div>
          <h4 className="font-display mb-0">
            {server.name}
            {server.is_primary && (
              <span className="badge text-bg-info ms-2 align-middle">primary</span>
            )}
          </h4>
          <span className={`badge text-bg-${getStatusBadge(state)}`}>{state}</span>
          <span className="text-body-secondary small ms-2">default: {server.default_state}</span>
          {server.idle_sleep_seconds > 0 && (
            <span
              className="text-body-secondary small ms-2"
              title="A running server with nobody on it is put back to sleep after this long."
            >
              sleeps when empty: {server.idle_sleep_seconds}s
            </span>
          )}
        </div>
        <div className="btn-group btn-group-sm" role="group">
          <button className="btn btn-success" onClick={() => handleControl('start')}>
            <i className="fas fa-play"></i> Start
          </button>
          <button className="btn btn-warning" onClick={() => handleControl('sleep')}>
            <i className="fas fa-moon"></i> Sleep
          </button>
          <button className="btn btn-secondary" onClick={() => handleControl('stop')}>
            <i className="fas fa-stop"></i> Stop
          </button>
          <button className="btn btn-outline-secondary" onClick={loadServer} title="Refresh state">
            <i className="fas fa-rotate"></i>
          </button>
        </div>
      </div>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}

      {/* Details */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-start">
            <h5 className="card-title font-display mb-3">Details</h5>
            {/* The log is one button, so it belongs with the other per-server
                screens rather than in a section of its own. It stays outside
                the admin check: reading a log is a moderator's job too, and
                only the buttons that change something are restricted. */}
            <div className="btn-group btn-group-sm" role="group">
              <Link
                className="btn btn-outline-secondary"
                to={`/admin/servers/${serverId}/logs`}
              >
                <i className="fas fa-file-lines"></i> Log
              </Link>
              {isAdmin() && (
                <>
                  <button className="btn btn-outline-secondary" onClick={() => setShowEdit(true)}>
                    <i className="fas fa-edit"></i> Edit
                  </button>
                  <button className="btn btn-outline-secondary" onClick={() => setShowConfig(true)}>
                    <i className="fas fa-sliders"></i> Config
                  </button>
                  <button className="btn btn-outline-danger" onClick={handleDelete}>
                    <i className="fas fa-trash"></i> Delete
                  </button>
                </>
              )}
            </div>
          </div>
          <dl className="row mb-0">
            <dt className="col-sm-3 text-body-secondary fw-normal">Address</dt>
            <dd className="col-sm-9 font-monospace">
              {server.hostname || <span className="text-body-secondary">—</span>}
            </dd>

            <dt className="col-sm-3 text-body-secondary fw-normal">Ports</dt>
            <dd className="col-sm-9 font-monospace">
              {Array.isArray(server.ports) && server.ports.length
                ? server.ports.join(', ')
                : <span className="text-body-secondary">—</span>}
            </dd>

            <dt className="col-sm-3 text-body-secondary fw-normal">Timezone</dt>
            <dd className="col-sm-9">
              {server.timezone || <span className="text-body-secondary">UTC</span>}
            </dd>

            <dt className="col-sm-3 text-body-secondary fw-normal">Description</dt>
            <dd className="col-sm-9 mb-0">
              {server.description || <span className="text-body-secondary">—</span>}
            </dd>
          </dl>
        </div>
      </div>

      {/* Console */}
      <div className="card mb-3">
        <div className="card-body">
          <h5 className="card-title font-display mb-3">Console</h5>
          <div className="position-relative">
            <div className="input-group">
              <input
                type="text"
                className="form-control"
                placeholder="Console command"
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                onFocus={() => setCommandFocused(true)}
                onBlur={() => setTimeout(() => setCommandFocused(false), 150)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleSendCommand(); }}
                aria-autocomplete="list"
                aria-expanded={commandFocused && matchingCommands.length > 0}
                aria-controls="console-command-suggestions"
              />
              <button className="btn btn-danger" onClick={handleSendCommand}>Send</button>
            </div>
            {commandFocused && matchingCommands.length > 0 && (
              <div
                id="console-command-suggestions"
                className="list-group position-absolute w-100 shadow"
                style={{ zIndex: 2 }}
                role="listbox"
              >
                {matchingCommands.map((action) => (
                  <button
                    type="button"
                    key={action.id}
                    className="list-group-item list-group-item-action text-start"
                    role="option"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => chooseCommandSuggestion(action)}
                  >
                    <span className="fw-semibold">{action.label}</span>
                    <code className="small text-body-secondary ms-2">
                      {action.template || action.command}
                    </code>
                    {action.description && (
                      <span className="small text-body-secondary d-block">{action.description}</span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="form-text">
            Start typing to search commands available to your role; choosing one fills in its editable template.
            {commandSuggestionsError && ` ${commandSuggestionsError}`}
          </div>
          {commandOutput && (
            <div className="mt-2">
              {commandOutput.text ? (
                <pre
                  className="mb-0 p-2 bg-body-tertiary rounded small"
                  style={{ whiteSpace: 'pre-wrap', maxHeight: '12rem', overflow: 'auto' }}
                >
                  <code>{commandOutput.text}</code>
                </pre>
              ) : (
                <div className="form-text">
                  Delivered — the server acknowledged writing it to its console.
                  Without RCON configured the console does not answer back, so
                  check the log for any output.
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Mods. The shared library — installing and removing the files — is
          host-level and stays on Installations; picking which of the downloaded
          ones this server loads is per-server, so it lives here. */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-center mb-3">
            <h5 className="card-title font-display mb-0">Mods</h5>
            <Link className="btn btn-sm btn-outline-secondary" to="/admin/installations">
              <i className="fas fa-hard-drive"></i> Mod library
            </Link>
          </div>
          <ServerModsEditor
            serverId={serverId}
            serverName={server.name}
            serverState={state}
            admin={isAdmin()}
          />
        </div>
      </div>

      {/* Backups */}
      {isAdmin() && (
        <div className="card mb-3">
          <div className="card-body">
            <div className="d-flex justify-content-between align-items-center mb-3">
              <h5 className="card-title font-display mb-0">Backups</h5>
              <button className="btn btn-sm btn-outline-secondary" onClick={fetchBackups}>
                Refresh
              </button>
            </div>

            {backupError && <div className="alert alert-danger">{backupError}</div>}
            {backupMsg && <div className="alert alert-success">{backupMsg}</div>}

            <p className="text-body-secondary">
              A running server is told to save and given a moment to flush before
              the archive is taken, so the world is consistent. Restoring
              requires the server to be stopped.
            </p>

            <div className="row g-2 align-items-end mb-3">
              <div className="col-md-8">
                <label className="form-label text-body-secondary" htmlFor="backup-label">
                  Name
                </label>
                <div className="input-group">
                  <span
                    className="input-group-text font-monospace"
                    title="UTC, stamped when the archive is written"
                  >
                    <BackupStamp withSeparator={finishLabel(backupNote) !== ''} />
                  </span>
                  <input
                    id="backup-label"
                    type="text"
                    className="form-control font-monospace"
                    placeholder="label (optional)"
                    maxLength={BACKUP_LABEL_MAX}
                    value={backupNote}
                    onChange={(e) => setBackupNote(labelChars(e.target.value))}
                  />
                </div>
              </div>
              <div className="col-md-4">
                <button
                  className="btn btn-danger w-100"
                  onClick={handleBackup}
                  disabled={backupBusy}
                >
                  {backupBusy ? 'Working…' : 'Back up now'}
                </button>
              </div>
            </div>

            <div className="d-flex align-items-center gap-2 mb-4">
              <input
                ref={uploadInput}
                type="file"
                accept=".gz,.tar.gz,application/gzip"
                className="d-none"
                onChange={handleUploadBackup}
              />
              <button
                className="btn btn-sm btn-outline-secondary"
                onClick={() => uploadInput.current && uploadInput.current.click()}
                disabled={backupBusy}
              >
                {backupBusy ? 'Working…' : 'Upload a backup'}
              </button>
              <small className="text-body-secondary">
                A <code>.tar.gz</code> previously downloaded from here.
              </small>
            </div>

            {backupList.length === 0 ? (
              <p className="text-body-secondary mb-0">No backups yet.</p>
            ) : (
              <div className="table-responsive">
                <table className="table table-sm align-middle mb-0">
                  <thead>
                    <tr>
                      <th>Archive</th>
                      <th>Size</th>
                      <th>Taken</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {backupList.map((b) => (
                      <tr key={b.name}>
                        <td className="text-break"><code>{b.name}</code></td>
                        <td>{humanBytes(b.bytes)}</td>
                        <td>{formatDateTime(b.created_at, '—')}</td>
                        <td>
                          <div className="d-flex gap-2 justify-content-end">
                            <button
                              className="btn btn-sm btn-outline-secondary"
                              onClick={() => handleDownloadBackup(b.name)}
                              disabled={backupBusy}
                            >
                              Download
                            </button>
                            <button
                              className="btn btn-sm btn-outline-danger"
                              onClick={() => handleRestore(b.name)}
                              disabled={backupBusy}
                            >
                              Restore
                            </button>
                            <button
                              className="btn btn-sm btn-outline-danger"
                              onClick={() => handleDeleteBackup(b.name)}
                              disabled={backupBusy}
                            >
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {showConfig && (
        <ServerConfig server={server} onClose={() => setShowConfig(false)} />
      )}

      {showEdit && (
        <ServerForm
          server={server}
          onClose={() => setShowEdit(false)}
          onSaved={() => { setShowEdit(false); loadServer(); }}
        />
      )}
    </>
  );
}

export default ServerDetail;
