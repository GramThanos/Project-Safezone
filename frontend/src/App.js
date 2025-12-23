import React, { useState, useEffect } from 'react';

function App() {
  const [systemStatus, setSystemStatus] = useState(null);
  const [serverStatus, setServerStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  const getStatusClass = (value) => {
    const lowerValue = value.toLowerCase();
    if (lowerValue === 'healthy' || lowerValue === 'running') return 'status-healthy';
    if (lowerValue === 'connected') return 'status-connected';
    if (lowerValue === 'disconnected' || lowerValue === 'not_installed') return 'status-disconnected';
    if (lowerValue === 'stopped') return 'status-stopped';
    return 'status-unknown';
  };

  const loadSystemStatus = async () => {
    try {
      const response = await fetch('/health');
      const data = await response.json();
      setSystemStatus(data);
    } catch (error) {
      console.error('Error loading system status:', error);
      setSystemStatus({ error: 'Failed to load' });
    }
  };

  const loadServerStatus = async () => {
    try {
      const response = await fetch('/api/server/status');
      const data = await response.json();
      setServerStatus(data);
    } catch (error) {
      console.error('Error loading server status:', error);
      setServerStatus({ error: 'Failed to load' });
    }
  };

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([loadSystemStatus(), loadServerStatus()]);
      setLoading(false);
    };

    loadData();
    const interval = setInterval(loadData, 10000); // Refresh every 10 seconds

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="container">
      <header>
        <h1>🏠 Project Safehouse</h1>
        <p className="subtitle">Project Zomboid Dedicated Server Manager</p>
      </header>

      <div className="dashboard">
        <div className="card">
          <h2>System Status</h2>
          {loading && !systemStatus ? (
            <div className="loading">
              <div className="spinner"></div>
              <p>Loading...</p>
            </div>
          ) : systemStatus && !systemStatus.error ? (
            <div>
              <div className="status-item">
                <span className="status-label">Application</span>
                <span className={`status-value ${getStatusClass(systemStatus.status)}`}>
                  {systemStatus.status}
                </span>
              </div>
              <div className="status-item">
                <span className="status-label">Database</span>
                <span className={`status-value ${getStatusClass(systemStatus.database)}`}>
                  {systemStatus.database}
                </span>
              </div>
              <div className="status-item">
                <span className="status-label">Cache</span>
                <span className={`status-value ${getStatusClass(systemStatus.cache)}`}>
                  {systemStatus.cache}
                </span>
              </div>
            </div>
          ) : (
            <p>Error loading status</p>
          )}
        </div>

        <div className="card">
          <h2>Game Server</h2>
          {loading && !serverStatus ? (
            <div className="loading">
              <div className="spinner"></div>
              <p>Loading...</p>
            </div>
          ) : serverStatus && !serverStatus.error ? (
            <div>
              <div className="status-item">
                <span className="status-label">Server Status</span>
                <span className={`status-value ${getStatusClass(serverStatus.status)}`}>
                  {serverStatus.status}
                </span>
              </div>
              <div className="status-item">
                <span className="status-label">Last Update</span>
                <span className="status-value status-unknown">
                  {serverStatus.last_update}
                </span>
              </div>
            </div>
          ) : (
            <p>Error loading server status</p>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
