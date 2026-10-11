// Admin › Servers: a grid of cards, one per server.
//
// This is the screen an admin scans to answer "is everything up?", so a card
// carries what answers it - state, who is on, the last day's activity - and
// the controls and screens reached for most: start/sleep/stop and the log.
// Console, config, backups, edit and delete stay on the server's own page.
import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import PlayerActivityChart from '../../components/PlayerActivityChart';
import { getStatusBadge, Spinner } from './helpers';
import ServerForm from './ServerForm';

function Servers() {
  const navigate = useNavigate();
  const { token, isAdmin } = useAuth();
  const [servers, setServers] = useState([]);
  const [history, setHistory] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    // The 24h series is loaded once; a start/stop only refreshes the state.
    loadData().then(loadHistory);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setError('');
    let list = [];
    try {
      const data = await api.admin.servers.getAll(token);
      list = data.servers || [];
      setServers(list);
    } catch (err) {
      console.error('Load servers error:', err);
      setError('Failed to load servers');
    }
    setLoading(false);
    return list;
  };

  const loadHistory = async (list) => {
    const results = await Promise.all(list.map(async (server) => {
      try {
        const data = await api.servers.getHistory(server.id, 24);
        return [server.id, data.history || []];
      } catch (err) {
        console.error(`Load history error (server ${server.id}):`, err);
        return [server.id, []];
      }
    }));
    setHistory(Object.fromEntries(results));
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

      {loading ? <Spinner /> : servers.length === 0 ? (
        <div className="text-center text-body-secondary py-5">No servers found</div>
      ) : (
        <div className="row g-3">
          {servers.map((server) => {
            const state = server.state || server.default_state;
            const ports = Array.isArray(server.ports) ? server.ports.join(', ') : '';
            return (
              <div key={server.id} className="col-lg-6">
                <div className="card h-100">
                  <div className="card-body d-flex flex-column">
                    <div className="d-flex justify-content-between align-items-start gap-2 mb-2">
                      <h5 className="card-title font-display text-break mb-0">
                        {server.name}
                        {server.is_primary && (
                          <span className="badge text-bg-info ms-2 align-middle">primary</span>
                        )}
                      </h5>
                      <span className={`badge text-bg-${getStatusBadge(state)}`}>{state}</span>
                    </div>

                    {server.description && (
                      <p className="card-text text-body-secondary small mb-2">{server.description}</p>
                    )}

                    {(server.hostname || ports) && (
                      <div className="small text-body-secondary font-monospace text-break mb-2">
                        <i className="fas fa-plug me-1"></i>
                        {server.hostname || '-'}{ports && ` : ${ports}`}
                      </div>
                    )}

                    <div className="d-flex flex-wrap gap-3 small mb-2">
                      <span title="Players in game right now">
                        <i className="fas fa-signal text-success me-1"></i>
                        <strong>{server.online_count ?? '-'}</strong> online
                      </span>
                      <span title="Characters linked to an account on this server">
                        <i className="fas fa-users text-body-secondary me-1"></i>
                        <strong>{server.character_count ?? '-'}</strong> players
                      </span>
                      {server.idle_sleep_seconds > 0 && (
                        <span
                          className="text-body-secondary"
                          title="A running server with nobody on it is put back to sleep after this long."
                        >
                          <i className="fas fa-moon me-1"></i>
                          sleeps when empty: {server.idle_sleep_seconds}s
                        </span>
                      )}
                    </div>

                    {/* Activity over the last 24 hours */}
                    <div className="mb-3">
                      <PlayerActivityChart history={history[server.id] || []} height={110} />
                    </div>

                    <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mt-auto">
                      <div className="btn-group btn-group-sm text-nowrap" role="group">
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
                      <div className="btn-group btn-group-sm text-nowrap" role="group">
                        <Link className="btn btn-outline-secondary" to={`/admin/servers/${server.id}/logs`}>
                          <i className="fas fa-file-lines"></i> Log
                        </Link>
                        <button
                          className="btn btn-outline-secondary"
                          onClick={() => navigate(`/admin/servers/${server.id}`)}
                        >
                          Manage <i className="fas fa-arrow-right"></i>
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
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
