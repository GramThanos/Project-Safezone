// Servers list page
import React, { useState, useEffect } from 'react';
import api from '../services/api';

function Servers() {
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    loadServers();
    // Refresh every 30 seconds
    const interval = setInterval(loadServers, 30000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadServers = async () => {
    try {
      const data = await api.servers.getStatus();
      if (data.servers) {
        setServers(data.servers);
      }
      setLoading(false);
    } catch (err) {
      console.error('Load servers error:', err);
      setError('Failed to load servers');
      setLoading(false);
    }
  };

  const getStatusBadge = (state) => {
    const statusMap = {
      'running': 'success',
      'sleeping': 'warning',
      'stopped': 'secondary'
    };
    return statusMap[state?.toLowerCase()] || 'secondary';
  };

  if (loading) {
    return (
      <section className="py-5" style={{ minHeight: '50vh' }}>
        <div className="container text-center">
          <div className="spinner-border text-light" role="status">
            <span className="visually-hidden">Loading...</span>
          </div>
          <p className="mt-3">Loading servers...</p>
        </div>
      </section>
    );
  }

  return (
    <section className="py-5" style={{ minHeight: '50vh' }}>
      <div className="container">
        <div className="d-flex justify-content-between align-items-center mb-4">
          <div>
            <h2 className="text-uppercase font-display">
              Game Servers
            </h2>
            <p className="text-body-secondary">View active servers and their status</p>
          </div>
          <button className="btn btn-danger" onClick={loadServers}>
            <i className="fas fa-sync-alt"></i> Refresh
          </button>
        </div>

        {error && (
          <div className="alert alert-danger" role="alert">
            {error}
          </div>
        )}

        {servers.length === 0 ? (
          <div className="text-center py-5">
            <p className="text-body-secondary">No servers configured yet</p>
          </div>
        ) : (
          <div className="row g-4">
            {servers.map((server) => (
              <div key={server.id} className="col-md-6 col-lg-4">
                <div className="card h-100">
                  <div className="card-body">
                    <div className="d-flex justify-content-between align-items-start mb-3">
                      <h5 className="card-title font-display mb-0">{server.name}</h5>
                      <span className={`badge text-bg-${getStatusBadge(server.state)}`}>
                        {server.state || server.default_state}
                      </span>
                    </div>

                    <div className="d-flex justify-content-between mb-2">
                      <span className="text-body-secondary">
                        <i className="fas fa-network-wired"></i> Ports:
                      </span>
                      <span>{Array.isArray(server.ports) ? server.ports.join(', ') : '—'}</span>
                    </div>

                    <div className="d-flex justify-content-between">
                      <span className="text-body-secondary">
                        <i className="fas fa-toggle-on"></i> Default:
                      </span>
                      <span>{server.default_state}</span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

export default Servers;
