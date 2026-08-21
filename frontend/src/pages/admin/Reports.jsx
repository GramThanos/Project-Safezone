// Admin › Reports: the queue of player reports and ban appeals.
//
// Open items first, oldest first — somebody has been waiting. Answering one
// requires saying what you decided, because a resolution nobody explains is
// indistinguishable from being ignored.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { getStatusBadge, Spinner } from './helpers';

function Reports() {
  const { token } = useAuth();
  const [reports, setReports] = useState([]);
  const [openCount, setOpenCount] = useState(0);
  const [filter, setFilter] = useState('open');
  const [answering, setAnswering] = useState(null);
  const [answer, setAnswer] = useState({ status: 'resolved', resolution: '' });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const loadData = async () => {
    setError('');
    try {
      const params = filter ? `?status=${filter}` : '';
      const data = await api.admin.reports.getAll(token, params);
      setReports(data.reports || []);
      setOpenCount(data.open || 0);
    } catch (err) {
      console.error('Load reports error:', err);
      setError('Failed to load the queue');
    }
    setLoading(false);
  };

  const submitAnswer = async (e) => {
    e.preventDefault();
    if (!answer.resolution.trim()) return;
    setError('');
    setNotice('');
    try {
      await api.admin.reports.resolve(token, answering.id, answer.status, answer.resolution.trim());
      setNotice('Answered. The reporter has been notified.');
      setAnswering(null);
      setAnswer({ status: 'resolved', resolution: '' });
      loadData();
    } catch (err) {
      console.error('Resolve report error:', err);
      setError(err.message || 'Could not answer that');
    }
  };

  const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : '');

  return (
    <>
      <h4 className="font-display mb-1">
        Reports &amp; Appeals
        {openCount > 0 && (
          <span className="badge text-bg-danger ms-2">{openCount} open</span>
        )}
      </h4>
      <p className="text-body-secondary">
        Answering requires an explanation, which the person who filed it sees.
      </p>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      <div className="btn-group btn-group-sm mb-3" role="group">
        {[['open', 'Open'], ['resolved', 'Resolved'], ['dismissed', 'Dismissed'], ['', 'All']].map(
          ([value, label]) => (
            <button
              key={label}
              className={`btn btn-${filter === value ? 'danger' : 'outline-secondary'}`}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          )
        )}
      </div>

      {loading ? <Spinner /> : reports.length === 0 ? (
        <div className="card">
          <div className="card-body text-body-secondary">
            Nothing here.
          </div>
        </div>
      ) : (
        reports.map((r) => (
          <div className="card mb-3" key={r.id}>
            <div className="card-body">
              <div className="d-flex justify-content-between align-items-start gap-2">
                <div>
                  <span className="badge text-bg-secondary text-capitalize me-2">{r.kind}</span>
                  <span className={`badge text-bg-${getStatusBadge(r.status)}`}>{r.status}</span>
                  <div className="text-body-secondary small mt-1">
                    From account #{r.reporter_user_id}
                    {r.subject_username ? ` · about ${r.subject_username}` : ''}
                    {` · ${fmt(r.created_at)}`}
                  </div>
                </div>
                {r.status === 'open' && (
                  <button
                    className="btn btn-sm btn-danger"
                    onClick={() => { setAnswering(r); setAnswer({ status: 'resolved', resolution: '' }); }}
                  >
                    Answer
                  </button>
                )}
              </div>

              <p className="mt-3 mb-0" style={{ whiteSpace: 'pre-wrap' }}>{r.body}</p>

              {r.resolution && (
                <div className="mt-3 p-2 bg-body-tertiary rounded">
                  <div className="small text-body-secondary">
                    Answered by #{r.reviewed_by} · {fmt(r.reviewed_at)}
                  </div>
                  <div>{r.resolution}</div>
                </div>
              )}
            </div>
          </div>
        ))
      )}

      {answering && (
        <div
          className="modal show d-block"
          style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
          onClick={() => setAnswering(null)}
        >
          <div className="modal-dialog modal-dialog-centered" onClick={(e) => e.stopPropagation()}>
            <form className="modal-content" onSubmit={submitAnswer}>
              <div className="modal-header">
                <h5 className="modal-title font-display text-capitalize">
                  Answer this {answering.kind}
                </h5>
                <button type="button" className="btn-close" onClick={() => setAnswering(null)}></button>
              </div>
              <div className="modal-body">
                <p className="text-body-secondary" style={{ whiteSpace: 'pre-wrap' }}>
                  {answering.body}
                </p>

                <div className="mb-3">
                  <label className="form-label text-body-secondary">Outcome</label>
                  <select
                    className="form-select"
                    value={answer.status}
                    onChange={(e) => setAnswer({ ...answer, status: e.target.value })}
                  >
                    <option value="resolved">Resolved — acted on it</option>
                    <option value="dismissed">Dismissed — nothing to do</option>
                  </select>
                </div>

                <div className="mb-3">
                  <label className="form-label text-body-secondary">
                    What you decided (they will see this)
                  </label>
                  <textarea
                    className="form-control"
                    rows="4"
                    value={answer.resolution}
                    onChange={(e) => setAnswer({ ...answer, resolution: e.target.value })}
                    required
                  />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-outline-secondary" onClick={() => setAnswering(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-danger" disabled={!answer.resolution.trim()}>
                  Send answer
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

export default Reports;
