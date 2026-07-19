// Admin › Tasks: background server actions (install/update game files, app info) + status log.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { getStatusBadge, Spinner } from './helpers';

// Format an ISO timestamp for display.
const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : 'N/A');

// Render an arbitrary task-data value: objects/arrays as pretty JSON, else as text.
const renderValue = (value) => {
  if (value === null || value === undefined || value === '') {
    return <span className="text-body-secondary">—</span>;
  }
  if (typeof value === 'object') {
    return (
      <pre className="mb-0 p-2 bg-body-tertiary rounded small">
        <code>{JSON.stringify(value, null, 2)}</code>
      </pre>
    );
  }
  return String(value);
};

function Tasks() {
  const { token } = useAuth();
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // Track the opened task by id so the modal stays fresh across polling refreshes.
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const selectedTask = tasks.find((t) => t.id === selectedTaskId);

  useEffect(() => {
    loadData();
    // Poll task status so install/update progress shows while the page is open.
    const id = setInterval(loadData, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setError('');
    try {
      const data = await api.admin.tasks.getAll(token);
      if (data.tasks) setTasks(data.tasks);
    } catch (err) {
      console.error('Load tasks error:', err);
      setError('Failed to load tasks');
    }
    setLoading(false);
  };

  const handleCreateTask = async (action) => {
    setError('');
    try {
      await api.admin.tasks.create(token, { action });
      loadData();
    } catch (err) {
      console.error('Create task error:', err);
      setError(err.message || 'Failed to create task');
    }
  };

  return (
    <>
      <h4 className="font-display mb-3">Tasks</h4>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}

      <div className="card mb-3">
        <div className="card-body">
          <h5 className="card-title font-display mb-1">Game Server Files</h5>
          <p className="text-body-secondary">
            Install or update the Project Zomboid server via SteamCMD. The server
            can't start until the game is installed. This runs in the background and
            may take several minutes — watch the task status below (auto-refreshing).
          </p>
          <div className="d-flex gap-2 flex-wrap">
            <button className="btn btn-danger" onClick={() => handleCreateTask('update_server')}>
              <i className="fas fa-download"></i> Install / Update Game
            </button>
            <button className="btn btn-outline-light" onClick={() => handleCreateTask('get_app_info')}>
              Fetch App Info
            </button>
            <button className="btn btn-outline-light ms-auto" onClick={loadData}>
              <i className="fas fa-sync-alt"></i> Refresh
            </button>
          </div>
        </div>
      </div>

      {loading ? <Spinner /> : (
        <div className="table-responsive">
          <table className="table table-dark table-striped table-hover align-middle">
            <thead>
              <tr>
                <th>ID</th>
                <th>Action</th>
                <th>Status</th>
                <th>Result</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {tasks.length === 0 ? (
                <tr>
                  <td colSpan="5" className="text-center">No tasks found</td>
                </tr>
              ) : (
                tasks.map((task) => (
                  <tr
                    key={task.id}
                    onClick={() => setSelectedTaskId(task.id)}
                    style={{ cursor: 'pointer' }}
                    title="Click to view details"
                  >
                    <td>{task.id}</td>
                    <td>{task.action}</td>
                    <td>
                      <span className={`badge text-bg-${getStatusBadge(task.status)}`}>
                        {task.status}
                      </span>
                    </td>
                    <td className="text-body-secondary">
                      {task.data?.result
                        ? `${task.data.result}${task.data.message ? ' — ' + task.data.message : ''}`
                        : '—'}
                    </td>
                    <td>{fmt(task.updated_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Task detail modal */}
      {selectedTask && (
        <div
          className="modal show d-block"
          style={{ backgroundColor: 'rgba(0,0,0,0.8)' }}
          onClick={() => setSelectedTaskId(null)}
        >
          <div
            className="modal-dialog modal-dialog-centered modal-lg modal-dialog-scrollable"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-content">
              <div className="modal-header">
                <h5 className="modal-title font-display">
                  Task #{selectedTask.id}
                  <span className={`badge text-bg-${getStatusBadge(selectedTask.status)} ms-2`}>
                    {selectedTask.status}
                  </span>
                </h5>
                <button
                  type="button"
                  className="btn-close"
                  onClick={() => setSelectedTaskId(null)}
                ></button>
              </div>
              <div className="modal-body">
                <dl className="row mb-3">
                  <dt className="col-sm-3 text-body-secondary">Action</dt>
                  <dd className="col-sm-9">{selectedTask.action}</dd>

                  <dt className="col-sm-3 text-body-secondary">Status</dt>
                  <dd className="col-sm-9">
                    <span className={`badge text-bg-${getStatusBadge(selectedTask.status)}`}>
                      {selectedTask.status}
                    </span>
                  </dd>

                  <dt className="col-sm-3 text-body-secondary">Created</dt>
                  <dd className="col-sm-9">{fmt(selectedTask.created_at)}</dd>

                  <dt className="col-sm-3 text-body-secondary">Updated</dt>
                  <dd className="col-sm-9">{fmt(selectedTask.updated_at)}</dd>
                </dl>

                <h6 className="font-display">Attributes</h6>
                {Object.keys(selectedTask.data || {}).length === 0 ? (
                  <p className="text-body-secondary mb-0">No additional attributes.</p>
                ) : (
                  <dl className="row mb-0">
                    {Object.entries(selectedTask.data).map(([key, value]) => (
                      <React.Fragment key={key}>
                        <dt className="col-sm-3 text-body-secondary text-break">{key}</dt>
                        <dd className="col-sm-9">{renderValue(value)}</dd>
                      </React.Fragment>
                    ))}
                  </dl>
                )}
              </div>
              <div className="modal-footer">
                <button className="btn btn-outline-light" onClick={() => setSelectedTaskId(null)}>
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default Tasks;
