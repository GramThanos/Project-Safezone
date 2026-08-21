// Admin › Servers › one server: everything about a single machine.
//
// The list is deliberately thin — name, state, start/stop — because that is
// what an admin scans. Everything that needs room to breathe lives here: the
// connection details, the console, backups, the config editor, and the
// destructive buttons. The log has a page of its own (`ServerLogs`), linked
// from here — it wants the whole window.
import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { getStatusBadge, Spinner } from './helpers';
import ServerConfig from './ServerConfig';
import ServerForm from './ServerForm';

const humanBytes = (n) => {
  if (!n) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
};

function ServerDetail() {
  const { serverId } = useParams();
  const navigate = useNavigate();
  const { token, isAdmin } = useAuth();

  const [server, setServer] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [command, setCommand] = useState('');
  const [commandOutput, setCommandOutput] = useState(null);

  // Backups.
  const [backupList, setBackupList] = useState([]);
  const [backupNote, setBackupNote] = useState('');
  const [backupBusy, setBackupBusy] = useState(false);
  const [backupMsg, setBackupMsg] = useState('');
  const [backupError, setBackupError] = useState('');

  // Mods, read-only here. Choosing them is done on Installations, where the
  // shared library they are chosen from actually lives; this is the summary you
  // want when you are looking at one server and wondering why it will not boot.
  const [mods, setMods] = useState(null);

  const [showConfig, setShowConfig] = useState(false);
  const [showEdit, setShowEdit] = useState(false);

  useEffect(() => {
    setCommandOutput(null);
    loadServer();
    fetchMods();
    if (isAdmin()) fetchBackups();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverId]);

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

  const handleDelete = async () => {
    if (!window.confirm(`Delete ${server.name}? This cannot be undone.`)) return;
    try {
      await api.admin.servers.delete(token, serverId);
      navigate('/admin/servers');
    } catch (err) {
      console.error('Delete server error:', err);
      setError(err.message || 'Failed to delete server');
    }
  };

  const fetchMods = async () => {
    try {
      setMods(await api.admin.servers.mods(token, serverId));
    } catch (err) {
      // A server whose config has never been written has no mod list yet, and
      // that is not worth an error banner on the page.
      console.error('Load server mods error:', err);
      setMods(null);
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
      await api.admin.servers.backup(token, serverId, backupNote.trim());
      // The task runs in the background, so the list will not have it yet.
      setBackupMsg('Backup queued. It will appear here once the task finishes — '
        + 'watch Tasks for progress.');
      setBackupNote('');
    } catch (err) {
      console.error('Backup error:', err);
      setBackupError(err.message || 'Could not queue the backup');
    }
    setBackupBusy(false);
  };

  const handleRestore = async (name) => {
    if (!window.confirm(
      `Restore ${name}? This replaces the current world on ${server.name}. `
      + 'The server must be stopped. The world being replaced is kept aside, not deleted.'
    )) return;
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
          <div className="input-group">
            <input
              type="text"
              className="form-control"
              placeholder="Console command"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSendCommand(); }}
            />
            <button className="btn btn-danger" onClick={handleSendCommand}>Send</button>
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

      {/* Mods */}
      {mods && (
        <div className="card mb-3">
          <div className="card-body">
            <div className="d-flex justify-content-between align-items-center mb-3">
              <h5 className="card-title font-display mb-0">Mods</h5>
              <Link className="btn btn-sm btn-outline-secondary" to="/admin/installations">
                <i className="fas fa-sliders"></i> Manage
              </Link>
            </div>

            {(mods.missing_ids || []).length > 0 && (
              <div className="alert alert-warning" role="alert">
                Configured but not downloaded:{' '}
                <span className="font-monospace">{mods.missing_ids.join(', ')}</span>.
                This server will not start until they are fetched.
              </div>
            )}
            {(mods.requirement_problems || []).length > 0 && (
              <div className="alert alert-warning" role="alert">
                <div className="fw-semibold mb-1">Dependency problems</div>
                <ul className="mb-0 ps-3">
                  {mods.requirement_problems.map((problem) => (
                    <li key={`${problem.mod}:${problem.requires}:${problem.problem}`}>
                      <code>{problem.mod}</code>{' '}
                      {problem.problem === 'missing'
                        ? <>requires <code>{problem.requires}</code>, which is not enabled</>
                        : <>loads before <code>{problem.requires}</code>, which it requires</>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(mods.unknown_mod_names || []).length > 0 && (
              <div className="alert alert-warning" role="alert">
                Loaded but provided by nothing downloaded:{' '}
                <span className="font-monospace">{mods.unknown_mod_names.join(', ')}</span>.
                This is the failure that looks healthy right up until nobody can
                connect.
              </div>
            )}

            <dl className="row mb-0">
              <dt className="col-sm-3 text-body-secondary fw-normal">Workshop items</dt>
              <dd className="col-sm-9 font-monospace text-break">
                {(mods.workshop_ids || []).join('; ')
                  || <span className="text-body-secondary">none</span>}
              </dd>

              <dt className="col-sm-3 text-body-secondary fw-normal">Load order</dt>
              <dd className="col-sm-9 font-monospace text-break">
                {(mods.mod_names || []).join('; ')
                  || <span className="text-body-secondary">none</span>}
              </dd>
            </dl>
          </div>
        </div>
      )}

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

            <div className="row g-2 align-items-end mb-4">
              <div className="col-md-8">
                <label className="form-label text-body-secondary">Note (optional)</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="e.g. before-mod-update"
                  value={backupNote}
                  onChange={(e) => setBackupNote(e.target.value)}
                />
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
                        <td>{b.created_at ? new Date(b.created_at).toLocaleString() : '—'}</td>
                        <td>
                          <button
                            className="btn btn-sm btn-outline-danger"
                            onClick={() => handleRestore(b.name)}
                            disabled={backupBusy}
                          >
                            Restore
                          </button>
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
