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

  const getStatusBadge = (status) => {
    const statusMap = {
      'online': 'success',
      'offline': 'secondary',
      'starting': 'warning',
      'stopping': 'warning'
    };
    return statusMap[status?.toLowerCase()] || 'secondary';
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
            <h2 style={{ fontFamily: "'Oswald', sans-serif", letterSpacing: '0.6px' }}>
              GAME SERVERS
            </h2>
            <p className="small-muted">View active servers and their status</p>
          </div>
          <button className="btn btn-accent" onClick={loadServers}>
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
            <p className="small-muted">No servers configured yet</p>
          </div>
        ) : (
          <div className="row g-4">
            {servers.map((server) => (
              <div key={server.id} className="col-md-6 col-lg-4">
                <div className="character-card">
                  <div className="d-flex justify-content-between align-items-start mb-3">
                    <h5 className="character-title mb-0">{server.name}</h5>
                    <span className={`badge bg-${getStatusBadge(server.status)}`}>
                      {server.status}
                    </span>
                  </div>

                  <div className="small-muted mb-2">
                    <i className="fas fa-server"></i> {server.host}:{server.port}
                  </div>

                  <div className="d-flex justify-content-between mb-2">
                    <span className="small-muted">
                      <i className="fas fa-users"></i> Players:
                    </span>
                    <span>{server.active_players} / {server.max_players}</span>
                  </div>

                  <div className="d-flex justify-content-between">
                    <span className="small-muted">
                      <i className="fas fa-calendar"></i> Game Day:
                    </span>
                    <span>{server.game_day || 0}</span>
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
