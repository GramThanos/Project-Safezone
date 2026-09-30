// Admin › Events: what causes a box to be granted, and which boxes take part.
//
// Three kinds of event. The daily and weekly-bonus events are built in — they
// can be switched on or off and their box line-up tuned, but not created or
// deleted. Custom events are yours to make: a name, a window, and whether the
// loot drops once for the whole window or every day inside it. When an event
// fires, one box is picked from its line-up by weight.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useDialog } from '../../context/DialogContext';
import api from '../../services/api';
import { Spinner } from './helpers';

const pct = (n) => `${(100 * (n || 0)).toFixed(1)}%`;

const TYPE_LABEL = {
  daily: 'Daily',
  weekly_bonus: 'Weekly bonus',
  custom: 'Custom'
};
const TYPE_BADGE = {
  daily: 'text-bg-primary',
  weekly_bonus: 'text-bg-warning',
  custom: 'text-bg-info'
};

// The API stores event windows as naive UTC and compares them against UTC now;
// a datetime-local input speaks the operator's local time. Converting on both
// edges is what makes "starts at 18:00" mean 18:00 where the person setting it
// is sitting — slicing the ISO string instead silently shifted every window by
// the operator's offset.
const utcToLocalInput = (iso) => {
  if (!iso) return '';
  const utc = new Date(/[Z+]|-\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(utc.getTime())) return '';
  // Shift by the offset so toISOString (always UTC) prints local wall-clock.
  return new Date(utc.getTime() - utc.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 16);
};

// A datetime-local value has no zone, so Date parses it as local time — which
// is exactly what it means. toISOString then hands the API real UTC.
const localInputToUtc = (value) => {
  if (!value) return null;
  const local = new Date(value);
  return Number.isNaN(local.getTime()) ? null : local.toISOString();
};

function Events() {
  const { token, isAdmin } = useAuth();
  const { confirm } = useDialog();
  const admin = isAdmin();
  const [events, setEvents] = useState([]);
  const [boxes, setBoxes] = useState([]);
  const [boxAdd, setBoxAdd] = useState({});
  const [newEvent, setNewEvent] = useState({
    name: '', description: '', cadence: 'daily', starts_at: '', ends_at: ''
  });
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
      const [eventsData, boxesData] = await Promise.all([
        api.admin.events.getAll(token),
        api.admin.boxes.getAll(token)
      ]);
      setEvents(eventsData.events || []);
      setBoxes(boxesData.boxes || []);
    } catch (err) {
      console.error('Load events error:', err);
      setError('Failed to load events');
    }
    setLoading(false);
  };

  const guard = (fn) => async (...args) => {
    setError('');
    setNotice('');
    try {
      await fn(...args);
      await loadData();
    } catch (err) {
      console.error('Event action error:', err);
      setError(err.message || 'That action failed');
    }
  };

  const handleCreate = guard(async () => {
    if (!newEvent.name.trim()) throw new Error('Give the event a name');
    await api.admin.events.create(token, {
      name: newEvent.name.trim(),
      description: newEvent.description.trim(),
      cadence: newEvent.cadence,
      starts_at: localInputToUtc(newEvent.starts_at),
      ends_at: localInputToUtc(newEvent.ends_at)
    });
    setNewEvent({ name: '', description: '', cadence: 'daily', starts_at: '', ends_at: '' });
    setNotice('Event created.');
  });

  const handleField = guard(async (event, patch) => {
    await api.admin.events.update(token, event.id, patch);
  });

  const handleDelete = guard(async (event) => {
    if (!(await confirm({
      title: 'Delete event?',
      message: `Delete the "${event.name}" event?`,
      confirmLabel: 'Delete'
    }))) return;
    await api.admin.events.remove(token, event.id);
    setNotice('Event deleted.');
  });

  const handleAddBox = guard(async (event) => {
    const boxId = boxAdd[event.id];
    if (!boxId) throw new Error('Pick a box to add');
    await api.admin.events.addBox(token, event.id, { box_id: parseInt(boxId, 10), weight: 1 });
    setBoxAdd({ ...boxAdd, [event.id]: '' });
  });

  const handleRemoveBox = guard(async (event, entryId) => {
    await api.admin.events.removeBox(token, event.id, entryId);
  });

  const handleReweight = async (event, entry, input) => {
    const weight = parseFloat(input.value);
    if (Number.isNaN(weight) || weight < 0) {
      input.value = entry.weight;
      return;
    }
    if (weight === entry.weight) return;
    setError('');
    try {
      await api.admin.events.setBoxWeight(token, event.id, entry.id, weight);
      loadData();
    } catch (err) {
      console.error('Reweight error:', err);
      setError(err.message || 'Failed to change that weight');
    }
  };

  if (loading) return <Spinner />;

  const boxLineup = (event) => (
    <>
      {event.boxes.length === 0 ? (
        <p className="text-body-secondary mb-2">
          No boxes in this event yet — it will grant nothing until you add one.
        </p>
      ) : (
        <div className="table-responsive">
          <table className="table table-sm align-middle mb-2">
            <thead>
              <tr>
                <th>Box</th>
                <th style={{ width: '8rem' }}>Weight</th>
                <th style={{ width: '7rem' }}>Pick chance</th>
                <th style={{ width: '5rem' }}></th>
              </tr>
            </thead>
            <tbody>
              {event.boxes.map((b) => (
                <tr key={b.id}>
                  <td>
                    {b.name}
                    <span className="text-body-secondary small ms-2">
                      {b.draws} reward{b.draws === 1 ? '' : 's'}
                    </span>
                  </td>
                  <td>
                    <input
                      type="number"
                      min="0"
                      step="0.5"
                      className="form-control form-control-sm"
                      defaultValue={b.weight}
                      disabled={!admin}
                      onBlur={(e) => handleReweight(event, b, e.target)}
                    />
                  </td>
                  <td className="text-body-secondary">
                    {b.weight > 0 ? pct(b.pick_chance) : 'never'}
                  </td>
                  <td>
                    {admin && (
                      <button
                        className="btn btn-sm btn-outline-danger"
                        onClick={() => handleRemoveBox(event, b.id)}
                      >
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {admin && (
        <div className="row g-2 align-items-end">
          <div className="col-md-8">
            <select
              className="form-select"
              value={boxAdd[event.id] || ''}
              onChange={(e) => setBoxAdd({ ...boxAdd, [event.id]: e.target.value })}
            >
              <option value="">Add a box…</option>
              {boxes
                .filter((box) => !event.boxes.some((eb) => eb.box_id === box.id))
                .map((box) => (
                  <option key={box.id} value={box.id}>{box.name}</option>
                ))}
            </select>
          </div>
          <div className="col-md-4">
            <button className="btn btn-danger w-100" onClick={() => handleAddBox(event)}>
              Add box
            </button>
          </div>
        </div>
      )}
    </>
  );

  return (
    <>
      <h4 className="font-display mb-1">Events</h4>
      <p className="text-body-secondary">
        An event grants a box by picking one from its line-up by weight. The daily
        event fires once a day; the weekly bonus is paid to players who kept a
        streak. Custom events run in a window and stack on top of the daily box.
        Manage the boxes themselves on the <strong>Loot Boxes</strong> screen.
      </p>

      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      {events.map((event) => {
        const isCustom = event.type === 'custom';
        return (
          <div className={`card mb-3 ${event.enabled ? '' : 'opacity-75'}`} key={event.id}>
            <div className="card-body">
              <div className="d-flex flex-wrap justify-content-between align-items-start gap-2 mb-2">
                <div>
                  <span className={`badge ${TYPE_BADGE[event.type]} me-2`}>
                    {TYPE_LABEL[event.type] || event.type}
                  </span>
                  {!isCustom && <span className="fw-semibold">{event.name}</span>}
                </div>
                <div className="d-flex align-items-center gap-3">
                  <div className="form-check form-switch mb-0">
                    <input
                      type="checkbox"
                      role="switch"
                      className="form-check-input"
                      id={`event-enabled-${event.id}`}
                      checked={event.enabled}
                      disabled={!admin}
                      onChange={(e) => handleField(event, { enabled: e.target.checked })}
                    />
                    <label className="form-check-label small" htmlFor={`event-enabled-${event.id}`}>
                      {event.enabled ? 'Enabled' : 'Disabled'}
                    </label>
                  </div>
                  {admin && isCustom && (
                    <button
                      className="btn btn-sm btn-outline-danger"
                      onClick={() => handleDelete(event)}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>

              {/* Editable identity */}
              <div className="row g-2 mb-3">
                {isCustom && (
                  <div className="col-md-4">
                    <label className="form-label text-body-secondary small mb-1">Name</label>
                    <input
                      className="form-control form-control-sm"
                      defaultValue={event.name}
                      disabled={!admin}
                      onBlur={(e) => {
                        const name = e.target.value.trim();
                        if (name && name !== event.name) handleField(event, { name });
                      }}
                    />
                  </div>
                )}
                <div className={isCustom ? 'col-md-8' : 'col-12'}>
                  <label className="form-label text-body-secondary small mb-1">Description</label>
                  <input
                    className="form-control form-control-sm"
                    defaultValue={event.description}
                    disabled={!admin}
                    onBlur={(e) => {
                      const description = e.target.value.trim();
                      if (description !== (event.description || '')) handleField(event, { description });
                    }}
                  />
                </div>

                {isCustom && (
                  <>
                    <div className="col-md-3">
                      <label className="form-label text-body-secondary small mb-1">Loot cadence</label>
                      <select
                        className="form-select form-select-sm"
                        value={event.cadence}
                        disabled={!admin}
                        onChange={(e) => handleField(event, { cadence: e.target.value })}
                      >
                        <option value="daily">Every day in the window</option>
                        <option value="once">Once for the whole window</option>
                      </select>
                    </div>
                    <div className="col-md-4">
                      <label className="form-label text-body-secondary small mb-1">Starts</label>
                      <input
                        type="datetime-local"
                        className="form-control form-control-sm"
                        defaultValue={utcToLocalInput(event.starts_at)}
                        disabled={!admin}
                        onBlur={(e) => {
                          if (e.target.value !== utcToLocalInput(event.starts_at)) {
                            handleField(event, { starts_at: localInputToUtc(e.target.value) });
                          }
                        }}
                      />
                    </div>
                    <div className="col-md-4">
                      <label className="form-label text-body-secondary small mb-1">Ends</label>
                      <input
                        type="datetime-local"
                        className="form-control form-control-sm"
                        defaultValue={utcToLocalInput(event.ends_at)}
                        disabled={!admin}
                        onBlur={(e) => {
                          if (e.target.value !== utcToLocalInput(event.ends_at)) {
                            handleField(event, { ends_at: localInputToUtc(e.target.value) });
                          }
                        }}
                      />
                    </div>
                  </>
                )}
              </div>

              {boxLineup(event)}
            </div>
          </div>
        );
      })}

      {/* Create a custom event */}
      {admin && (
        <div className="card mb-4">
          <div className="card-body">
            <h5 className="card-title font-display mb-3">New custom event</h5>
            <div className="row g-2 align-items-end">
              <div className="col-md-4">
                <label className="form-label text-body-secondary small mb-1">Name</label>
                <input
                  className="form-control"
                  placeholder="e.g. Launch Weekend"
                  value={newEvent.name}
                  onChange={(e) => setNewEvent({ ...newEvent, name: e.target.value })}
                />
              </div>
              <div className="col-md-8">
                <label className="form-label text-body-secondary small mb-1">Description (optional)</label>
                <input
                  className="form-control"
                  value={newEvent.description}
                  onChange={(e) => setNewEvent({ ...newEvent, description: e.target.value })}
                />
              </div>
              <div className="col-md-3">
                <label className="form-label text-body-secondary small mb-1">Loot cadence</label>
                <select
                  className="form-select"
                  value={newEvent.cadence}
                  onChange={(e) => setNewEvent({ ...newEvent, cadence: e.target.value })}
                >
                  <option value="daily">Every day in the window</option>
                  <option value="once">Once for the whole window</option>
                </select>
              </div>
              <div className="col-md-4">
                <label className="form-label text-body-secondary small mb-1">Starts (optional)</label>
                <input
                  type="datetime-local"
                  className="form-control"
                  value={newEvent.starts_at}
                  onChange={(e) => setNewEvent({ ...newEvent, starts_at: e.target.value })}
                />
              </div>
              <div className="col-md-4">
                <label className="form-label text-body-secondary small mb-1">Ends (optional)</label>
                <input
                  type="datetime-local"
                  className="form-control"
                  value={newEvent.ends_at}
                  onChange={(e) => setNewEvent({ ...newEvent, ends_at: e.target.value })}
                />
              </div>
              <div className="col-md-1">
                <button className="btn btn-danger w-100" onClick={handleCreate}>
                  Create
                </button>
              </div>
            </div>
            <div className="form-text mt-2">
              A blank start or end means the window is open on that side. After
              creating the event, add the boxes it should grant.
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default Events;
