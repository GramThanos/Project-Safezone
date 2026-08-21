// Reports and appeals — the one place a player can start a conversation with
// staff. Reachable while banned, where it becomes an appeal form only.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import usePageTitle from '../hooks/usePageTitle';

const STATUS_BADGE = {
  open: 'warning',
  resolved: 'success',
  dismissed: 'secondary'
};

function Reports() {
  const { token, user } = useAuth();
  const banned = user?.role === 'banned';
  usePageTitle(banned ? 'Appeal' : 'Reports');

  const [reports, setReports] = useState([]);
  const [form, setForm] = useState({ subject_username: '', body: '' });
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
      const data = await api.reports.listMine(token);
      setReports(data.reports || []);
    } catch (err) {
      console.error('Load reports error:', err);
      setError('Could not load your reports');
    }
    setLoading(false);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setNotice('');
    if (!form.body.trim()) {
      setError('Tell us what happened');
      return;
    }
    try {
      const data = await api.reports.create(token, {
        kind: banned ? 'appeal' : 'report',
        subject_username: banned ? null : form.subject_username.trim(),
        body: form.body.trim()
      });
      setNotice(data.message
        || 'Sent to staff. You will get a notification here when someone replies.');
      setForm({ subject_username: '', body: '' });
      loadData();
    } catch (err) {
      console.error('Submit report error:', err);
      setError(err.message || 'Could not submit that');
    }
  };

  const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : '');

  return (
    <section className="py-5" style={{ minHeight: '60vh' }}>
      <div className="container">
        <div className="row justify-content-center">
          <div className="col-lg-8">
            <h2 className="font-display mb-3">
              {banned ? 'Appeal' : 'Reports'}
            </h2>

            {banned && (
              <div className="alert alert-warning">
                Your account is banned. You can read your notifications — which
                say why — and appeal here. Nothing else is available.
              </div>
            )}

            {error && <div className="alert alert-danger">{error}</div>}
            {notice && <div className="alert alert-success">{notice}</div>}

            <div className="card mb-4">
              <div className="card-body">
                <h5 className="card-title font-display mb-3">
                  {banned ? 'Appeal your ban' : 'Report a player'}
                </h5>

                {/* Appealing something you cannot see makes for appeals that
                    answer the wrong accusation. */}
                {banned && user?.ban && (
                  <div className="alert alert-secondary">
                    <div className="fw-bold mb-1">What you are appealing</div>
                    <div>{user.ban.reason || 'No reason was recorded.'}</div>
                    <div className="small text-body-secondary mt-1">
                      {user.ban.permanent
                        ? 'This ban does not expire on its own.'
                        : `Ends ${new Date(user.ban.expires_at).toLocaleString()}.`}
                    </div>
                  </div>
                )}
                <form onSubmit={handleSubmit}>
                  {!banned && (
                    <div className="mb-3">
                      <label className="form-label text-body-secondary">
                        Who (in-game name, if you know it)
                      </label>
                      <input
                        type="text"
                        className="form-control"
                        value={form.subject_username}
                        onChange={(e) => setForm({ ...form, subject_username: e.target.value })}
                        placeholder="optional"
                      />
                    </div>
                  )}
                  <div className="mb-3">
                    <label className="form-label text-body-secondary">
                      {banned ? 'Why should this ban be lifted?' : 'What happened?'}
                    </label>
                    <textarea
                      className="form-control"
                      rows="5"
                      maxLength="4000"
                      value={form.body}
                      onChange={(e) => setForm({ ...form, body: e.target.value })}
                      required
                    />
                    <div className="form-text">
                      Be specific — when, where, and what you saw. A moderator
                      reads this and replies.
                    </div>
                  </div>

                  <button type="submit" className="btn btn-danger">
                    {banned ? 'Submit appeal' : 'Submit report'}
                  </button>
                  <div className="form-text mt-2">
                    This goes to the staff team. Replies arrive as a notification
                    on this site, and show up under your submissions below.
                  </div>
                </form>
              </div>
            </div>

            <h5 className="font-display mb-3">Your submissions</h5>
            {loading ? (
              <p className="text-body-secondary">Loading…</p>
            ) : reports.length === 0 ? (
              <p className="text-body-secondary">Nothing submitted yet.</p>
            ) : (
              <div className="list-group">
                {reports.map((r) => (
                  <div key={r.id} className="list-group-item">
                    <div className="d-flex justify-content-between align-items-start gap-2">
                      <strong className="text-capitalize">{r.kind}</strong>
                      <span className={`badge text-bg-${STATUS_BADGE[r.status] || 'secondary'}`}>
                        {r.status}
                      </span>
                    </div>
                    {r.subject_username && (
                      <div className="text-body-secondary small">
                        About {r.subject_username}
                      </div>
                    )}
                    <p className="mb-1 mt-2">{r.body}</p>
                    <div className="text-body-secondary small">{fmt(r.created_at)}</div>
                    {r.resolution && (
                      <div className="mt-2 p-2 bg-body-tertiary rounded">
                        <div className="small text-body-secondary">Staff answer</div>
                        <div>{r.resolution}</div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

export default Reports;
