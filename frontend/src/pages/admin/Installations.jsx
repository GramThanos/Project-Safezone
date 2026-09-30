// Admin › Servers › Installations: the game files every server runs from, and
// the shared Workshop library they draw from.
//
// Why this is not part of a server's page: there is one SteamCMD install
// directory for the whole stack, and the Workshop items downloaded into it are
// shared by every server. Installing a mod is therefore a host-level act, and it
// belongs here. Only the *selection* — which of the downloaded mods a given
// server loads, and in what order — is per-server, and that lives on the
// server's own page (`ServerModsEditor`), next to the server it configures.
import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useDialog } from '../../context/DialogContext';
import api from '../../services/api';
import { Spinner } from './helpers';

// Where an admin gets an item id from, and where they go to read about one.
const WORKSHOP_URL = (id) => `https://steamcommunity.com/sharedfiles/filedetails/?id=${id}`;

// Task actions that touch the install. While one of these is in flight the page
// polls, because the answer to "is it done" is the reason you are looking.
const INSTALL_ACTIONS = ['update_server', 'uninstall_server', 'get_app_info', 'download_workshop', 'update_mods'];

const fmtBytes = (n) => {
  if (n === null || n === undefined) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
};

// Steam records times as unix seconds, not milliseconds.
const fmtUnix = (seconds) => (seconds ? new Date(seconds * 1000).toLocaleString() : '—');

function Installations() {
  const { token, isAdmin } = useAuth();
  const { confirm } = useDialog();
  const admin = isAdmin();

  const [installation, setInstallation] = useState(null);
  const [mods, setMods] = useState([]);
  const [servers, setServers] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // Adding a mod: look up what was pasted, then confirm the download. The
  // lookup exists because SteamCMD reports success for an item id that does not
  // exist, so without it a typo costs a several-minute task before anyone finds
  // out.
  const [newItems, setNewItems] = useState('');
  const [preview, setPreview] = useState(null);
  const [metadataError, setMetadataError] = useState(null);
  const [busy, setBusy] = useState(false);
  // Opt-in, because the Workshop library survives a game reinstall and wiping
  // it as a side effect of removing the base game is a costly surprise.
  const [removeMods, setRemoveMods] = useState(false);

  // The branch to install. Empty string means public; `null` means "whatever is
  // configured", which is the default and is not the same thing.
  const [branch, setBranch] = useState(null);

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll only while something is actually running. A page that refetches
  // forever costs requests for nothing the rest of the time.
  const running = tasks.some(
    (t) => INSTALL_ACTIONS.includes(t.action) && t.status !== 'completed'
  );
  useEffect(() => {
    if (!running) return undefined;
    const id = setInterval(() => loadAll({ quiet: true }), 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  const loadAll = async ({ quiet = false } = {}) => {
    if (!quiet) setError('');
    try {
      const [inst, modData, serverData, taskData] = await Promise.all([
        api.admin.installation.get(token),
        api.admin.mods.getAll(token),
        api.admin.servers.getAll(token),
        api.admin.tasks.getAll(token)
      ]);
      setInstallation(inst);
      setMods(modData.mods || []);
      setMetadataError(modData.metadata_error || null);
      setServers(serverData.servers || []);
      setTasks(taskData.tasks || []);
    } catch (err) {
      console.error('Load installations error:', err);
      setError(err.message || 'Failed to load the installation');
    }
    setLoading(false);
  };

  // The last successful app-info fetch, which is where the *available* build
  // ids come from. It is a task result rather than a live call because asking
  // Steam means running SteamCMD, which is far too slow for a page load.
  const appInfo = tasks
    .filter((t) => t.action === 'get_app_info' && t.data && t.data.result === 'success')
    .map((t) => t.data.data)
    .find((d) => d && d.branches);

  const installed = installation && installation.installed;
  const installedBranch = (installed && installed.branch) || 'public';
  const branches = (appInfo && appInfo.branches) || {};
  const availableBuild = branches[installedBranch] && branches[installedBranch].buildid;
  const outOfDate = Boolean(installed && availableBuild && installed.buildid
    && String(availableBuild) !== String(installed.buildid));
  // The live state overlaid by the backend, falling back to the configured
  // default when the manager has not published one yet.
  const stateOf = (s) => s.state || s.default_state;
  const anyRunning = servers.some((s) => stateOf(s) === 'running');
  const branchNames = Object.keys(branches).sort();

  // Every mutating action here queues a task and refreshes; the only thing that
  // differs is which call is made, so they share this.
  const run = async (fn, successMessage) => {
    setError('');
    setNotice('');
    setBusy(true);
    try {
      const data = await fn();
      setNotice((data && data.message) || successMessage);
      await loadAll({ quiet: true });
      return true;
    } catch (err) {
      console.error('Installation action error:', err);
      setError(err.message || 'That did not work');
      return false;
    } finally {
      setBusy(false);
    }
  };

  const handleUpdateGame = async () => {
    const target = branch === null ? 'the configured branch' : (branch || 'public');
    const warning = 'Install or update the game files from ' + target + '?\n\n'
      + 'This replaces the binaries every server runs and can take several '
      + 'minutes. Servers should be stopped first.';
    if (!(await confirm({ title: 'Update game files?', message: warning, confirmLabel: 'Update' }))) return;
    run(
      () => api.admin.installation.update(token, branch === null ? undefined : branch),
      'Update queued'
    );
  };

  const handleUninstallGame = async () => {
    // Spelled out per choice rather than generically: the difference between
    // keeping and dropping the Workshop library is the difference between a
    // ten-minute reinstall and re-downloading tens of gigabytes.
    const mods = removeMods
      ? 'Your downloaded Workshop mods go too, and will have to be '
        + 'downloaded again.\n\n'
      : 'Your downloaded Workshop mods are kept.\n\n';
    const warning = 'Delete all installed game files?\n\n'
      + 'This removes the game binaries every server runs. Server configs and '
      + 'saved worlds are kept, and you can reinstall the game here '
      + 'afterwards.\n\n'
      + mods
      + 'Servers must be stopped first.';
    if (!(await confirm({ title: 'Uninstall game files?', message: warning, confirmLabel: 'Uninstall' }))) return;
    run(() => api.admin.installation.uninstall(token, !removeMods),
      'Uninstall queued');
  };

  // Split on whitespace and separators so a pasted list of URLs works as-is.
  const pastedItems = () => newItems.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);

  const handleLookup = async (e) => {
    e.preventDefault();
    const items = pastedItems();
    if (!items.length) {
      setError('Paste a Workshop item id or a Workshop page URL');
      return;
    }
    setError('');
    setNotice('');
    setBusy(true);
    try {
      setPreview(await api.admin.mods.preview(token, items));
    } catch (err) {
      console.error('Preview mods error:', err);
      setError(err.message || 'Could not look those up');
    } finally {
      setBusy(false);
    }
  };

  const handleAddMods = () => {
    // The preview already worked out what should be sent: collection ids stay
    // whole so the task expands and records their order, and anything Steam
    // says does not exist is dropped rather than handed to a SteamCMD run that
    // would report success and fetch nothing.
    const items = preview.download_items || [];
    if (!items.length) {
      setError('Nothing here can be downloaded');
      return;
    }
    run(() => api.admin.mods.install(token, items), 'Download queued')
      .then((ok) => {
        if (ok) {
          setNewItems('');
          setPreview(null);
        }
      });
  };

  const handleRemoveMod = async (item) => {
    if (!(await confirm({
      title: 'Delete Workshop item?',
      message: `Delete the downloaded files for Workshop item ${item.id}?`,
      confirmLabel: 'Delete'
    }))) return;
    run(() => api.admin.mods.remove(token, item.id), 'Workshop item removed');
  };

  if (loading) return <Spinner />;

  return (
    <>
      <div className="d-flex align-items-center mb-3">
        <h4 className="font-display mb-0">Installations</h4>
        <button
          className="btn btn-sm btn-outline-secondary border-0 ms-2"
          onClick={() => loadAll()}
          title="Refresh"
          aria-label="Refresh"
        >
          <i className="fas fa-sync-alt"></i>
        </button>
        {running && (
          <span className="badge text-bg-info ms-auto">
            <span className="spinner-border spinner-border-sm me-1" role="status"></span>
            Work in progress
          </span>
        )}
      </div>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}
      {running && (
        <div className="alert alert-info" role="alert">
          A SteamCMD task is running. Tasks are processed one at a time, so reward
          deliveries queue behind it until it finishes —{' '}
          <Link to="/admin/tasks">watch it on Tasks</Link>.
        </div>
      )}

      {/* ------------------------------------------------ Game files ----- */}
      <div className="card mb-4">
        <div className="card-header d-flex align-items-center">
          <span className="font-display">Game files</span>
          {installed
            ? <span className="badge text-bg-success ms-2">Installed</span>
            : <span className="badge text-bg-warning ms-2">Not installed</span>}
          {outOfDate && <span className="badge text-bg-warning ms-2">Update available</span>}
        </div>
        <div className="card-body">
          {installation && installation.error && (
            <div className="alert alert-warning" role="alert">{installation.error}</div>
          )}
          {!installed && (
            <p className="text-body-secondary">
              Nothing is installed yet. No server can start until the game files
              are downloaded — this is the first thing to do on a new host.
            </p>
          )}

          <dl className="row mb-3 small">
            <dt className="col-sm-3 text-body-secondary fw-normal">App</dt>
            <dd className="col-sm-9">
              {(installed && installed.name) || 'Project Zomboid Dedicated Server'}{' '}
              <span className="font-monospace text-body-secondary">
                ({installation && installation.app_id})
              </span>
            </dd>

            <dt className="col-sm-3 text-body-secondary fw-normal">Branch</dt>
            <dd className="col-sm-9">
              <span className="font-monospace">{installedBranch}</span>
              {installation && installation.configured_branch
                && installation.configured_branch !== (installed && installed.branch) && (
                <span className="text-body-secondary ms-2">
                  (configured:{' '}
                  <span className="font-monospace">{installation.configured_branch}</span>)
                </span>
              )}
            </dd>

            <dt className="col-sm-3 text-body-secondary fw-normal">Build</dt>
            <dd className="col-sm-9">
              <span className="font-monospace">{(installed && installed.buildid) || '—'}</span>
              {availableBuild && (
                <span className={outOfDate
                  ? 'ms-2 text-warning-emphasis'
                  : 'ms-2 text-body-secondary'}>
                  {outOfDate ? `→ ${availableBuild} available` : 'up to date'}
                </span>
              )}
            </dd>

            <dt className="col-sm-3 text-body-secondary fw-normal">Installed</dt>
            <dd className="col-sm-9">{fmtUnix(installed && installed.last_updated)}</dd>

            <dt className="col-sm-3 text-body-secondary fw-normal">Size</dt>
            <dd className="col-sm-9">{fmtBytes(installed && installed.size_on_disk)}</dd>

            <dt className="col-sm-3 text-body-secondary fw-normal">Location</dt>
            <dd className="col-sm-9 font-monospace text-break">
              {installation && installation.install_dir}
            </dd>

            <dt className="col-sm-3 text-body-secondary fw-normal">Launch script</dt>
            <dd className="col-sm-9 font-monospace text-break">
              {installation && installation.server_script}
              {installation && !installation.server_script_present && (
                <span className="badge text-bg-danger ms-2">missing</span>
              )}
            </dd>
          </dl>

          {installed && installation && !installation.server_script_present && (
            <div className="alert alert-warning" role="alert">
              The game is installed but the launch script is not where the manager
              expects it. A library-style install puts it under{' '}
              <code>steamapps/common/</code> instead — point <code>SERVER_SCRIPT</code>{' '}
              at the right path.
            </div>
          )}

          {anyRunning && (
            <div className="alert alert-warning" role="alert">
              A server is running. Updating the game files underneath it takes
              effect only on its next restart, and swapping files out from under a
              live world risks corrupting it. Stop your servers first.
            </div>
          )}

          {admin ? (
            <div className="d-flex gap-2 flex-wrap align-items-center">
              <div className="input-group" style={{ maxWidth: '22rem' }}>
                <label className="input-group-text" htmlFor="branch">Branch</label>
                <select
                  id="branch"
                  className="form-select"
                  value={branch === null ? '__configured__' : branch}
                  onChange={(e) => setBranch(
                    e.target.value === '__configured__' ? null : e.target.value
                  )}
                >
                  <option value="__configured__">
                    As configured
                    {installation && installation.configured_branch
                      ? ` (${installation.configured_branch})`
                      : ' (public)'}
                  </option>
                  <option value="">public</option>
                  {branchNames.filter((b) => b !== 'public').map((b) => (
                    <option key={b} value={b}>{b}</option>
                  ))}
                </select>
              </div>
              <button className="btn btn-danger" onClick={handleUpdateGame} disabled={busy}>
                <i className="fas fa-download"></i>{' '}
                {installed ? 'Update game' : 'Install game'}
              </button>
              <button
                className="btn btn-outline-secondary"
                onClick={() => run(() => api.admin.installation.appInfo(token), 'Fetch queued')}
                disabled={busy}
                title="Ask Steam which build each branch is on"
              >
                Check for updates
              </button>
              {installed && (
                <div className="d-flex align-items-center gap-2 ms-auto">
                  <div className="form-check mb-0">
                    <input
                      className="form-check-input"
                      type="checkbox"
                      id="uninstall-remove-mods"
                      checked={removeMods}
                      onChange={(e) => setRemoveMods(e.target.checked)}
                      disabled={busy || anyRunning}
                    />
                    <label
                      className="form-check-label small text-body-secondary"
                      htmlFor="uninstall-remove-mods"
                    >
                      Also remove Workshop mods
                    </label>
                  </div>
                  <button
                    className="btn btn-outline-danger"
                    onClick={handleUninstallGame}
                    disabled={busy || anyRunning}
                    title={anyRunning
                      ? 'Stop your servers before uninstalling'
                      : 'Delete the game files (configs and saved worlds are kept)'}
                  >
                    <i className="fas fa-trash"></i> Uninstall game
                  </button>
                </div>
              )}
            </div>
          ) : (
            <p className="text-body-secondary mb-0">
              Only an admin can change what is installed.
            </p>
          )}

          {branchNames.length === 0 && (
            <p className="text-body-secondary mt-2 mb-0">
              Branches are listed once app info has been fetched at least once.
            </p>
          )}
        </div>
      </div>

      {/* ------------------------------------------------ Mod library ---- */}
      <div className="card mb-4">
        <div className="card-header font-display">
          Workshop mods
          <span className="text-body-secondary ms-2 fw-normal">
            {(installation && installation.workshop && installation.workshop.item_count) || 0}
            {' '}item(s),{' '}
            {fmtBytes(installation && installation.workshop && installation.workshop.size)}
          </span>
        </div>
        <div className="card-body">
          <p className="text-body-secondary">
            Downloaded once and shared by every server. Downloading a mod does not
            switch it on — a server loads it only once it is enabled in that
            server&rsquo;s own Mods section, on the server&rsquo;s page.
            {!admin && ' Installing and removing mods is an admin job; you can '
              + 'switch the downloaded ones on and off from each server’s page.'}
          </p>

          {metadataError && (
            <div className="alert alert-warning" role="alert">
              Workshop titles are unavailable: {metadataError}. Everything below
              still works — items are shown by id.
            </div>
          )}

          {admin && (
            <form className="row g-2 align-items-start mb-3" onSubmit={handleLookup}>
              <div className="col-md">
                <textarea
                  className="form-control font-monospace"
                  rows="2"
                  placeholder="2818490036&#10;https://steamcommunity.com/sharedfiles/filedetails/?id=2822286426"
                  value={newItems}
                  onChange={(e) => { setNewItems(e.target.value); setPreview(null); }}
                ></textarea>
                <div className="form-text">
                  Workshop item ids or page URLs, one per line. A <em>collection</em>
                  URL works too and expands into everything in it, in the order its
                  author arranged them. All of it is fetched in a single SteamCMD run.
                </div>
              </div>
              <div className="col-md-auto">
                <button className="btn btn-primary" type="submit" disabled={busy}>
                  <i className="fas fa-magnifying-glass"></i> Look up
                </button>
              </div>
            </form>
          )}

          {/* What you are about to download, before spending minutes on it. */}
          {admin && preview && (
            <div className="card bg-body-tertiary mb-3">
              <div className="card-body">
                {preview.metadata_error && (
                  <p className="text-body-secondary">
                    Could not reach Steam for details ({preview.metadata_error}),
                    so these are unverified ids.
                  </p>
                )}

                {(preview.collections || []).map((collection) => (
                  <div className="alert alert-info py-2" role="alert" key={collection.id}>
                    <strong>{collection.title || 'Collection'}</strong>{' '}
                    <span className="font-monospace">{collection.id}</span> is a
                    collection — expanded to {collection.count} item(s).
                  </div>
                ))}

                {(preview.unresolved || []).map((bad) => (
                  <div className="alert alert-danger py-2" role="alert" key={bad.input}>
                    <span className="font-monospace">{bad.input}</span> — {bad.error}
                  </div>
                ))}

                {(preview.items || []).length === 0 ? (
                  <p className="mb-0 text-body-secondary">Nothing to download.</p>
                ) : (
                  <ul className="list-unstyled mb-3">
                    {preview.items.map((item) => (
                      <li key={item.id} className="d-flex gap-2 mb-2">
                        {item.preview_url && (
                          <img
                            src={item.preview_url}
                            alt=""
                            width="48"
                            height="48"
                            className="rounded flex-shrink-0"
                            style={{ objectFit: 'cover' }}
                          />
                        )}
                        <div>
                          <div>
                            <strong>{item.title || 'Unknown item'}</strong>{' '}
                            <a
                              href={WORKSHOP_URL(item.id)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="font-monospace"
                            >
                              {item.id}
                            </a>
                            {item.downloaded && (
                              <span className="badge text-bg-secondary ms-2">
                                already downloaded
                              </span>
                            )}
                            {item.found === false && (
                              <span className="badge text-bg-danger ms-2">
                                no such item
                              </span>
                            )}
                            {item.banned && (
                              <span className="badge text-bg-danger ms-2">
                                removed from the Workshop
                              </span>
                            )}
                          </div>
                          {item.summary && (
                            <div className="text-body-secondary small">{item.summary}</div>
                          )}
                          {item.size !== null && item.size !== undefined && (
                            <div className="text-body-secondary small">
                              {fmtBytes(item.size)}
                              {item.updated ? ` · updated ${fmtUnix(item.updated)}` : ''}
                            </div>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}

                <div className="d-flex gap-2">
                  <button
                    className="btn btn-primary"
                    onClick={handleAddMods}
                    disabled={busy || !(preview.download_items || []).length}
                  >
                    <i className="fas fa-download"></i> Download
                  </button>
                  <button
                    className="btn btn-outline-secondary"
                    onClick={() => setPreview(null)}
                    disabled={busy}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}

          {mods.length === 0 ? (
            <p className="text-body-secondary mb-0">No Workshop items downloaded.</p>
          ) : (
            <div className="table-responsive">
              <table className="table table-sm align-middle mb-0">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Provides</th>
                    <th className="text-nowrap">Size</th>
                    <th>Used by</th>
                    {admin && <th></th>}
                  </tr>
                </thead>
                <tbody>
                  {mods.map((item) => (
                    <tr key={item.id} className={item.missing ? 'table-warning' : undefined}>
                      <td>
                        <div className="d-flex gap-2">
                          {item.workshop && item.workshop.preview_url && (
                            <img
                              src={item.workshop.preview_url}
                              alt=""
                              width="40"
                              height="40"
                              className="rounded flex-shrink-0"
                              style={{ objectFit: 'cover' }}
                            />
                          )}
                          <div>
                            {item.workshop && item.workshop.title && (
                              <div>{item.workshop.title}</div>
                            )}
                            <a
                              href={WORKSHOP_URL(item.id)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="font-monospace small"
                            >
                              {item.id}
                            </a>
                            <div className="small text-body-secondary">
                              {item.missing
                                ? 'configured but not downloaded'
                                : fmtUnix(item.updated_at)}
                            </div>
                            {item.workshop && item.workshop.summary && (
                              <div className="small text-body-secondary">
                                {item.workshop.summary}
                              </div>
                            )}
                          </div>
                        </div>
                      </td>
                      <td>
                        {(item.mods || []).length === 0 ? (
                          <span className="text-body-secondary">—</span>
                        ) : (
                          item.mods.map((mod) => (
                            <div key={mod.id} className="mb-1">
                              <div>
                                {mod.name} <code className="small">{mod.id}</code>
                              </div>
                              {/* From the mod's own mod.info, so it is there
                                  even with no way to reach Steam. */}
                              {mod.description && (
                                <div className="small text-body-secondary">
                                  {mod.description}
                                </div>
                              )}
                            </div>
                          ))
                        )}
                      </td>
                      <td className="text-nowrap">{fmtBytes(item.size)}</td>
                      <td>
                        {(item.used_by || []).length === 0 ? (
                          <span className="text-body-secondary">nobody</span>
                        ) : (
                          item.used_by.map((name) => (
                            <span key={name} className="badge text-bg-secondary me-1">
                              {name}
                            </span>
                          ))
                        )}
                      </td>
                      {admin && (
                        <td className="text-end text-nowrap">
                          {!item.missing && (
                            <button
                              className="btn btn-sm btn-outline-danger"
                              onClick={() => handleRemoveMod(item)}
                              disabled={busy || (item.used_by || []).length > 0}
                              title={(item.used_by || []).length > 0
                                ? 'Remove it from those servers first'
                                : 'Delete the downloaded files'}
                            >
                              <i className="fas fa-trash"></i>
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <p className="text-body-secondary">
        Everything here runs as a background task.{' '}
        <Link to="/admin/tasks">Tasks</Link> has the queue and the full SteamCMD
        output.
      </p>
    </>
  );
}

export default Installations;
