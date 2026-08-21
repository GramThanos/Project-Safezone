// Admin › Jobs: the recurring work the scheduler does.
//
// New job kinds arrive disabled on purpose — a job that starts running the
// moment it is deployed is a surprise. Turning one on is a deliberate act.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';

// Offered intervals, rather than a free-text seconds box nobody wants to compute.
const INTERVALS = [
  { label: 'Every 5 minutes', value: 300 },
  { label: 'Hourly', value: 3600 },
  { label: 'Every 6 hours', value: 21600 },
  { label: 'Daily', value: 86400 },
  { label: 'Weekly', value: 604800 }
];

function Jobs() {
  const { token } = useAuth();
  const [jobs, setJobs] = useState([]);
  const [kinds, setKinds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setError('');
    try {
      const data = await api.admin.jobs.getAll(token);
      setJobs(data.jobs || []);
      setKinds(data.kinds || []);
    } catch (err) {
      console.error('Load jobs error:', err);
      setError('Failed to load jobs');
    }
    setLoading(false);
  };

  const update = async (job, patch) => {
    setError('');
    setNotice('');
    try {
      await api.admin.jobs.update(token, job.id, patch);
      loadData();
    } catch (err) {
      console.error('Update job error:', err);
      setError(err.message || 'Could not update that job');
    }
  };

  const runNow = async (job) => {
    setError('');
    setNotice('');
    try {
      const data = await api.admin.jobs.run(token, job.id);
      setNotice(data.message || 'Queued.');
    } catch (err) {
      console.error('Run job error:', err);
      setError(err.message || 'Could not queue that job');
    }
  };

  const describe = (kind) => kinds.find((k) => k.kind === kind)?.description || '';
  const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : '—');

  if (loading) return <Spinner />;

  return (
    <>
      <h4 className="font-display mb-1">Scheduled Jobs</h4>
      <p className="text-body-secondary">
        Recurring work runs in its own process. A job you have just enabled runs
        within a tick; "Run now" simply moves its next run forward.
      </p>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      {jobs.length === 0 ? (
        <div className="card">
          <div className="card-body text-body-secondary">
            No jobs registered yet. The scheduler adds them on its first run — if
            this stays empty, that process is not running.
          </div>
        </div>
      ) : (
        jobs.map((job) => (
          <div className="card mb-3" key={job.id}>
            <div className="card-body">
              <div className="d-flex justify-content-between align-items-start gap-3 flex-wrap">
                <div>
                  <h5 className="font-display mb-1">
                    {job.kind}
                    {job.running && (
                      <span className="badge text-bg-info ms-2">running</span>
                    )}
                  </h5>
                  <p className="text-body-secondary mb-0">{describe(job.kind)}</p>
                </div>
                <div className="form-check form-switch">
                  <input
                    className="form-check-input"
                    type="checkbox"
                    id={`job-${job.id}`}
                    checked={job.enabled}
                    onChange={(e) => update(job, { enabled: e.target.checked })}
                  />
                  <label className="form-check-label" htmlFor={`job-${job.id}`}>
                    {job.enabled ? 'Enabled' : 'Disabled'}
                  </label>
                </div>
              </div>

              <div className="row g-3 mt-2 align-items-end">
                <div className="col-md-4">
                  <label className="form-label text-body-secondary">Runs</label>
                  <select
                    className="form-select"
                    value={job.interval_seconds}
                    onChange={(e) => update(job, { interval_seconds: parseInt(e.target.value, 10) })}
                  >
                    {INTERVALS.map((i) => (
                      <option key={i.value} value={i.value}>{i.label}</option>
                    ))}
                    {!INTERVALS.some((i) => i.value === job.interval_seconds) && (
                      <option value={job.interval_seconds}>
                        Every {job.interval_seconds}s
                      </option>
                    )}
                  </select>
                </div>
                <div className="col-md-4">
                  <div className="text-body-secondary small">Last run</div>
                  <div>{fmt(job.last_run_at)}</div>
                </div>
                <div className="col-md-2">
                  <div className="text-body-secondary small">Next</div>
                  <div>{job.enabled ? fmt(job.next_run_at) : '—'}</div>
                </div>
                <div className="col-md-2">
                  <button
                    className="btn btn-outline-secondary w-100"
                    onClick={() => runNow(job)}
                    disabled={!job.enabled}
                  >
                    Run now
                  </button>
                </div>
              </div>

              {job.last_result && (
                <div className="mt-3">
                  <div className="text-body-secondary small">Last result</div>
                  <code className="d-block text-break">{job.last_result}</code>
                </div>
              )}
            </div>
          </div>
        ))
      )}
    </>
  );
}

export default Jobs;
