// Admin › Staff Feed: what the site has announced to staff, newest first.
//
// This used to arrive as notifications in the player bell — one row per
// moderator, mixed in with "your reward arrived". Two unrelated things in one
// inbox, and no way to mute either without muting the other. The feed is now
// its own screen: one entry per alert, shared by everyone who can read it, with
// a per-person read marker behind the badge.
//
// It answers the question the Alerts screen cannot: *did anything actually
// fire?* A Discord channel that is quiet because nothing happened and one that
// is quiet because the webhook was deleted look identical from the outside —
// here they do not.
import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';

const PAGE_SIZE = 25;

// Severity by eye, from the event key. The catalog carries a colour for Discord
// but not a severity (yet — that is the next piece of this rework), so the two
// things worth noticing are picked out by name until it does.
const LOUD = new Set(['server.failed', 'alert.raised', 'report.created']);

const ICONS = {
  Game: 'controller',
  Accounts: 'person',
  Moderation: 'gavel',
  Loot: 'gift',
  Operations: 'exclamation-triangle'
};

// Absolute time is what an operator correlating with a game log needs; relative
// time is what they need to read the page. Both, rather than choosing.
const when = (iso) => {
  if (!iso) return { absolute: '', relative: '' };
  const at = new Date(`${iso.endsWith('Z') ? iso : `${iso}Z`}`);
  if (Number.isNaN(at.getTime())) return { absolute: iso, relative: '' };

  const seconds = Math.max(0, Math.round((Date.now() - at.getTime()) / 1000));
  let relative;
  if (seconds < 60) relative = 'just now';
  else if (seconds < 3600) relative = `${Math.floor(seconds / 60)}m ago`;
  else if (seconds < 86400) relative = `${Math.floor(seconds / 3600)}h ago`;
  else relative = `${Math.floor(seconds / 86400)}d ago`;

  return { absolute: at.toLocaleString(), relative };
};

function StaffFeed() {
  const { token } = useAuth();
  const [alerts, setAlerts] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [readAt, setReadAt] = useState(null);
  const [unread, setUnread] = useState(0);
  const [filter, setFilter] = useState('');
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async (nextOffset, event) => {
    setError('');
    try {
      const data = await api.admin.staffFeed.getAll(token, {
        limit: PAGE_SIZE, offset: nextOffset, event: event || undefined
      });
      setAlerts(data.alerts || []);
      setCatalog(data.events || []);
      setUnread(data.unread || 0);
      setReadAt(data.read_at || null);
      setTotal(data.pagination?.total ?? 0);
    } catch (err) {
      console.error('Load staff feed error:', err);
      setError('Failed to load the staff feed');
    }
    setLoading(false);
  }, [token]);

  useEffect(() => {
    load(offset, filter);
  }, [load, offset, filter]);

  // Marking read is explicit rather than on-open: an operator who glances at
  // the page while something is on fire should not lose the highlight showing
  // which entries are new.
  const handleMarkRead = async () => {
    setError('');
    try {
      const data = await api.admin.staffFeed.markRead(token);
      setReadAt(data.read_at || null);
      setUnread(0);
    } catch (err) {
      console.error('Mark staff feed read error:', err);
      setError(err.message || 'Could not mark the feed read');
    }
  };

  const changeFilter = (event) => {
    setOffset(0);
    setFilter(event);
  };

  if (loading) return <Spinner />;

  const byKey = {};
  catalog.forEach((event) => { byKey[event.key] = event; });

  // Compared as instants, not strings: both sides are naive-UTC ISO from the
  // API, but `isoformat()` drops the microseconds when they happen to be zero,
  // and a lexicographic compare across the two shapes is a trap waiting for a
  // whole-second timestamp.
  const asTime = (iso) => (iso ? Date.parse(iso.endsWith('Z') ? iso : `${iso}Z`) : NaN);
  const readMark = asTime(readAt);
  const isNew = (alert) => Number.isNaN(readMark) || asTime(alert.created_at) > readMark;
  const pages = Math.ceil(total / PAGE_SIZE) || 1;
  const page = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <>
      <div className="d-flex flex-wrap justify-content-between align-items-baseline gap-2">
        <h4 className="font-display mb-1">
          Staff Feed
          {unread > 0 && (
            <span className="badge text-bg-danger ms-2">{unread} new</span>
          )}
        </h4>
        {unread > 0 && (
          <button className="btn btn-sm btn-outline-secondary" onClick={handleMarkRead}>
            <i className="bi bi-check2-all me-1"></i> Mark all read
          </button>
        )}
      </div>
      <p className="text-body-secondary">
        Everything the site has announced to staff. This is the same set of
        events that reaches your Discord channels and ops mail — if something is
        here but did not arrive there, the destination is the problem, not the
        event. Configure what fires and where it goes under{' '}
        <Link to="/admin/alerts">Alerts</Link>.
      </p>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}

      {catalog.length > 0 && (
        <div className="mb-3 d-flex flex-wrap gap-1">
          <button
            className={`btn btn-sm ${filter ? 'btn-outline-secondary' : 'btn-secondary'}`}
            onClick={() => changeFilter('')}
          >
            Everything
          </button>
          {catalog.map((event) => (
            <button
              key={event.key}
              className={`btn btn-sm ${filter === event.key ? 'btn-secondary' : 'btn-outline-secondary'}`}
              onClick={() => changeFilter(event.key)}
              title={event.help || event.label}
            >
              {event.label}
            </button>
          ))}
        </div>
      )}

      {alerts.length === 0 ? (
        <div className="card">
          <div className="card-body text-body-secondary">
            {filter
              ? 'Nothing has fired for that event yet.'
              : 'Nothing has fired yet. That is either a quiet deployment or a '
                + 'staff feed with no events ticked — check the Alerts screen if '
                + 'you were expecting something.'}
          </div>
        </div>
      ) : (
        <div className="card">
          <ul className="list-group list-group-flush">
            {alerts.map((alert) => {
              const spec = byKey[alert.event];
              const time = when(alert.created_at);
              const fresh = isNew(alert);
              return (
                <li
                  className={`list-group-item${fresh ? ' border-start border-3 border-danger' : ''}`}
                  key={alert.id}
                >
                  <div className="d-flex flex-wrap align-items-baseline gap-2">
                    <i className={`bi bi-${ICONS[spec?.group] || 'dot'} text-body-secondary`}></i>
                    <span className={`fw-semibold${LOUD.has(alert.event) ? ' text-danger-emphasis' : ''}`}>
                      {alert.title}
                    </span>
                    {fresh && <span className="badge text-bg-danger">new</span>}
                    <span className="text-body-secondary small ms-auto" title={time.absolute}>
                      {time.relative}
                    </span>
                  </div>
                  {alert.body && (
                    <div className="small text-body-secondary mt-1" style={{ whiteSpace: 'pre-wrap' }}>
                      {alert.body}
                    </div>
                  )}
                  <div className="small mt-1 d-flex flex-wrap gap-2 align-items-center">
                    <span className="badge text-bg-light text-dark">
                      {spec?.label || alert.event}
                    </span>
                    {/* Every link the catalog produces is an in-app path;
                        anything else is not ours to route, so it is skipped
                        rather than handed to the router. */}
                    {alert.link && alert.link.startsWith('/') && (
                      <Link to={alert.link}>Open</Link>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="d-flex justify-content-between align-items-center mt-3">
          <button
            className="btn btn-sm btn-outline-secondary"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Newer
          </button>
          <span className="text-body-secondary small">Page {page} of {pages}</span>
          <button
            className="btn btn-sm btn-outline-secondary"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Older
          </button>
        </div>
      )}
    </>
  );
}

export default StaffFeed;
