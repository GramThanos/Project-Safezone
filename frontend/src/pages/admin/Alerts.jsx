// Admin › Alerts: what the site announces to staff, and where it goes.
//
// One list of events, three kinds of destination. A channel is a Discord
// webhook, the staff inbox, or an ops mailbox, and each one ticks the events it
// wants — so player traffic can go to a busy Discord channel while the two
// things worth waking up for go to mail.
//
// What this page has to say out loud, or an operator is left guessing:
//   - A webhook URL is a secret and is never shown again. It comes back masked,
//     and an edit that leaves the field blank keeps the stored one.
//   - Game events (joins, server state) travel through the scheduler. If that
//     process is not running, this page is the only place that difference is
//     visible — everywhere else it looks exactly like a quiet evening.
//   - Some events fire on every player action. Fine for Discord, a poor idea
//     for a mailbox, so the checkbox says so before it is ticked.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';

// What each kind is, in the operator's terms rather than the schema's.
const KINDS = {
  webhook: {
    label: 'Discord webhook',
    icon: 'discord',
    badge: 'primary',
    targetLabel: 'Discord webhook URL',
    placeholder: 'https://discord.com/api/webhooks/…',
    secret: true,
    help: 'Discord → Edit Channel → Integrations → Webhooks → Copy Webhook URL. '
      + 'Anyone holding this URL can post in that channel, so it is stored like '
      + 'a password and never shown again.'
  },
  inapp: {
    label: 'Staff inbox',
    icon: 'bell',
    badge: 'secondary',
    targetLabel: null,
    help: 'Notifications in the panel, for every moderator and admin. There is '
      + 'one of these and it needs no address.'
  },
  email: {
    label: 'Ops mail',
    icon: 'envelope',
    badge: 'success',
    targetLabel: 'Addresses',
    placeholder: 'ops@example.com, oncall@example.com',
    secret: false,
    help: 'Comma separated. Addresses are typed here rather than taken from the '
      + 'staff list, so an alert does not depend on who holds a role this week.'
  }
};

const BLANK = { kind: 'webhook', name: '', target: '', events: [], server_ids: [], enabled: true };

// The scheduler ticks every 30 seconds; a couple of missed ticks is a slow
// moment, five minutes of silence is a process that is not there.
const PUMP_STALE_SECONDS = 300;

// Preserve the catalog's order (the API sorts it) while grouping.
const byGroup = (events) => {
  const groups = [];
  events.forEach((event) => {
    let group = groups.find((g) => g.label === event.group);
    if (!group) {
      group = { label: event.group, events: [] };
      groups.push(group);
    }
    group.events.push(event);
  });
  return groups;
};

const toggle = (list, value) => (
  list.includes(value) ? list.filter((item) => item !== value) : [...list, value]
);

function ChannelForm({ initial, catalog, servers, isNew, saving, onSubmit, onCancel }) {
  const [form, setForm] = useState(initial);
  const kind = KINDS[form.kind] || KINDS.webhook;
  const groups = byGroup(catalog);
  const uid = initial.id || 'new';

  // The server filter only means anything for events that happen on a server.
  const scoped = catalog.filter((event) => event.scoped).map((event) => event.key);
  const filterUseful = form.events.some((key) => scoped.includes(key));
  // A busy event is fine in a chat channel and miserable in a mailbox.
  const noisy = form.kind !== 'webhook';

  const submit = (e) => {
    e.preventDefault();
    onSubmit(form);
  };

  return (
    <form onSubmit={submit}>
      <div className="row g-3">
        {isNew && (
          <div className="col-md-3">
            <label className="form-label" htmlFor={`kind-${uid}`}>Kind</label>
            <select
              className="form-select"
              id={`kind-${uid}`}
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value, target: '' })}
            >
              {Object.keys(KINDS).map((key) => (
                <option value={key} key={key}>{KINDS[key].label}</option>
              ))}
            </select>
            <div className="form-text">Cannot be changed later.</div>
          </div>
        )}
        <div className={isNew ? 'col-md-3' : 'col-md-4'}>
          <label className="form-label" htmlFor={`name-${uid}`}>Name</label>
          <input
            type="text"
            className="form-control"
            id={`name-${uid}`}
            placeholder="#server-log"
            maxLength={64}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <div className="form-text">How you tell channels apart. Only you see it.</div>
        </div>
        {kind.targetLabel && (
          <div className="col-md-6">
            <label className="form-label" htmlFor={`target-${uid}`}>{kind.targetLabel}</label>
            <input
              type={kind.secret ? 'password' : 'text'}
              className="form-control"
              id={`target-${uid}`}
              autoComplete="off"
              placeholder={isNew || !kind.secret ? kind.placeholder : 'leave blank to keep the current URL'}
              value={form.target}
              onChange={(e) => setForm({ ...form, target: e.target.value })}
            />
            <div className="form-text">{kind.help}</div>
          </div>
        )}
        {!kind.targetLabel && (
          <div className="col-md-6 d-flex align-items-end">
            <div className="form-text">{kind.help}</div>
          </div>
        )}
      </div>

      <fieldset className="mt-4">
        <legend className="fs-6 text-body-secondary">Send a message when…</legend>
        <div className="row g-3">
          {groups.map((group) => (
            <div className="col-md-6 col-xl-4" key={group.label}>
              <div className="card h-100">
                <div className="card-body">
                  <h6 className="card-title font-display">{group.label}</h6>
                  {group.events.map((event) => (
                    <div className="form-check mb-2" key={event.key}>
                      <input
                        className="form-check-input"
                        type="checkbox"
                        id={`${uid}-${event.key}`}
                        checked={form.events.includes(event.key)}
                        onChange={() => setForm({ ...form, events: toggle(form.events, event.key) })}
                      />
                      <label className="form-check-label" htmlFor={`${uid}-${event.key}`}>
                        {event.label}
                        {event.volume === 'high' && (
                          <span className="badge text-bg-warning ms-2">busy</span>
                        )}
                      </label>
                      {event.help && <div className="form-text mt-0">{event.help}</div>}
                      {event.volume === 'high' && noisy && (
                        <div className="form-text mt-0 text-warning-emphasis">
                          Fires on every player action — a lot of mail, or a lot of
                          unread notifications.
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </fieldset>

      {servers.length > 0 && (
        <fieldset className="mt-4">
          <legend className="fs-6 text-body-secondary">Which servers</legend>
          <p className="form-text mt-0">
            {filterUseful
              ? 'Leave everything unticked to hear about all of them. Account and moderation events are never filtered — they do not belong to a server.'
              : 'Only used by the server-side events above; nothing selected here is currently subscribed to one.'}
          </p>
          <div className="d-flex flex-wrap gap-3">
            {servers.map((server) => (
              <div className="form-check" key={server.id}>
                <input
                  className="form-check-input"
                  type="checkbox"
                  id={`${uid}-server-${server.id}`}
                  checked={(form.server_ids || []).includes(server.id)}
                  onChange={() => setForm({ ...form, server_ids: toggle(form.server_ids || [], server.id) })}
                />
                <label className="form-check-label" htmlFor={`${uid}-server-${server.id}`}>
                  {server.name}
                </label>
              </div>
            ))}
          </div>
        </fieldset>
      )}

      <div className="mt-4 d-flex gap-2">
        <button type="submit" className="btn btn-danger" disabled={saving}>
          {saving ? 'Saving…' : (isNew ? 'Add channel' : 'Save changes')}
        </button>
        {onCancel && (
          <button type="button" className="btn btn-outline-secondary" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

function Alerts() {
  const { token } = useAuth();
  const [channels, setChannels] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [servers, setServers] = useState([]);
  const [pump, setPump] = useState({});
  const [mailConfigured, setMailConfigured] = useState(true);
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState(null);
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
      const data = await api.admin.alerts.getAll(token);
      setChannels(data.channels || []);
      setCatalog(data.events || []);
      setPump(data.pump || {});
      setMailConfigured(data.mail_configured !== false);
    } catch (err) {
      console.error('Load alerts error:', err);
      setError('Failed to load alert channels');
    }
    try {
      // Only for the per-server filter, so a failure here is not fatal: the
      // filter simply does not offer itself.
      const data = await api.admin.servers.getAll(token);
      setServers(data.servers || []);
    } catch (err) {
      console.error('Load servers error:', err);
    }
    setLoading(false);
  };

  const handleCreate = async (form) => {
    setError('');
    setNotice('');
    setSaving(true);
    try {
      await api.admin.alerts.create(token, form);
      setAdding(false);
      setNotice('Channel added. Send it a test message to make sure it lands.');
      loadData();
    } catch (err) {
      console.error('Create channel error:', err);
      setError(err.message || 'Could not add that channel');
    }
    setSaving(false);
  };

  const handleUpdate = async (id, form) => {
    setError('');
    setNotice('');
    setSaving(true);
    try {
      // An untouched webhook URL means "keep the stored one" — sending the
      // empty string would otherwise read as "clear it".
      const payload = { ...form };
      if (!payload.target) delete payload.target;
      await api.admin.alerts.update(token, id, payload);
      setEditingId(null);
      setNotice('Channel updated.');
      loadData();
    } catch (err) {
      console.error('Update channel error:', err);
      setError(err.message || 'Could not save that channel');
    }
    setSaving(false);
  };

  const handleToggle = async (channel) => {
    setError('');
    setNotice('');
    setBusyId(channel.id);
    try {
      await api.admin.alerts.update(token, channel.id, { enabled: !channel.enabled });
      loadData();
    } catch (err) {
      console.error('Toggle channel error:', err);
      setError(err.message || 'Could not change that channel');
    }
    setBusyId(null);
  };

  const handleTest = async (channel) => {
    setError('');
    setNotice('');
    setBusyId(channel.id);
    try {
      await api.admin.alerts.test(token, channel.id);
      setNotice(`A test message was delivered to ${channel.name}.`);
    } catch (err) {
      console.error('Test channel error:', err);
      setError(`${channel.name}: ${err.message || 'the test message was not delivered'}`);
    }
    setBusyId(null);
    loadData();
  };

  const handleDelete = async (channel) => {
    if (!window.confirm(`Remove ${channel.name}? Nothing changes at the destination — this only stops the messages.`)) return;
    setError('');
    setNotice('');
    setBusyId(channel.id);
    try {
      await api.admin.alerts.remove(token, channel.id);
      setNotice(`${channel.name} removed.`);
      loadData();
    } catch (err) {
      console.error('Delete channel error:', err);
      setError(err.message || 'Could not remove that channel');
    }
    setBusyId(null);
  };

  const labelFor = (key) => {
    const event = catalog.find((item) => item.key === key);
    return event ? event.label : key;
  };

  const serverNames = (ids) => (
    (ids || [])
      .map((id) => {
        const server = servers.find((s) => s.id === id);
        return server ? server.name : `#${id}`;
      })
      .join(', ')
  );

  const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : 'never');

  // Whether the scheduler is draining the queue. Only worth saying when
  // somebody is actually subscribed to something that depends on it.
  const gameKeys = catalog.filter((event) => event.source === 'game').map((event) => event.key);
  const wantsGameEvents = channels.some(
    (channel) => channel.enabled && (channel.events || []).some((key) => gameKeys.includes(key))
  );
  const pumpStale = pump.age_seconds === null || pump.age_seconds === undefined
    || pump.age_seconds > PUMP_STALE_SECONDS;
  const wantsMail = channels.some((channel) => channel.enabled && channel.kind === 'email');

  if (loading) return <Spinner />;

  return (
    <>
      <h4 className="font-display mb-1">Alerts</h4>
      <p className="text-body-secondary">
        What the site tells staff, and where. Every channel picks its own events,
        so the busy ones and the ones worth waking up for do not have to share a
        destination.
      </p>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      {wantsGameEvents && pumpStale && (
        <div className="alert alert-warning" role="alert">
          <strong>Nothing is delivering game events.</strong> Joins, leaves and
          server state reach their channels through the <code>scheduler</code> container,
          and it has not checked the queue
          {pump.age_seconds ? ` for ${Math.round(pump.age_seconds / 60)} minutes` : ''}.
          Everything else is sent as it happens and is unaffected.
          {pump.queued ? ` ${pump.queued} event(s) are waiting.` : ''}
        </div>
      )}

      {wantsMail && !mailConfigured && (
        <div className="alert alert-warning" role="alert">
          <strong>No mail server is configured.</strong> An ops mail channel
          cannot send anything until <code>SMTP_HOST</code> is set on the
          game-server container — that is the only one with outbound access.
        </div>
      )}

      <div className="d-flex justify-content-between align-items-center mb-3">
        <h5 className="font-display mb-0">
          {channels.length} channel{channels.length === 1 ? '' : 's'}
        </h5>
        {!adding && (
          <button className="btn btn-danger" onClick={() => { setAdding(true); setEditingId(null); }}>
            <i className="bi bi-plus-lg me-1"></i>Add channel
          </button>
        )}
      </div>

      {adding && (
        <div className="card mb-4">
          <div className="card-body">
            <h5 className="card-title font-display mb-3">New channel</h5>
            <ChannelForm
              initial={BLANK}
              catalog={catalog}
              servers={servers}
              isNew
              saving={saving}
              onSubmit={handleCreate}
              onCancel={() => setAdding(false)}
            />
          </div>
        </div>
      )}

      {channels.length === 0 && !adding && (
        <p className="text-body-secondary">
          No channels yet. Add one to start sending alerts somewhere.
        </p>
      )}

      {channels.map((channel) => {
        const kind = KINDS[channel.kind] || KINDS.webhook;
        return (
          <div className="card mb-3" key={channel.id}>
            <div className="card-body">
              <div className="d-flex flex-wrap justify-content-between align-items-start gap-2">
                <div>
                  <h5 className="card-title font-display mb-1">
                    <i className={`bi bi-${kind.icon} me-2`}></i>
                    {channel.name}
                    <span className={`badge ms-2 text-bg-${kind.badge}`}>{kind.label}</span>
                    <span className={`badge ms-1 text-bg-${channel.enabled ? 'success' : 'secondary'}`}>
                      {channel.enabled ? 'on' : 'off'}
                    </span>
                  </h5>
                  {channel.target
                    ? <code className="small text-break">{channel.target}</code>
                    : <span className="small text-body-secondary">Every moderator and admin</span>}
                </div>
                <div className="btn-group">
                  <button
                    className="btn btn-sm btn-outline-secondary"
                    onClick={() => handleTest(channel)}
                    disabled={busyId === channel.id}
                  >
                    Test
                  </button>
                  <button
                    className="btn btn-sm btn-outline-secondary"
                    onClick={() => { setEditingId(editingId === channel.id ? null : channel.id); setAdding(false); }}
                  >
                    {editingId === channel.id ? 'Close' : 'Edit'}
                  </button>
                  <button
                    className="btn btn-sm btn-outline-secondary"
                    onClick={() => handleToggle(channel)}
                    disabled={busyId === channel.id}
                  >
                    {channel.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    className="btn btn-sm btn-outline-danger"
                    onClick={() => handleDelete(channel)}
                    disabled={busyId === channel.id}
                  >
                    Delete
                  </button>
                </div>
              </div>

              <div className="mt-3">
                {(channel.events || []).length === 0 ? (
                  <span className="text-body-secondary">
                    Subscribed to nothing, so it will never say anything.
                  </span>
                ) : (
                  (channel.events || []).map((key) => (
                    <span className="badge text-bg-light border me-1 mb-1" key={key}>
                      {labelFor(key)}
                    </span>
                  ))
                )}
              </div>

              <div className="mt-2 small text-body-secondary">
                {(channel.server_ids || []).length > 0
                  ? `Server events limited to: ${serverNames(channel.server_ids)}. `
                  : 'All servers. '}
                Last sent: {fmt(channel.last_sent_at)}
                {channel.last_status && (
                  <span className={`badge ms-2 text-bg-${channel.last_status === 'ok' ? 'success' : 'danger'}`}>
                    {channel.last_status}
                  </span>
                )}
              </div>

              {channel.last_status === 'failed' && channel.last_error && (
                <div className="alert alert-warning mt-3 mb-0 py-2 small" role="alert">
                  {channel.last_error}
                </div>
              )}

              {editingId === channel.id && (
                <div className="mt-4 pt-3 border-top">
                  <ChannelForm
                    initial={{
                      id: channel.id,
                      kind: channel.kind,
                      name: channel.name,
                      target: channel.kind === 'webhook' ? '' : (channel.target || ''),
                      events: channel.events || [],
                      server_ids: channel.server_ids || [],
                      enabled: channel.enabled
                    }}
                    catalog={catalog}
                    servers={servers}
                    isNew={false}
                    saving={saving}
                    onSubmit={(form) => handleUpdate(channel.id, form)}
                    onCancel={() => setEditingId(null)}
                  />
                </div>
              )}
            </div>
          </div>
        );
      })}

      <div className="card mt-4">
        <div className="card-body">
          <h6 className="card-title font-display">What is sent, and what is not</h6>
          <p className="text-body-secondary mb-2 small">
            Messages carry in-game character names, account usernames and server
            names. They never carry email addresses, passwords or IP addresses.
            The text of a report reaches the staff inbox and ops mail — never a
            Discord channel, which usually has a wider membership than the staff
            list does.
          </p>
          <p className="text-body-secondary mb-0 small">
            Messages to <em>players</em> about their own account — a reward
            arriving, a ban ending — are not configured here. They always go to
            the person concerned, and account mail such as verification and
            password resets is part of how those flows work rather than
            something to switch on and off.
          </p>
        </div>
      </div>
    </>
  );
}

export default Alerts;
