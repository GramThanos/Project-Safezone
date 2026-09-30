// Admin › Audit Log: recent administrative actions.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useDialog } from '../../context/DialogContext';
import api from '../../services/api';
import { Spinner } from './helpers';

function Audit() {
  const { token, isAdmin } = useAuth();
  const { confirm } = useDialog();
  const [auditEntries, setAuditEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showClear, setShowClear] = useState(false);
  const [keepDays, setKeepDays] = useState('');
  const [clearing, setClearing] = useState(false);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api.admin.audit.getAll(token);
      if (data.entries) setAuditEntries(data.entries);
    } catch (err) {
      console.error('Load audit error:', err);
      setError('Failed to load audit log');
    }
    setLoading(false);
  };

  const handleClear = async () => {
    const days = keepDays.trim();
    if (days && !/^\d+$/.test(days)) {
      setError('Days must be a whole number, or blank to clear everything');
      return;
    }
    const what = days
      ? `Delete audit entries older than ${days} day(s)?`
      : 'Delete the ENTIRE audit log? Every record of what staff have done goes.';
    if (!(await confirm({
      title: 'Clear audit log?',
      message: `${what}\n\nThis cannot be undone.`,
      confirmLabel: 'Delete'
    }))) return;

    setError('');
    setNotice('');
    setClearing(true);
    try {
      const data = await api.admin.audit.clear(token, days || undefined);
      setNotice(`Removed ${data.count} entr${data.count === 1 ? 'y' : 'ies'}.`);
      setShowClear(false);
      setKeepDays('');
      loadData();
    } catch (err) {
      console.error('Clear audit error:', err);
      setError(err.message || 'Could not clear the audit log');
    }
    setClearing(false);
  };

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h4 className="font-display mb-0">Audit Log</h4>
        {isAdmin() && (
          <button
            className="btn btn-outline-danger"
            onClick={() => setShowClear(!showClear)}
          >
            <i className="bi bi-trash"></i> Clear…
          </button>
        )}
      </div>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      {showClear && (
        <div className="card mb-3">
          <div className="card-body">
            <h6 className="card-title">Clear entries</h6>
            <p className="text-body-secondary small">
              A log that only grows is a data-protection problem on a public
              server, so it can be trimmed — but the clear is itself recorded,
              with who did it and how much went.
            </p>
            <div className="row g-2 align-items-end">
              <div className="col-sm-5">
                <label className="form-label text-body-secondary" htmlFor="keep-days">
                  Keep the last … days
                </label>
                <input
                  id="keep-days"
                  type="number"
                  min="0"
                  className="form-control"
                  placeholder="blank = delete everything"
                  value={keepDays}
                  onChange={(e) => setKeepDays(e.target.value)}
                />
                <div className="form-text">
                  Entries older than this are deleted. Leave blank to empty the log.
                </div>
              </div>
              <div className="col-sm-4 d-flex gap-2">
                <button
                  className="btn btn-danger"
                  onClick={handleClear}
                  disabled={clearing}
                >
                  {clearing ? 'Clearing…' : 'Clear'}
                </button>
                <button
                  className="btn btn-outline-secondary"
                  onClick={() => setShowClear(false)}
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {loading ? <Spinner /> : (
        <div className="table-responsive">
          <table className="table table-striped align-middle">
            <thead>
              <tr>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Target</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {auditEntries.length === 0 ? (
                <tr>
                  <td colSpan="5" className="text-center">No audit entries</td>
                </tr>
              ) : (
                auditEntries.map((e) => (
                  <tr key={e.id}>
                    <td>{e.created_at ? new Date(e.created_at).toLocaleString() : 'N/A'}</td>
                    <td>{e.actor_user_id ? `#${e.actor_user_id}` : 'system'}</td>
                    <td><span className="badge text-bg-info">{e.action}</span></td>
                    <td>{e.target || '—'}</td>
                    <td className="text-body-secondary">{e.detail}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default Audit;
