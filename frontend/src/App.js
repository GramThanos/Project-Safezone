import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:5000';

function App() {
  const [health, setHealth] = useState(null);
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchHealth();
    fetchServers();
  }, []);

  const fetchHealth = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/health`);
      setHealth(response.data);
    } catch (err) {
      setError('Failed to connect to backend');
      console.error('Health check failed:', err);
    }
  };

  const fetchServers = async () => {
    try {
      setLoading(true);
      const response = await axios.get(`${API_URL}/api/servers`);
      setServers(response.data.servers || []);
      setError(null);
    } catch (err) {
      setError('Failed to fetch servers');
      console.error('Fetch servers failed:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>🏚️ Project Safehouse</h1>
        <p className="subtitle">Project Zomboid Server Manager</p>
      </header>

      <main className="App-main">
        <section className="status-section">
          <h2>System Status</h2>
          {health ? (
            <div className="status-card">
              <div className="status-item">
                <span className="status-label">API Status:</span>
                <span className={`status-value ${health.status === 'healthy' ? 'success' : 'error'}`}>
                  {health.status}
                </span>
              </div>
              <div className="status-item">
                <span className="status-label">Database:</span>
                <span className={`status-value ${health.database === 'connected' ? 'success' : 'error'}`}>
                  {health.database}
                </span>
              </div>
            </div>
          ) : (
            <p className="loading">Checking system status...</p>
          )}
        </section>

        <section className="servers-section">
          <h2>Servers</h2>
          {error && <div className="error-message">{error}</div>}
          {loading ? (
            <p className="loading">Loading servers...</p>
          ) : servers.length > 0 ? (
            <div className="servers-grid">
              {servers.map((server) => (
                <div key={server.id} className="server-card">
                  <h3>{server.name}</h3>
                  <div className="server-info">
                    <p>Status: <span className={`badge ${server.status}`}>{server.status}</span></p>
                    <p>Port: {server.port}</p>
                    <p>Max Players: {server.max_players}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <p>No servers configured yet.</p>
              <p className="empty-hint">Add your first Project Zomboid server to get started!</p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

export default App;
