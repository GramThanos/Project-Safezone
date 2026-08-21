// Admin › Servers › one server › log.
//
// Its own page rather than a card on the server page: a log wants the whole
// window, and watching one is a different job from administering the server -
// you sit on this screen while something starts up, and everything else on the
// server page is just in the way.
import React, { useState, useEffect, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';

// The backend caps a tail at 2000 lines, so offering more would be a lie.
const LINE_CHOICES = [100, 300, 500, 1000, 2000];
const DEFAULT_LINES = 300;
const POLL_MS = 5000;

function ServerLogs() {
  const { serverId } = useParams();
  const { token } = useAuth();

  const [server, setServer] = useState(null);
  const [lines, setLines] = useState([]);
  const [lineCount, setLineCount] = useState(DEFAULT_LINES);
  const [live, setLive] = useState(true);
  const [wrap, setWrap] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  // Kept apart from `error`, which the next poll clears - a clipboard refusal
  // needs to stay on screen long enough to read.
  const [copyError, setCopyError] = useState('');
  const paneRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    api.admin.servers.get(token, serverId)
      .then((data) => { if (!cancelled) setServer(data.server); })
      .catch((err) => console.error('Load server error:', err));
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverId]);

  const fetchLogs = async (count = lineCount) => {
    try {
      const data = await api.admin.servers.logs(token, serverId, count);
      setLines(data.lines || []);
      setError('');
    } catch (err) {
      console.error('Load logs error:', err);
      setLines([]);
      setError(err.message || 'Could not read the log');
    }
    setLoading(false);
  };

  // Refetch on mount and whenever the tail length changes.
  useEffect(() => {
    setLoading(true);
    fetchLogs(lineCount);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverId, lineCount]);

  // Poll only while live updates are on.
  useEffect(() => {
    if (!live) return undefined;
    const id = setInterval(() => fetchLogs(lineCount), POLL_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, lineCount, serverId]);

  // The interesting end of a log is the bottom, so every refresh lands there.
  // Without this a poll leaves you looking at lines from five seconds ago.
  useEffect(() => {
    const pane = paneRef.current;
    if (pane) pane.scrollTop = pane.scrollHeight;
  }, [lines, wrap]);

  const copyLog = async () => {
    setCopyError('');
    try {
      await navigator.clipboard.writeText(lines.join('\n'));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      // Clipboard access needs a secure context and can be refused outright.
      // Say so rather than leaving a button that silently does nothing.
      setCopyError('Your browser would not let the page write to the clipboard. '
        + 'Select the log text and copy it by hand.');
    }
  };

  return (
    <>
      <Link to={`/admin/servers/${serverId}`} className="btn btn-sm btn-outline-secondary mb-3">
        <i className="fas fa-arrow-left"></i> {server ? server.name : 'Server'}
      </Link>

      <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
        <h4 className="font-display mb-0">
          {server ? `${server.name} — log` : 'Log'}
        </h4>

        <div className="d-flex flex-wrap align-items-center gap-3">
          <div className="d-flex align-items-center gap-2">
            <label className="form-label small mb-0 text-body-secondary" htmlFor="log-lines">
              Lines
            </label>
            <select
              id="log-lines"
              className="form-select form-select-sm"
              style={{ width: 'auto' }}
              value={lineCount}
              onChange={(e) => setLineCount(parseInt(e.target.value, 10))}
            >
              {LINE_CHOICES.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>

          <div className="form-check form-switch mb-0">
            <input
              className="form-check-input"
              type="checkbox"
              id="log-live"
              checked={live}
              onChange={(e) => setLive(e.target.checked)}
            />
            <label className="form-check-label small" htmlFor="log-live">Live updates</label>
          </div>

          <div className="form-check form-switch mb-0">
            <input
              className="form-check-input"
              type="checkbox"
              id="log-wrap"
              checked={wrap}
              onChange={(e) => setWrap(e.target.checked)}
            />
            <label className="form-check-label small" htmlFor="log-wrap">Wrap lines</label>
          </div>

          <button
            className="btn btn-sm btn-outline-secondary"
            onClick={copyLog}
            disabled={lines.length === 0}
          >
            <i className="fas fa-clipboard"></i> {copied ? 'Copied' : 'Copy'}
          </button>
          <button className="btn btn-sm btn-outline-secondary" onClick={() => fetchLogs(lineCount)}>
            <i className="fas fa-rotate"></i> Refresh
          </button>
        </div>
      </div>

      {error && <div className="alert alert-warning" role="alert">{error}</div>}
      {copyError && <div className="alert alert-warning" role="alert">{copyError}</div>}

      {loading ? <Spinner /> : lines.length === 0 ? (
        !error && <p className="text-body-secondary">Nothing in the log yet.</p>
      ) : (
        <>
          <pre
            ref={paneRef}
            className="mb-2 p-3 bg-body-tertiary rounded small"
            style={{
              // Unwrapped, a long stack trace scrolls sideways instead of
              // pushing every other line off the screen.
              whiteSpace: wrap ? 'pre-wrap' : 'pre',
              wordBreak: wrap ? 'break-word' : 'normal',
              maxHeight: '70vh',
              overflow: 'auto'
            }}
          >
            <code>{lines.join('\n')}</code>
          </pre>
          <div className="text-body-secondary small">
            Last {lines.length} lines
            {live ? ` · refreshing every ${POLL_MS / 1000}s` : ' · live updates off'}
          </div>
        </>
      )}
    </>
  );
}

export default ServerLogs;
