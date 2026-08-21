// Notifications: what the site did on your behalf, and what staff did to you.
//
// Removable now, not just markable. Reading and removing are different acts,
// and a list that only ever grew buried the one message that mattered under an
// archive of ones that did not.
import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { usePlayer } from '../context/PlayerContext';
import { useToast } from '../context/ToastContext';
import api from '../services/api';
import usePageTitle from '../hooks/usePageTitle';

const ICONS = {
  reward: 'fa-gift',
  moderation: 'fa-gavel',
  system: 'fa-circle-info',
  claim: 'fa-user-check'
};

const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : '');

function Notifications() {
  usePageTitle('Notifications');
  const { token } = useAuth();
  const { refreshCounts } = usePlayer();
  const { push } = useToast();

  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState('all');   // all | unread
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // The endpoint has always paginated at 25; this page simply never asked for
  // the rest, so anything older than the first page was unreachable.
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = async () => {
    try {
      const data = await api.notifications.list(token);
      setItems(data.notifications || []);
      setHasMore(Boolean(data.pagination?.has_more));
      setError('');
    } catch (err) {
      console.error('Load notifications error:', err);
      setError('Could not load your notifications. Try again in a moment.');
    }
    setLoading(false);
  };

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const data = await api.notifications.list(token, `?offset=${items.length}`);
      setItems((current) => [...current, ...(data.notifications || [])]);
      setHasMore(Boolean(data.pagination?.has_more));
    } catch (err) {
      console.error('Load more notifications error:', err);
      setError('Could not load older notifications.');
    }
    setLoadingMore(false);
  };

  const handleRead = async (id) => {
    // Optimistic: marking read is trivially reversible and waiting for a round
    // trip to grey out a line is a worse experience than being briefly wrong.
    setItems((current) => current.map((n) => (n.id === id ? { ...n, read: true } : n)));
    try {
      await api.notifications.markRead(token, id);
      refreshCounts();
    } catch (err) {
      console.error('Mark read error:', err);
      load();
    }
  };

  const handleReadAll = async () => {
    const previouslyUnread = items.filter((n) => !n.read).map((n) => n.id);
    if (previouslyUnread.length === 0) return;
    setItems((current) => current.map((n) => ({ ...n, read: true })));
    try {
      await api.notifications.markAllRead(token);
      refreshCounts();
      // Undo rather than a confirmation up front: the action is cheap, and
      // asking first would interrupt the common case to protect the rare one.
      push(`Marked ${previouslyUnread.length} as read.`, {
        action: {
          label: 'Undo',
          onClick: async () => {
            setItems((current) => current.map(
              (n) => (previouslyUnread.includes(n.id) ? { ...n, read: false } : n)
            ));
            // There is no "mark unread" endpoint, so this is a local undo and
            // the badge is reloaded from the server to stay honest about it.
            await load();
            refreshCounts();
          }
        }
      });
    } catch (err) {
      console.error('Mark all read error:', err);
      load();
    }
  };

  const handleRemove = async (notification) => {
    setItems((current) => current.filter((n) => n.id !== notification.id));
    try {
      await api.notifications.remove(token, notification.id);
      refreshCounts();
      push('Notification removed.');
    } catch (err) {
      console.error('Remove notification error:', err);
      setError('Could not remove that one.');
      load();
    }
  };

  const handleClearRead = async () => {
    const readCount = items.filter((n) => n.read).length;
    if (readCount === 0) return;
    try {
      const data = await api.notifications.clearRead(token);
      push(`Removed ${data.count} read notification${data.count === 1 ? '' : 's'}.`);
      load();
    } catch (err) {
      console.error('Clear read error:', err);
      setError('Could not clear those.');
    }
  };

  const shown = filter === 'unread' ? items.filter((n) => !n.read) : items;
  const unreadCount = items.filter((n) => !n.read).length;
  const readCount = items.length - unreadCount;

  return (
    <section className="py-5" style={{ minHeight: '60vh' }}>
      <div className="container">
        <div className="row justify-content-center">
          <div className="col-lg-8">
            <div className="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-3">
              <h2 className="font-display mb-0">Notifications</h2>
              <div className="d-flex flex-wrap gap-2">
                <div className="btn-group btn-group-sm" role="group">
                  <button
                    className={`btn btn-outline-light${filter === 'all' ? ' active' : ''}`}
                    onClick={() => setFilter('all')}
                  >
                    All {items.length > 0 && `(${items.length})`}
                  </button>
                  <button
                    className={`btn btn-outline-light${filter === 'unread' ? ' active' : ''}`}
                    onClick={() => setFilter('unread')}
                  >
                    Unread {unreadCount > 0 && `(${unreadCount})`}
                  </button>
                </div>
                {unreadCount > 0 && (
                  <button className="btn btn-sm btn-outline-light" onClick={handleReadAll}>
                    Mark all read
                  </button>
                )}
                {readCount > 0 && (
                  <button
                    className="btn btn-sm btn-outline-light"
                    onClick={handleClearRead}
                    title="Removes the ones you have already read"
                  >
                    Clear read
                  </button>
                )}
              </div>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            {loading ? (
              <div className="d-flex flex-column gap-2" aria-hidden="true">
                {[0, 1, 2].map((n) => (
                  <div key={n} className="bg-body-tertiary rounded" style={{ height: '4.5rem' }}></div>
                ))}
              </div>
            ) : shown.length === 0 ? (
              <div className="card">
                <div className="card-body text-center text-body-secondary py-5">
                  {filter === 'unread' && items.length > 0
                    ? 'Nothing unread. Everything here has been seen.'
                    : 'Nothing here yet. This is where you will hear about character '
                      + 'links, reward deliveries and anything staff does to your account.'}
                </div>
              </div>
            ) : (
              <div className="list-group">
                {shown.map((n) => (
                  <div
                    key={n.id}
                    className={`list-group-item d-flex gap-3 align-items-start${n.read ? '' : ' border-start border-4 border-danger'}`}
                  >
                    <i className={`fas ${ICONS[n.kind] || 'fa-bell'} mt-1 text-body-secondary`}></i>
                    <div className="flex-grow-1">
                      <div className="d-flex justify-content-between align-items-start gap-2">
                        <strong className={n.read ? 'text-body-secondary' : ''}>{n.title}</strong>
                        <small className="text-body-secondary text-nowrap">{fmt(n.created_at)}</small>
                      </div>
                      {n.body && <div className="text-body-secondary">{n.body}</div>}
                      <div className="mt-2 d-flex gap-2">
                        {n.link && (
                          <Link to={n.link} className="btn btn-sm btn-outline-light">
                            Open
                          </Link>
                        )}
                        {!n.read && (
                          <button
                            className="btn btn-sm btn-outline-light"
                            onClick={() => handleRead(n.id)}
                          >
                            Mark read
                          </button>
                        )}
                      </div>
                    </div>
                    <button
                      className="btn btn-sm btn-link text-body-secondary p-0"
                      onClick={() => handleRemove(n)}
                      title="Remove this notification"
                      aria-label={`Remove notification: ${n.title}`}
                    >
                      <i className="fas fa-xmark"></i>
                    </button>
                  </div>
                ))}
              </div>
            )}

            {hasMore && !loading && (
              <div className="text-center mt-3">
                <button
                  className="btn btn-outline-light"
                  onClick={loadMore}
                  disabled={loadingMore}
                >
                  {loadingMore ? 'Loading…' : 'Show older'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

export default Notifications;
