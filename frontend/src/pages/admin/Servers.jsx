// Admin › Servers: the list.
//
// Deliberately just name, state and start/stop. This is the screen an admin
// scans to answer "is everything up?", and the row used to carry a console
// input, a log button, config, backups, edit and delete - which made the one
// question it exists to answer the hardest thing on it. Everything else lives
// on the server's own page.
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { getStatusBadge, Spinner } from './helpers';
import ServerForm from './ServerForm';

function Servers() {
  const navigate = useNavigate();
  const { token, isAdmin } = useAuth();
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setError('');
    try {
      const data = await api.admin.servers.getAll(token);
      setServers(data.servers || []);
    } catch (err) {
      console.error('Load servers error:', err);
      setError('Failed to load servers');
    }
    setLoading(false);
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

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h4 className="font-display mb-0">Servers</h4>
        {isAdmin() && (
          <button className="btn btn-danger" onClick={() => setShowCreate(true)}>
            <i className="fas fa-plus"></i> Add Server
          </button>
        )}
      </div>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}

      {loading ? <Spinner /> : (
        <div className="table-responsive">
          <table className="table table-striped align-middle">
            <thead>
              <tr>
                <th>Name</th>
                <th>State</th>
                <th style={{ width: '1%' }}>Controls</th>
                <th style={{ width: '1%' }}></th>
              </tr>
            </thead>
            <tbody>
              {servers.length === 0 ? (
                <tr>
                  <td colSpan={4} className="text-center">No servers found</td>
                </tr>
              ) : (
                servers.map((server) => (
                  <tr key={server.id}>
                    <td>
                      {server.name}
                      {server.is_primary && (
                        <span className="badge text-bg-info ms-2">primary</span>
                      )}
                    </td>
                    <td>
                      <span className={`badge text-bg-${getStatusBadge(server.state || server.default_state)}`}>
                        {server.state || server.default_state}
                      </span>
                    </td>
                    <td>
                      <div className="btn-group btn-group-sm text-nowrap" role="group">
                        <button className="btn btn-success" onClick={() => handleControl(server.id, 'start')}>
                          <i className="fas fa-play"></i> Start
                        </button>
                        <button className="btn btn-secondary" onClick={() => handleControl(server.id, 'stop')}>
                          <i className="fas fa-stop"></i> Stop
                        </button>
                      </div>
                    </td>
                    <td>
                      <button
                        className="btn btn-sm btn-outline-secondary text-nowrap"
                        onClick={() => navigate(`/admin/servers/${server.id}`)}
                      >
                        Manage <i className="fas fa-arrow-right"></i>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <ServerForm
          server={null}
          onClose={() => setShowCreate(false)}
          onSaved={(created) => {
            setShowCreate(false);
            // Straight to the new server's page: creating one is almost always
            // followed by configuring it.
            if (created?.id) navigate(`/admin/servers/${created.id}`);
            else loadData();
          }}
        />
      )}
    </>
  );
}

export default Servers;
