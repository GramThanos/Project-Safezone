// Admin › Servers: the create/edit dialog.
//
// Shared by two callers that want the same fields: the list page creates, the
// server page edits. `server` null means "create" - which is also what decides
// whether the name field is editable, since a name is fixed after creation.
import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const EMPTY_FORM = {
  name: '',
  hostname: '',
  description: '',
  ports: '16261, 16262',
  default_state: 'stopped',
  idle_sleep_seconds: '0',
  timezone: '',
  is_primary: false
};

const formFor = (server) => (server ? {
  name: server.name,
  hostname: server.hostname || '',
  description: server.description || '',
  ports: Array.isArray(server.ports) ? server.ports.join(', ') : '',
  default_state: server.default_state || 'stopped',
  idle_sleep_seconds: String(server.idle_sleep_seconds ?? 0),
  timezone: server.timezone || '',
  is_primary: !!server.is_primary
} : EMPTY_FORM);

function ServerForm({ server, onClose, onSaved }) {
  const { token } = useAuth();
  const [form, setForm] = useState(formFor(server));
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    // Parse the comma-separated ports field into a list of integers.
    const ports = form.ports
      .split(',')
      .map((p) => parseInt(p.trim(), 10))
      .filter((p) => !Number.isNaN(p));

    if (!server && !form.name.trim()) {
      setError('Server name is required');
      return;
    }
    if (ports.length === 0) {
      setError('At least one valid port is required');
      return;
    }

    // Blank reads as 0 ("never sleep on its own"), the same as typing it.
    const idleRaw = form.idle_sleep_seconds.trim();
    const idleSleep = idleRaw === '' ? 0 : Number(idleRaw);
    if (!Number.isInteger(idleSleep) || idleSleep < 0) {
      setError('Idle sleep must be a whole number of seconds, or 0 to disable it');
      return;
    }
    // Mirrors the API's floor: the roster is only refreshed every 30s, so a
    // shorter timeout could sleep on a player who has not been seen yet.
    if (idleSleep > 0 && idleSleep < 120) {
      setError('Idle sleep must be at least 120 seconds, or 0 to disable it');
      return;
    }

    // The name is fixed after creation, so it is never sent on update.
    const payload = {
      hostname: form.hostname.trim(),
      description: form.description.trim(),
      ports,
      default_state: form.default_state,
      idle_sleep_seconds: idleSleep,
      timezone: form.timezone.trim(),
      is_primary: form.is_primary
    };

    try {
      const data = server
        ? await api.admin.servers.update(token, server.id, payload)
        : await api.admin.servers.create(token, { ...payload, name: form.name.trim() });
      onSaved(data.server);
    } catch (err) {
      console.error('Save server error:', err);
      setError(err.message || 'Failed to save server');
    }
  };

  return (
    <div
      className="modal show d-block"
      style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
      onClick={onClose}
    >
      <div
        className="modal-dialog modal-dialog-centered modal-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title font-display">
              {server ? `Edit ${server.name}` : 'Add Server'}
            </h5>
            <button type="button" className="btn-close" onClick={onClose}></button>
          </div>
          <form onSubmit={handleSubmit}>
            <div className="modal-body">
              {error && <div className="alert alert-danger py-2">{error}</div>}

              <div className="mb-3">
                <label className="form-label text-body-secondary">Name</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="zomboid_server"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  disabled={!!server}
                  required={!server}
                />
                {server && (
                  <div className="form-text">The server name cannot be changed after creation.</div>
                )}
              </div>

              <div className="mb-3">
                <label className="form-label text-body-secondary">Hostname (domain or IP)</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="play.example.com"
                  value={form.hostname}
                  onChange={(e) => setForm({ ...form, hostname: e.target.value })}
                />
                <div className="form-text">Shown to players as the address to connect to.</div>
              </div>

              <div className="mb-3">
                <label className="form-label text-body-secondary">Description</label>
                <textarea
                  className="form-control"
                  rows="3"
                  placeholder="A short description shown on the public servers page."
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                ></textarea>
              </div>

              <div className="row g-2">
                <div className="col-md-8">
                  <label className="form-label text-body-secondary">Ports (comma-separated)</label>
                  <input
                    type="text"
                    className="form-control"
                    placeholder="16261, 16262"
                    value={form.ports}
                    onChange={(e) => setForm({ ...form, ports: e.target.value })}
                  />
                  <div className="form-text">The first port is used as the connection port.</div>
                </div>
                <div className="col-md-4">
                  <label className="form-label text-body-secondary">Default state</label>
                  <select
                    className="form-select"
                    value={form.default_state}
                    onChange={(e) => setForm({ ...form, default_state: e.target.value })}
                  >
                    <option value="stopped">stopped</option>
                    <option value="sleeping">sleeping</option>
                    <option value="running">running</option>
                  </select>
                  <div className="form-text">Applied when the manager starts. Live start/stop is not saved here.</div>
                </div>
              </div>

              <div className="mt-3">
                <label className="form-label text-body-secondary">
                  Sleep when empty (seconds)
                </label>
                <input
                  type="number"
                  min="0"
                  step="1"
                  className="form-control"
                  placeholder="0"
                  value={form.idle_sleep_seconds}
                  onChange={(e) => setForm({ ...form, idle_sleep_seconds: e.target.value })}
                />
                <div className="form-text">
                  How long the server may run with nobody online before it is put
                  to sleep and can be woken again by a connection. The countdown
                  only starts once the world has finished loading, and resets the
                  moment anyone joins. 0 disables it — the server stays up until
                  somebody stops it. Minimum 120 seconds, because the player list
                  is only refreshed every 30.
                </div>
              </div>

              <div className="mt-3">
                <label className="form-label text-body-secondary">Timezone (optional)</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="Europe/Athens"
                  value={form.timezone}
                  onChange={(e) => setForm({ ...form, timezone: e.target.value })}
                />
                <div className="form-text">
                  IANA name. Leave blank to use UTC.
                </div>
              </div>

              <div className="mt-3 form-check">
                <input
                  className="form-check-input"
                  type="checkbox"
                  id="server-is-primary"
                  checked={form.is_primary}
                  onChange={(e) => setForm({ ...form, is_primary: e.target.checked })}
                />
                <label className="form-check-label" htmlFor="server-is-primary">
                  Primary server
                </label>
                <div className="form-text">
                  The primary server's timezone decides when daily loot boxes
                  reset. Only one server can be primary — marking this one
                  unmarks any other.
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn btn-outline-secondary" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" className="btn btn-danger">
                {server ? 'Save Changes' : 'Create Server'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

export default ServerForm;
