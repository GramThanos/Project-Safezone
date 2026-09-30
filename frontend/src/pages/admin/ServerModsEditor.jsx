// Admin › Servers › one server › Mods: which of the downloaded Workshop items
// this server loads, and in what order.
//
// The shared mod *library* — installing and removing the files every server
// draws from — is host-level and lives on Installations. Only the selection is
// per-server, so it lives here, on the page for the server it belongs to. A
// moderator may switch downloaded mods on and off and reorder them; installing,
// downloading, and forgetting collections stay admin-only.
import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';

function ServerModsEditor({ serverId, serverName, serverState, admin }) {
  const { token } = useAuth();

  const [mods, setMods] = useState([]);
  const [collections, setCollections] = useState([]);
  const [serverMods, setServerMods] = useState(null);
  const [modsDirty, setModsDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverId]);

  const loadAll = async () => {
    setError('');
    try {
      const [modData, collectionData, serverModData] = await Promise.all([
        api.admin.mods.getAll(token),
        api.admin.mods.collections(token),
        api.admin.servers.mods(token, serverId)
      ]);
      setMods(modData.mods || []);
      setCollections(collectionData.collections || []);
      // Kept in the configured order: `Mods` is a load order, and rebuilding it
      // from a set would quietly reorder somebody's carefully sequenced list.
      setServerMods({
        workshop_ids: serverModData.workshop_ids || [],
        mod_names: serverModData.mod_names || []
      });
      setModsDirty(false);
    } catch (err) {
      console.error('Load server mods error:', err);
      setError(err.message || 'Could not read this server’s mod list');
    }
    setLoading(false);
  };

  // Save/download/forget all queue-and-refresh in the same shape; only the call
  // differs, so they share this.
  const run = async (fn, successMessage) => {
    setError('');
    setNotice('');
    setBusy(true);
    try {
      const data = await fn();
      setNotice((data && data.message) || successMessage);
      return true;
    } catch (err) {
      console.error('Server mods action error:', err);
      setError(err.message || 'That did not work');
      return false;
    } finally {
      setBusy(false);
    }
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
      () => api.admin.servers.saveMods(token, serverId,
        serverMods.workshop_ids, serverMods.mod_names),
      'Mod list saved'
    ).then((ok) => { if (ok) setModsDirty(false); });
  };

  const handleDownloadServerMods = () => {
    run(() => api.admin.servers.downloadMods(token, serverId), 'Download queued');
  };

  if (loading) return <Spinner />;

  // Computed once per render: the check rescans the library for every enabled
  // mod, and it is read in two places.
  const problems = requirementProblems();

  return (
    <>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      {(serverState === 'running' || serverState === 'booting') && (
        <div className="alert alert-warning" role="alert">
          <strong>{serverName}</strong> is running. The mod list is read at boot,
          so this takes effect on its next restart.
        </div>
      )}

      {!serverMods ? (
        <p className="text-body-secondary mb-0">Could not read this server’s mod list.</p>
      ) : (
        <>
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
                        ).then((ok) => { if (ok) loadAll(); })}
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
                  A count lower than the collection&rsquo;s size means some of its
                  items are not downloaded; those are skipped.
                </div>
              )}
            </div>
          )}

          {mods.length === 0 ? (
            <p className="text-body-secondary">
              No Workshop items downloaded, so there is nothing to load yet.{' '}
              {admin
                ? <>Install some on <Link to="/admin/installations">Installations</Link>.</>
                : 'An admin installs them on Installations.'}
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

          {/* The load order is what the game reads, so it is shown and edited
              here rather than hidden behind the checkboxes that produced it. */}
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
                {/* The literal line that ends up in the INI. Shown because it is
                    the thing being written, and because it is what somebody
                    comparing against a working server will read. */}
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
    </>
  );
}

export default ServerModsEditor;
