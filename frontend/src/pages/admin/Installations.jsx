// Admin › Servers › Installations: the game files every server runs from, and
// the Workshop content they load.
//
// Why this is not part of a server's page: there is one SteamCMD install
// directory for the whole stack, and the Workshop items downloaded into it are
// shared by every server. Installing a mod is therefore a host-level act, and
// only the *selection* — which of the downloaded mods a given server loads — is
// per-server. The page is laid out along that seam: what is on the machine
// first, then who uses it.
import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';

// Where an admin gets an item id from, and where they go to read about one.
const WORKSHOP_URL = (id) => `https://steamcommunity.com/sharedfiles/filedetails/?id=${id}`;

// Task actions that touch the install. While one of these is in flight the page
// polls, because the answer to "is it done" is the reason you are looking.
const INSTALL_ACTIONS = ['update_server', 'get_app_info', 'download_workshop', 'update_mods'];

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
  const admin = isAdmin();

  const [installation, setInstallation] = useState(null);
  const [mods, setMods] = useState([]);
  const [collections, setCollections] = useState([]);
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

  // The branch to install. Empty string means public; `null` means "whatever is
  // configured", which is the default and is not the same thing.
  const [branch, setBranch] = useState(null);

  // Per-server selection.
  const [selectedServer, setSelectedServer] = useState('');
  const [serverMods, setServerMods] = useState(null);
  const [modsDirty, setModsDirty] = useState(false);
  // Which server the newest in-flight mod request is for, so a slower earlier
  // one cannot land on top of it.
  const latestServerRequest = useRef(null);

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
      const [inst, modData, collectionData, serverData, taskData] = await Promise.all([
        api.admin.installation.get(token),
        api.admin.mods.getAll(token),
        api.admin.mods.collections(token),
        api.admin.servers.getAll(token),
        api.admin.tasks.getAll(token)
      ]);
      setInstallation(inst);
      setMods(modData.mods || []);
      setCollections(collectionData.collections || []);
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

  const handleUpdateGame = () => {
    const target = branch === null ? 'the configured branch' : (branch || 'public');
    const warning = 'Install or update the game files from ' + target + '?\n\n'
      + 'This replaces the binaries every server runs and can take several '
      + 'minutes. Servers should be stopped first.';
    if (!window.confirm(warning)) return;
    run(
      () => api.admin.installation.update(token, branch === null ? undefined : branch),
      'Update queued'
    );
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

  const handleRemoveMod = (item) => {
    if (!window.confirm(`Delete the downloaded files for Workshop item ${item.id}?`)) return;
    run(() => api.admin.mods.remove(token, item.id), 'Workshop item removed');
  };

  // Per-server selection --------------------------------------------------

  const loadServerMods = async (serverId) => {
    setServerMods(null);
    setModsDirty(false);
    if (!serverId) return;
    try {
      const data = await api.admin.servers.mods(token, serverId);
      // Two quick changes of server can land out of order, and showing one
      // server's mod list under another's name is worse than showing nothing.
      if (String(latestServerRequest.current) !== String(serverId)) return;
      // Kept in the configured order: `Mods` is a load order, and rebuilding it
      // from a set would quietly reorder somebody's carefully sequenced list.
      setServerMods({
        workshop_ids: data.workshop_ids || [],
        mod_names: data.mod_names || []
      });
    } catch (err) {
      console.error('Load server mods error:', err);
      setError(err.message || 'Could not read that server’s mod list');
    }
  };

  const handleSelectServer = (serverId) => {
    latestServerRequest.current = serverId;
    setSelectedServer(serverId);
    setError('');
    setNotice('');
    loadServerMods(serverId);
  };

  // Every name an item's mods answer to. Used when switching an item off, so a
  // server configured by folder name does not keep the orphaned entries.
  const namesOf = (item) => {
    const names = [];
    (item.mods || []).forEach((mod) => {
      if (mod.id) names.push(mod.id);
      if (mod.folder && mod.folder !== mod.id) names.push(mod.folder);
    });
    return names;
  };

  // Toggling an item toggles the mods it provides with it. They are two halves
  // of one decision — files to download, names to load — and letting them drift
  // apart is exactly how a server ends up healthy-looking and unjoinable.
  const toggleItem = (item, enabled) => {
    setServerMods((current) => {
      if (!current) return current;
      if (enabled) {
        // Only the canonical ids are added; both are recognised on removal.
        const adding = (item.mods || []).map((m) => m.id);
        return {
          workshop_ids: current.workshop_ids.includes(item.id)
            ? current.workshop_ids
            : current.workshop_ids.concat([item.id]),
          mod_names: current.mod_names.concat(
            adding.filter((id) => !current.mod_names.includes(id))
          )
        };
      }
      const provided = namesOf(item);
      return {
        workshop_ids: current.workshop_ids.filter((id) => id !== item.id),
        mod_names: current.mod_names.filter((name) => !provided.includes(name))
      };
    });
    setModsDirty(true);
  };

  // A single mod inside an item, for the items that ship several and where only
  // some of them are wanted.
  const toggleModName = (item, modId, enabled) => {
    setServerMods((current) => {
      if (!current) return current;
      const names = enabled
        ? (current.mod_names.includes(modId)
          ? current.mod_names
          : current.mod_names.concat([modId]))
        : current.mod_names.filter((n) => n !== modId);
      // Loading any mod of an item requires the item itself to be downloaded.
      const ids = enabled && !current.workshop_ids.includes(item.id)
        ? current.workshop_ids.concat([item.id])
        : current.workshop_ids;
      return { workshop_ids: ids, mod_names: names };
    });
    setModsDirty(true);
  };

  // Move one mod in the load order. `Mods` is read in order and some mods only
  // work when they come after what they extend, so the order is a real setting
  // and not a presentation detail. Up/down rather than drag-and-drop: it needs
  // no library, works from the keyboard, and is exact when the list is long.
  const moveMod = (index, delta) => {
    setServerMods((current) => {
      if (!current) return current;
      const target = index + delta;
      if (target < 0 || target >= current.mod_names.length) return current;
      const names = current.mod_names.slice();
      const [moved] = names.splice(index, 1);
      names.splice(target, 0, moved);
      return { workshop_ids: current.workshop_ids, mod_names: names };
    });
    setModsDirty(true);
  };

  // What an enabled mod is called, for the load-order list. The name lives on
  // the library entry that provides it, which the ordered list does not carry.
  const modEntry = (modId) => {
    for (const item of mods) {
      const found = (item.mods || []).find(
        (m) => m.id === modId || m.folder === modId
      );
      if (found) return found;
    }
    return null;
  };
  const modLabel = (modId) => (modEntry(modId) || {}).name || null;

  // Dependency problems in the order as it currently stands. Checked here as
  // well as on the server so reordering gives an answer immediately — the point
  // of the arrows is to fix this, and having to save to find out whether you
  // did would make them guesswork.
  const requirementProblems = () => {
    if (!serverMods) return [];

    // A Map, not an object: mod names are arbitrary strings, and `'toString' in
    // {}` is true, which would report an unmet requirement as satisfied.
    // Positions are keyed by canonical id so a config written with folder names
    // is checked rather than dismissed.
    const canonical = (name) => (modEntry(name) || {}).id || name;
    const position = new Map();
    serverMods.mod_names.forEach((name, index) => {
      const key = canonical(name);
      if (!position.has(key)) position.set(key, index);
    });

    const problems = [];
    serverMods.mod_names.forEach((name, index) => {
      const entry = modEntry(name);
      if (!entry) return;
      (entry.requires || []).forEach((required) => {
        const key = canonical(required);
        if (!position.has(key)) {
          problems.push({ mod: name, requires: required, problem: 'missing' });
        } else if (position.get(key) > index) {
          problems.push({ mod: name, requires: required, problem: 'order' });
        }
      });
    });
    return problems;
  };

  // Enable everything a collection contains, in the order its author chose.
  // Adopting a community's collection wholesale is the common case, and doing
  // it by hand means ticking dozens of boxes and then sorting them.
  const applyCollection = (collection) => {
    if (!serverMods) return;
    const downloaded = new Set(collection.downloaded || []);
    const ids = serverMods.workshop_ids.slice();
    const names = serverMods.mod_names.slice();
    let added = 0;
    let skipped = 0;

    (collection.items || []).forEach((itemId) => {
      // A member that was never downloaded, or was deleted since, is skipped
      // rather than written into the config as an entry that breaks the server.
      if (!downloaded.has(itemId)) { skipped += 1; return; }
      if (!ids.includes(itemId)) { ids.push(itemId); added += 1; }
      const entry = mods.find((m) => m.id === itemId);
      (entry ? entry.mods || [] : []).forEach((mod) => {
        if (!names.includes(mod.id) && !names.includes(mod.folder)) {
          names.push(mod.id);
        }
      });
    });

    const label = collection.title || collection.id;
    if (!added) {
      setNotice(skipped
        ? `Nothing to add from ${label} — none of its remaining items are downloaded.`
        : `${label} is already fully enabled.`);
      return;
    }

    setServerMods({ workshop_ids: ids, mod_names: names });
    setModsDirty(true);
    setNotice(`Added ${added} item(s) from ${label} in its published order`
      + (skipped ? `, skipping ${skipped} not downloaded` : '')
      + '. Review the load order, then save.');
  };

  const handleSaveServerMods = () => {
    if (!serverMods) return;
    run(
      () => api.admin.servers.saveMods(token, selectedServer,
        serverMods.workshop_ids, serverMods.mod_names),
      'Mod list saved'
    ).then((ok) => { if (ok) setModsDirty(false); });
  };

  const handleDownloadServerMods = () => {
    run(() => api.admin.servers.downloadMods(token, selectedServer), 'Download queued');
  };

  if (loading) return <Spinner />;

  const selected = servers.find((s) => String(s.id) === String(selectedServer));
  // Computed once per render: the check rescans the library for every enabled
  // mod, and it is read in two places.
  const problems = requirementProblems();

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
            switch it on — a server loads it only once it is in that server&rsquo;s
            list below.
            {!admin && ' Installing and removing mods is an admin job; below, you '
              + 'can switch the downloaded ones on and off per server.'}
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

      {/* ------------------------------------------- Per-server mods ----- */}
      <div className="card mb-4">
        <div className="card-header font-display">Mods per server</div>
        <div className="card-body">
          <div className="mb-3" style={{ maxWidth: '24rem' }}>
            <label className="form-label" htmlFor="server">Server</label>
            <select
              id="server"
              className="form-select"
              value={selectedServer}
              onChange={(e) => handleSelectServer(e.target.value)}
            >
              <option value="">Choose a server…</option>
              {servers.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>

          {!selectedServer && (
            <p className="text-body-secondary mb-0">
              Pick a server to choose which of the downloaded mods it loads.
              {!admin && ' Only mods that are already downloaded can be switched on.'}
            </p>
          )}

          {selectedServer && !serverMods && <Spinner />}

          {selectedServer && serverMods && (
            <>
              {selected && stateOf(selected) === 'running' && (
                <div className="alert alert-warning" role="alert">
                  <strong>{selected.name}</strong> is running. The mod list is read
                  at boot, so this takes effect on its next restart.
                </div>
              )}

              {collections.length > 0 && (
                <div className="mb-3">
                  <label className="form-label text-body-secondary mb-1">
                    Apply a collection
                  </label>
                  <div className="d-flex gap-2 flex-wrap">
                    {collections.map((collection) => (
                      <div className="btn-group btn-group-sm" key={collection.id}>
                        <button
                          className="btn btn-outline-primary"
                          onClick={() => applyCollection(collection)}
                          title={`Enable this collection's ${(collection.downloaded || []).length} downloaded mod(s), in the order its author chose`}
                        >
                          <i className="fas fa-layer-group"></i>{' '}
                          {collection.title || collection.id}
                          <span className="ms-1 text-body-secondary">
                            ({(collection.downloaded || []).length})
                          </span>
                        </button>
                        {admin && (
                          <button
                            className="btn btn-outline-secondary"
                            onClick={() => run(
                              () => api.admin.mods.forgetCollection(token, collection.id),
                              'Collection forgotten'
                            )}
                            title="Forget this collection. The mods it brought in stay."
                            aria-label={`Forget ${collection.title || collection.id}`}
                          >
                            <i className="fas fa-xmark"></i>
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                  {collections.some((c) => (c.missing || []).length > 0) && (
                    <div className="form-text">
                      A count lower than the collection&rsquo;s size means some of
                      its items are not downloaded; those are skipped.
                    </div>
                  )}
                </div>
              )}

              {mods.length === 0 ? (
                <p className="text-body-secondary">
                  Download a Workshop item above before assigning it.
                </p>
              ) : (
                <div className="table-responsive mb-3">
                  <table className="table table-sm align-middle mb-0">
                    <tbody>
                      {mods.map((item) => {
                        const provided = item.mods || [];
                        const on = serverMods.workshop_ids.includes(item.id);
                        return (
                          <React.Fragment key={item.id}>
                            <tr>
                              <td style={{ width: '2rem' }}>
                                <input
                                  type="checkbox"
                                  className="form-check-input"
                                  checked={on}
                                  disabled={!admin && item.missing && !on}
                                  onChange={(e) => toggleItem(item, e.target.checked)}
                                  title={!admin && item.missing && !on
                                    ? 'Not downloaded — only an admin can install it'
                                    : undefined}
                                  aria-label={`Use Workshop item ${item.id}`}
                                />
                              </td>
                              <td>
                                {item.workshop && item.workshop.title
                                  ? item.workshop.title
                                  : (provided.length === 1 ? provided[0].name : null)}
                                <span className="font-monospace small text-body-secondary ms-2">
                                  {item.id}
                                </span>
                                {item.missing && (
                                  <span className="badge text-bg-warning ms-2">
                                    not downloaded
                                  </span>
                                )}
                              </td>
                            </tr>
                            {/* Only worth splitting out when there is a choice to
                                make: most items provide exactly one mod. */}
                            {provided.length > 1 && provided.map((mod) => (
                              <tr key={`${item.id}:${mod.id}`}>
                                <td></td>
                                <td className="ps-4">
                                  <input
                                    type="checkbox"
                                    className="form-check-input me-2"
                                    checked={serverMods.mod_names.includes(mod.id)}
                                    onChange={(e) => toggleModName(item, mod.id, e.target.checked)}
                                    id={`mod-${item.id}-${mod.id}`}
                                  />
                                  <label htmlFor={`mod-${item.id}-${mod.id}`}>
                                    {mod.name} <code className="small">{mod.id}</code>
                                  </label>
                                </td>
                              </tr>
                            ))}
                          </React.Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {/* The load order is what the game reads, so it is shown and
                  edited here rather than hidden behind the checkboxes that
                  produced it. */}
              {problems.length > 0 && (
                <div className="alert alert-warning" role="alert">
                  <div className="fw-semibold mb-1">Dependency problems</div>
                  <ul className="mb-0 ps-3">
                    {problems.map((problem) => (
                      <li key={`${problem.mod}:${problem.requires}:${problem.problem}`}>
                        <code>{problem.mod}</code>{' '}
                        {problem.problem === 'missing' ? (
                          <>requires <code>{problem.requires}</code>, which is not enabled</>
                        ) : (
                          <>must load after <code>{problem.requires}</code> — move it down,
                            or move <code>{problem.requires}</code> up</>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="mb-3">
                <label className="form-label text-body-secondary mb-1">
                  Load order (<code>Mods=</code>)
                </label>
                {serverMods.mod_names.length === 0 ? (
                  <p className="text-body-secondary mb-0">
                    Nothing enabled — this server loads no mods.
                  </p>
                ) : (
                  <>
                    <p className="text-body-secondary small">
                      Mods load top to bottom. One that extends another has to come
                      after it, so if a mod misbehaves this is the first thing to
                      check.
                    </p>
                    <ol className="list-group list-group-numbered mb-2">
                      {serverMods.mod_names.map((modId, index) => (
                        <li
                          key={modId}
                          className="list-group-item d-flex align-items-center gap-2 py-1"
                        >
                          <span className="me-auto">
                            {modLabel(modId) && (
                              <span className="me-2">{modLabel(modId)}</span>
                            )}
                            <code className="small">{modId}</code>
                            {!modLabel(modId) && (
                              <span className="badge text-bg-warning ms-2">
                                nothing downloaded provides this
                              </span>
                            )}
                          </span>
                          {admin && (
                            <div className="btn-group btn-group-sm" role="group">
                              <button
                                className="btn btn-outline-secondary"
                                onClick={() => moveMod(index, -1)}
                                disabled={index === 0}
                                title="Load earlier"
                                aria-label={`Move ${modId} earlier`}
                              >
                                <i className="fas fa-arrow-up"></i>
                              </button>
                              <button
                                className="btn btn-outline-secondary"
                                onClick={() => moveMod(index, 1)}
                                disabled={index === serverMods.mod_names.length - 1}
                                title="Load later"
                                aria-label={`Move ${modId} later`}
                              >
                                <i className="fas fa-arrow-down"></i>
                              </button>
                            </div>
                          )}
                        </li>
                      ))}
                    </ol>
                    {/* The literal line that ends up in the INI. Shown because
                        it is the thing being written, and because it is what
                        somebody comparing against a working server will read. */}
                    <pre
                      className="p-2 bg-body-tertiary rounded small mb-0"
                      style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
                    >
                      <code>Mods={serverMods.mod_names.join(';')}</code>
                    </pre>
                  </>
                )}
              </div>

              <div className="d-flex gap-2 flex-wrap">
                <button
                  className="btn btn-primary"
                  onClick={handleSaveServerMods}
                  disabled={busy || !modsDirty}
                >
                  Save mod list
                </button>
                {admin && (
                  <button
                    className="btn btn-outline-secondary"
                    onClick={handleDownloadServerMods}
                    disabled={busy || modsDirty}
                    title={modsDirty
                      ? 'Save first — the download reads the saved list'
                      : 'Download everything this server is configured to load'}
                  >
                    <i className="fas fa-download"></i> Download this server&rsquo;s mods
                  </button>
                )}
                {modsDirty && (
                  <span className="align-self-center text-body-secondary">
                    Unsaved changes.
                  </span>
                )}
              </div>
            </>
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
