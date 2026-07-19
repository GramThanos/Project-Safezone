// Admin › Servers: lifecycle control, console commands, create/delete.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { getStatusBadge, Spinner } from './helpers';

function Servers() {
  const { token, isAdmin } = useAuth();
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [newServer, setNewServer] = useState({ name: '', ports: '16261, 16262', default_state: 'stopped' });
  const [commandInputs, setCommandInputs] = useState({});

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api.admin.servers.getAll(token);
      if (data.servers) setServers(data.servers);
    } catch (err) {
      console.error('Load servers error:', err);
      setError('Failed to load servers');
    }
    setLoading(false);
  };

  const handleCreateServer = async (e) => {
    e.preventDefault();
    setError('');
    // Parse the comma-separated ports field into a list of integers.
    const ports = newServer.ports
      .split(',')
      .map((p) => parseInt(p.trim(), 10))
      .filter((p) => !Number.isNaN(p));
    if (!newServer.name.trim()) {
      setError('Server name is required');
      return;
    }
    if (ports.length === 0) {
      setError('At least one valid port is required');
      return;
    }
    try {
      await api.admin.servers.create(token, {
        name: newServer.name.trim(),
        ports,
        default_state: newServer.default_state
      });
      setNewServer({ name: '', ports: '16261, 16262', default_state: 'stopped' });
      loadData();
    } catch (err) {
      console.error('Create server error:', err);
      setError(err.message || 'Failed to create server');
    }
  };

  const handleControl = async (serverId, action) => {
    setError('');
    try {
      await api.admin.servers.control(token, serverId, action);
      // Give the orchestrator a moment to react, then refresh live state.
      setTimeout(loadData, 1500);
    } catch (err) {
      console.error('Server control error:', err);
      setError(err.message || `Failed to ${action} server`);
    }
  };

  const handleSendCommand = async (serverId) => {
    const command = (commandInputs[serverId] || '').trim();
    if (!command) return;
    setError('');
    try {
      await api.admin.servers.command(token, serverId, command);
      setCommandInputs((prev) => ({ ...prev, [serverId]: '' }));
    } catch (err) {
      console.error('Send command error:', err);
      setError(err.message || 'Failed to send command');
    }
  };

  const handleDeleteServer = async (serverId) => {
    if (!window.confirm('Delete this server? This cannot be undone.')) return;
    setError('');
    try {
      await api.admin.servers.delete(token, serverId);
      loadData();
    } catch (err) {
      console.error('Delete server error:', err);
      setError(err.message || 'Failed to delete server');
    }
  };

  return (
    <>
      <h4 className="font-display mb-3">Servers</h4>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}

      {loading ? <Spinner /> : (
        <>
          <div className="table-responsive">
            <table className="table table-dark table-striped align-middle">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Ports</th>
                  <th>State</th>
                  <th>Default</th>
                  <th style={{ minWidth: '320px' }}>Controls</th>
                  {isAdmin() && <th>Manage</th>}
                </tr>
              </thead>
              <tbody>
                {servers.length === 0 ? (
                  <tr>
                    <td colSpan={isAdmin() ? 6 : 5} className="text-center">No servers found</td>
                  </tr>
                ) : (
                  servers.map((server) => (
                    <tr key={server.id}>
                      <td>{server.name}</td>
                      <td>{Array.isArray(server.ports) ? server.ports.join(', ') : '—'}</td>
                      <td>
                        <span className={`badge text-bg-${getStatusBadge(server.state || server.default_state)}`}>
                          {server.state || server.default_state}
                        </span>
                      </td>
                      <td>{server.default_state}</td>
                      <td>
                        <div className="btn-group btn-group-sm mb-2" role="group">
                          <button className="btn btn-success" onClick={() => handleControl(server.id, 'start')}>
                            <i className="fas fa-play"></i> Start
                          </button>
                          <button className="btn btn-warning" onClick={() => handleControl(server.id, 'sleep')}>
                            <i className="fas fa-moon"></i> Sleep
                          </button>
                          <button className="btn btn-secondary" onClick={() => handleControl(server.id, 'stop')}>
                            <i className="fas fa-stop"></i> Stop
                          </button>
                        </div>
                        <div className="input-group input-group-sm">
                          <input
                            type="text"
                            className="form-control"
                            placeholder="Console command"
                            value={commandInputs[server.id] || ''}
                            onChange={(e) => setCommandInputs((prev) => ({ ...prev, [server.id]: e.target.value }))}
                            onKeyDown={(e) => { if (e.key === 'Enter') handleSendCommand(server.id); }}
                          />
                          <button className="btn btn-danger" onClick={() => handleSendCommand(server.id)}>
                            Send
                          </button>
                        </div>
                      </td>
                      {isAdmin() && (
                        <td>
                          <button className="btn btn-sm btn-outline-danger" onClick={() => handleDeleteServer(server.id)}>
                            <i className="fas fa-trash"></i>
                          </button>
                        </td>
                      )}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Create server (admin only) */}
          {isAdmin() && (
            <div className="card mt-4">
              <div className="card-body">
                <h5 className="card-title font-display mb-3">Add Server</h5>
                <form className="row g-2 align-items-end" onSubmit={handleCreateServer}>
                  <div className="col-md-4">
                    <label className="form-label text-body-secondary">Name</label>
                    <input
                      type="text"
                      className="form-control"
                      placeholder="zomboid_server"
                      value={newServer.name}
                      onChange={(e) => setNewServer({ ...newServer, name: e.target.value })}
                    />
                  </div>
                  <div className="col-md-4">
                    <label className="form-label text-body-secondary">Ports (comma-separated)</label>
                    <input
                      type="text"
                      className="form-control"
                      placeholder="16261, 16262"
                      value={newServer.ports}
                      onChange={(e) => setNewServer({ ...newServer, ports: e.target.value })}
                    />
                  </div>
                  <div className="col-md-2">
                    <label className="form-label text-body-secondary">Default state</label>
                    <select
                      className="form-select"
                      value={newServer.default_state}
                      onChange={(e) => setNewServer({ ...newServer, default_state: e.target.value })}
                    >
                      <option value="stopped">stopped</option>
                      <option value="sleeping">sleeping</option>
                      <option value="running">running</option>
                    </select>
                  </div>
                  <div className="col-md-2">
                    <button type="submit" className="btn btn-danger w-100">Create</button>
                  </div>
                </form>
              </div>
            </div>
          )}
        </>
      )}
    </>
  );
}

export default Servers;
