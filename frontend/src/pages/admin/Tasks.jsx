// Admin › Tasks: the background work queue and its results.
//
// This page no longer *starts* anything. Installing game files and downloading
// mods moved to Installations, where the state those actions change is visible;
// what is left here is the honest job of a queue — what ran, what it said, and
// getting rid of the finished ones.
import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { getStatusBadge, Spinner } from './helpers';

// Format an ISO timestamp for display.
const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : 'N/A');

// Render an arbitrary task-data value. Everything goes in a <pre> block: values
// are often multi-line (e.g. captured SteamCMD output), so newlines must survive.
const renderValue = (value) => {
  if (value === null || value === undefined || value === '') {
    return <span className="text-body-secondary">—</span>;
  }
  const text = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
  return (
    <pre
      className="mb-0 p-2 bg-body-tertiary rounded small"
      style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: '40vh', overflow: 'auto' }}
    >
      <code>{text}</code>
    </pre>
  );
};

function Tasks() {
  const { token } = useAuth();
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
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

  // Only pending/completed tasks are removable - the worker owns anything mid-flight,
  // so a rejection here is expected rather than an error to hide.
  const handleDeleteTask = async (id) => {
    setError('');
    setNotice('');
    try {
      await api.admin.tasks.remove(token, id);
      setSelectedTaskId(null);
      loadData();
    } catch (err) {
      console.error('Delete task error:', err);
      setError(err.message || 'Could not delete that task');
    }
  };

  const handleClearTasks = async () => {
    if (!window.confirm('Remove every pending and completed task? Tasks currently processing are kept.')) return;
    setError('');
    try {
      const data = await api.admin.tasks.clear(token);
      setSelectedTaskId(null);
      setNotice(typeof data.count === 'number' ? `Cleared ${data.count} task(s).` : 'Tasks cleared.');
      loadData();
    } catch (err) {
      console.error('Clear tasks error:', err);
      setError(err.message || 'Could not clear the queue');
    }
  };

  return (
    <>
      <h4 className="font-display mb-3">Tasks</h4>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      {loading ? <Spinner /> : (
        <div className="table-responsive">
          <table className="table table-striped table-hover align-middle">
            <thead>
              <tr>
                <th>ID</th>
                <th>Action</th>
                <th>Status</th>
                <th>Result</th>
                {/* Refresh sits here as well as on the card below: this column
                    is what you are watching while a task runs, and the other
                    button is now past the end of the table. */}
                <th className="text-nowrap">
                  Updated
                  <button
                    className="btn btn-sm btn-outline-secondary border-0 ms-2 py-0"
                    onClick={loadData}
                    title="Refresh tasks"
                    aria-label="Refresh tasks"
                  >
                    <i className="fas fa-sync-alt"></i>
                  </button>
                </th>
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

      <div className="card mt-3">
        <div className="card-body">
          <p className="text-body-secondary">
            Installing or updating the game files and downloading mods now live on{' '}
            <Link to="/admin/installations">Installations</Link>, next to the state
            they change. Their output still lands here.
          </p>
          <div className="d-flex gap-2 flex-wrap">
            <button className="btn btn-outline-secondary" onClick={loadData}>
              <i className="fas fa-sync-alt"></i> Refresh
            </button>
            <button
              className="btn btn-outline-danger ms-auto"
              onClick={handleClearTasks}
              disabled={tasks.length === 0}
              title="Removes pending and completed tasks; anything processing is kept"
            >
              <i className="fas fa-trash"></i> Clear Finished
            </button>
          </div>
        </div>
      </div>

      {/* Task detail modal */}
      {selectedTask && (
        <div
          className="modal show d-block"
          style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
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
                <button
                  className="btn btn-outline-danger me-auto"
                  onClick={() => handleDeleteTask(selectedTask.id)}
                  disabled={selectedTask.status === 'processing'}
                  title={selectedTask.status === 'processing'
                    ? 'This task is being processed and cannot be removed'
                    : 'Remove this task'}
                >
                  <i className="fas fa-trash"></i> Delete
                </button>
                <button className="btn btn-outline-secondary" onClick={() => setSelectedTaskId(null)}>
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
