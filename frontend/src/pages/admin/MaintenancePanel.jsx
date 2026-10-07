// Admin › Servers › Installations › Maintenance: keeping the game and its mods
// up to date without anybody having to be awake for it.
//
// The game-server's maintenance worker checks for updates, plans a run, warns
// whoever is playing, takes every server down, updates and brings them back.
// Every server, because one install and one Workshop library serve them all.
// This panel shows what it is doing and holds the decisions: the policy and
// what to plan are an admin's; calling a planned run off is a moderator's too.
import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useDialog } from '../../context/DialogContext';
import api from '../../services/api';
import { getStatusBadge } from './helpers';
import { formatDateTime, fromUnix, parseDate } from '../../utils/dates';

const WORKSHOP_URL = (id) => `https://steamcommunity.com/sharedfiles/filedetails/?id=${id}`;
const CHANGELOG_URL = (id) => `https://steamcommunity.com/sharedfiles/filedetails/changelog/${id}`;

// Stored times are UTC ISO strings with a trailing Z; Steam's are unix seconds.
const fmtIso = (iso) => formatDateTime(iso, '—');
const fmtUnix = (seconds) => formatDateTime(fromUnix(seconds), '—');

const fmtBytes = (n) => {
  if (n === null || n === undefined) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
};

const fmtRemaining = (ms) => {
  const total = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${String(s).padStart(2, '0')}s`;
  return `${s}s`;
};

const describeTargets = (targets) => {
  const parts = [];
  const game = targets && targets.game;
  if (game) parts.push(`game build ${game.installed_build} → ${game.available_build}`);
  const mods = (targets && targets.mods) || [];
  if (mods.length) parts.push(`${mods.length} mod${mods.length === 1 ? '' : 's'}`);
  return parts.join(' and ') || 'nothing';
};

const RUN_LABELS = {
  scheduled: 'Planned',
  announcing: 'Counting down',
  stopping: 'Stopping servers',
  updating: 'Updating',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled'
};

const TRIGGER_LABELS = {
  schedule: 'scheduled check',
  state_change: 'server went quiet',
  boot: 'start-up check',
  manual: 'staff',
  after_update: 'after an update'
};

const runBadge = (status) => ({
  scheduled: 'info',
  announcing: 'warning',
  stopping: 'warning',
  updating: 'primary',
  cancelled: 'secondary'
}[status] || getStatusBadge(status));

// While something is moving, poll briskly; while a run merely waits, slowly;
// otherwise not at all - the refresh button is there for the rest.
const pollInterval = (data) => {
  if (!data) return null;
  const run = data.open_run;
  const checking = (data.worker && (data.worker.checking || []).length) || data.check_requested;
  if (checking || (run && run.status !== 'scheduled')) return 3000;
  if (run) return 15000;
  return null;
};

// --------------------------------------------------------------------------
// Planning dialog: which of the outstanding updates go into the run
// --------------------------------------------------------------------------

function PlanModal({ checks, policy, openRun, busy, onPlan, onToggleExclude, onClose }) {
  const game = checks.game && checks.game.result;
  const gameAvailable = Boolean(game && game.update_available);
  const modsResult = (checks.mods && checks.mods.result) || {};
  const excluded = new Set(policy.excluded_mods || []);
  const items = [...(modsResult.outdated || []), ...(modsResult.held_back || [])];

  const [includeGame, setIncludeGame] = useState(gameAvailable);
  const [selected, setSelected] = useState(
    () => new Set(items.filter((m) => !excluded.has(m.id)).map((m) => m.id))
  );
  const [mode, setMode] = useState('auto');

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const toggle = (id) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const nothing = !(includeGame && gameAvailable) && selected.size === 0;
  const joining = openRun && ['scheduled', 'announcing'].includes(openRun.status);

  return (
    <div
      className="modal show d-block"
      style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
      onClick={onClose}
    >
      <div
        className="modal-dialog modal-dialog-centered modal-lg modal-dialog-scrollable"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title font-display">Plan maintenance</h5>
            <button type="button" className="btn-close" onClick={onClose} aria-label="Close"></button>
          </div>

          <div className="modal-body">
            {joining && (
              <div className="alert alert-info py-2">
                A run is already planned; what you pick here is added to it, so one
                restart covers everything.
              </div>
            )}

            <h6 className="font-display">Game</h6>
            {gameAvailable ? (
              <div className="form-check mb-3">
                <input
                  className="form-check-input"
                  type="checkbox"
                  id="plan-game"
                  checked={includeGame}
                  onChange={(e) => setIncludeGame(e.target.checked)}
                />
                <label className="form-check-label" htmlFor="plan-game">
                  Build <span className="font-monospace">{game.installed_build}</span> →{' '}
                  <span className="font-monospace">{game.available_build}</span> on{' '}
                  <span className="font-monospace">{game.branch}</span>
                  {game.available_at && (
                    <span className="text-body-secondary small"> · released {fmtUnix(game.available_at)}</span>
                  )}
                  {game.damaged && (
                    <span className="badge text-bg-warning ms-2">install incomplete</span>
                  )}
                </label>
              </div>
            ) : (
              <p className="text-body-secondary small">The game is up to date.</p>
            )}

            <h6 className="font-display">Workshop mods</h6>
            {items.length === 0 ? (
              <p className="text-body-secondary small mb-0">Every mod in use is up to date.</p>
            ) : (
              <>
                <p className="text-body-secondary small">
                  The Workshop keeps dates, not version numbers, so the new version
                  is known only by when it was published — the changelog link is the
                  best place to see what changed. Versions shown are what is
                  installed now, where the mod declares one.
                </p>
                <ul className="list-unstyled mb-2">
                  {items.map((mod) => (
                    <li key={mod.id} className="d-flex gap-2 align-items-start mb-3">
                      <input
                        className="form-check-input mt-1 flex-shrink-0"
                        type="checkbox"
                        id={`plan-mod-${mod.id}`}
                        checked={selected.has(mod.id)}
                        onChange={() => toggle(mod.id)}
                      />
                      <div className="flex-grow-1">
                        <label className="form-check-label" htmlFor={`plan-mod-${mod.id}`}>
                          <strong>{mod.title || 'Unknown item'}</strong>{' '}
                          <a
                            href={WORKSHOP_URL(mod.id)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="font-monospace small"
                          >
                            {mod.id}
                          </a>
                        </label>
                        {excluded.has(mod.id) && (
                          <span className="badge text-bg-secondary ms-2">excluded from automatic updates</span>
                        )}
                        <div className="small text-body-secondary">
                          Installed {fmtUnix(mod.installed_at)} → published {fmtUnix(mod.updated_at)}
                          {mod.size ? ` · ${fmtBytes(mod.size)}` : ''}
                          {' · '}
                          <a href={CHANGELOG_URL(mod.id)} target="_blank" rel="noopener noreferrer">
                            changelog
                          </a>
                        </div>
                        {(mod.mods || []).length > 0 && (
                          <div className="small text-body-secondary">
                            {mod.mods.map((m) => (m.version ? `${m.name} ${m.version}` : m.name)).join(', ')}
                          </div>
                        )}
                        <div className="small">
                          {(mod.servers || []).map((name) => (
                            <span key={name} className="badge text-bg-secondary me-1">{name}</span>
                          ))}
                          <button
                            type="button"
                            className="btn btn-link btn-sm p-0 ms-1 align-baseline"
                            onClick={() => onToggleExclude(mod.id)}
                            disabled={busy}
                          >
                            {excluded.has(mod.id) ? 'Include in automatic updates' : 'Exclude from automatic updates'}
                          </button>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
                <div className="alert alert-warning small py-2 mb-0">
                  Holding a mod back is temporary at best: players&rsquo; Steam clients
                  always download a mod&rsquo;s latest version, and a server on an
                  older one can refuse them with a version mismatch.
                </div>
              </>
            )}

            <h6 className="font-display mt-3">When</h6>
            <div className="form-check">
              <input
                className="form-check-input"
                type="radio"
                name="plan-mode"
                id="plan-mode-auto"
                checked={mode === 'auto'}
                onChange={() => setMode('auto')}
              />
              <label className="form-check-label" htmlFor="plan-mode-auto">
                As the policy allows
                <div className="small text-body-secondary">
                  {policy.apply_when_empty ? 'As soon as every server is empty, ' : ''}
                  {policy.window_cron ? 'in the maintenance window' : 'without a maintenance window'}
                  {policy.max_wait_hours ? `, or with a countdown after ${policy.max_wait_hours} hours at the latest` : ''}.
                </div>
              </label>
            </div>
            <div className="form-check">
              <input
                className="form-check-input"
                type="radio"
                name="plan-mode"
                id="plan-mode-now"
                checked={mode === 'now'}
                onChange={() => setMode('now')}
              />
              <label className="form-check-label" htmlFor="plan-mode-now">
                Now
                <div className="small text-body-secondary">
                  Start the countdown straight away — or stop at once if nobody is on.
                </div>
              </label>
            </div>
          </div>

          <div className="modal-footer">
            <button className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
            <button
              className="btn btn-danger"
              disabled={busy || nothing}
              onClick={() => onPlan({
                game: includeGame && gameAvailable,
                mods: [...selected],
                mode
              })}
            >
              {busy ? 'Planning…' : (joining ? 'Add to the planned run' : 'Plan maintenance')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Policy form
// --------------------------------------------------------------------------

const toForm = (policy) => ({
  ...policy,
  countdown: (policy.countdown || []).join(', '),
  excluded_mods: (policy.excluded_mods || []).join('\n')
});

function Field({ label, error, help, children }) {
  return (
    <div className="mb-3">
      <label className="form-label small text-body-secondary mb-1">{label}</label>
      {children}
      {error ? <div className="invalid-feedback d-block">{error}</div>
        : help && <div className="form-text">{help}</div>}
    </div>
  );
}

function Switch({ id, label, help, checked, onChange, disabled }) {
  return (
    <div className="form-check form-switch mb-2">
      <input
        className="form-check-input"
        type="checkbox"
        role="switch"
        id={id}
        checked={Boolean(checked)}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
      />
      <label className="form-check-label" htmlFor={id}>
        {label}
        {help && <div className="small text-body-secondary">{help}</div>}
      </label>
    </div>
  );
}

function PolicyForm({ policy, meta, worker, admin, busy, onSave }) {
  const [form, setForm] = useState(() => toForm(policy));
  const [errors, setErrors] = useState({});

  // Reset to the stored policy only when it actually changes. The panel polls
  // while a run is moving, and every poll is a new object: keyed on identity,
  // this would wipe whatever an admin was halfway through typing.
  const stored = JSON.stringify(policy);
  useEffect(() => {
    setForm(toForm(JSON.parse(stored)));
    setErrors({});
  }, [stored]);

  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));
  const setText = (key) => (e) => set(key)(e.target.value);
  const next = (worker && worker.next) || {};
  const zone = (worker && worker.timezone) || 'UTC';
  const readOnly = !admin || busy;

  const submit = async (e) => {
    e.preventDefault();
    // Sent as typed: the game-server parses the comma and line lists itself
    // and reports per field what it could not read.
    const result = await onSave({
      ...form,
      max_wait_hours: form.max_wait_hours === '' ? 0 : form.max_wait_hours
    });
    setErrors(result || {});
  };

  return (
    <form onSubmit={submit}>
      <Switch
        id="mt-enabled"
        label="Automatic maintenance"
        help="Check on the schedules below and plan runs on its own. Checking and planning by hand work either way."
        checked={form.enabled}
        onChange={set('enabled')}
        disabled={readOnly}
      />

      <div className="row g-3 mt-1">
        <div className="col-md-4">
          <Field
            label="Check the game"
            error={errors.game_check_cron}
            help={next.game ? `Next: ${fmtIso(next.game)}` : 'Empty switches it off.'}
          >
            <input className="form-control font-monospace" value={form.game_check_cron || ''}
              onChange={setText('game_check_cron')} disabled={readOnly} placeholder="0 */6 * * *" />
          </Field>
        </div>
        <div className="col-md-4">
          <Field
            label="Check mods"
            error={errors.mods_check_cron}
            help={next.mods ? `Next: ${fmtIso(next.mods)}` : 'Empty switches it off.'}
          >
            <input className="form-control font-monospace" value={form.mods_check_cron || ''}
              onChange={setText('mods_check_cron')} disabled={readOnly} placeholder="*/30 * * * *" />
          </Field>
        </div>
        <div className="col-md-4">
          <Field
            label="Maintenance window"
            error={errors.window_cron}
            help={next.window ? `Next: ${fmtIso(next.window)}` : 'When a forced restart may start. Empty: never on a schedule.'}
          >
            <input className="form-control font-monospace" value={form.window_cron || ''}
              onChange={setText('window_cron')} disabled={readOnly} placeholder="0 5 * * *" />
          </Field>
        </div>
      </div>
      <p className="form-text mt-0">
        Cron format — minute, hour, day, month, weekday — read in{' '}
        <span className="font-monospace">{zone}</span>, the primary server&rsquo;s timezone.
      </p>

      <div className="row g-3">
        <div className="col-md-6">
          <Switch id="mt-state" label="Also check when a server stops, sleeps or fails"
            help="The moment an update costs nobody anything."
            checked={form.check_on_state_change} onChange={set('check_on_state_change')} disabled={readOnly} />
          <Switch id="mt-empty" label="Apply as soon as every server is empty"
            help="Nobody to warn, so no countdown."
            checked={form.apply_when_empty} onChange={set('apply_when_empty')} disabled={readOnly} />
        </div>
        <div className="col-md-6">
          <Switch id="mt-game-approval" label="Game updates wait for approval"
            checked={form.game_requires_approval} onChange={set('game_requires_approval')} disabled={readOnly} />
          <Switch id="mt-mods-approval" label="Mod updates wait for approval"
            help="Somebody else's code, arriving unannounced."
            checked={form.mods_requires_approval} onChange={set('mods_requires_approval')} disabled={readOnly} />
        </div>
      </div>

      <div className="row g-3 mt-1">
        <div className="col-md-4">
          <Field label="Force it after (hours)" error={errors.max_wait_hours}
            help="With a countdown, wherever the clock is. 0 waits indefinitely.">
            <input type="number" min="0" className="form-control" value={form.max_wait_hours ?? ''}
              onChange={setText('max_wait_hours')} disabled={readOnly} />
          </Field>
        </div>
        <div className="col-md-8">
          <Field label="Warnings (seconds before the restart)" error={errors.countdown}
            help="Each is broadcast in game once. Empty: no warning at all.">
            <input className="form-control font-monospace" value={form.countdown}
              onChange={setText('countdown')} disabled={readOnly} placeholder="900, 600, 300, 30, 15, 5" />
          </Field>
        </div>
      </div>

      <Field label="Warning message" error={errors.message}
        help={<><code>{'{time}'}</code> becomes &ldquo;15 minutes&rdquo;, &ldquo;30 seconds&rdquo;… No quotes or line breaks.</>}>
        <input className="form-control" value={form.message || ''}
          onChange={setText('message')} disabled={readOnly} maxLength={200} />
      </Field>
      <Field label="Cancellation message" error={errors.cancel_message}
        help="Broadcast if a run is called off after players were warned.">
        <input className="form-control" value={form.cancel_message || ''}
          onChange={setText('cancel_message')} disabled={readOnly} maxLength={200} />
      </Field>
      <Field label="Never update these mods automatically" error={errors.excluded_mods}
        help="Workshop item ids, one per line. They can still be picked by hand when planning.">
        <textarea className="form-control font-monospace" rows="2" value={form.excluded_mods}
          onChange={setText('excluded_mods')} disabled={readOnly}></textarea>
      </Field>

      <div className="d-flex align-items-center gap-3">
        {admin && (
          <button className="btn btn-primary" type="submit" disabled={busy}>Save policy</button>
        )}
        {meta && meta.updated_at && (
          <span className="small text-body-secondary">
            Last changed {fmtIso(meta.updated_at)}{meta.updated_by ? ` by ${meta.updated_by}` : ''}
          </span>
        )}
      </div>
    </form>
  );
}

// --------------------------------------------------------------------------
// The panel
// --------------------------------------------------------------------------

function MaintenancePanel() {
  const { token, isAdmin } = useAuth();
  const { confirm } = useDialog();
  const admin = isAdmin();

  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [showLog, setShowLog] = useState(null);
  const [now, setNow] = useState(Date.now());

  const load = useCallback(async () => {
    try {
      setData(await api.admin.maintenance.get(token));
    } catch (err) {
      console.error('Load maintenance error:', err);
      setError(err.message || 'Could not read the maintenance state');
    }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const interval = pollInterval(data);
  useEffect(() => {
    if (!interval) return undefined;
    const id = setInterval(load, interval);
    return () => clearInterval(id);
  }, [interval, load]);

  // The countdown is shown to the second without asking the server every second.
  const counting = data && data.open_run && data.open_run.status === 'announcing';
  useEffect(() => {
    if (!counting) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [counting]);

  const act = async (fn, fallback) => {
    setError('');
    setNotice('');
    setBusy(true);
    try {
      const result = await fn();
      setNotice((result && result.message) || fallback);
      await load();
      return { ok: true };
    } catch (err) {
      console.error('Maintenance action error:', err);
      setError(err.message || 'That did not work');
      return { ok: false, errors: (err.data && err.data.errors) || {} };
    } finally {
      setBusy(false);
    }
  };

  if (!data) {
    return error
      ? <div className="alert alert-danger">{error}</div>
      : null;
  }

  const { policy, open_run: run, checks = {}, worker, runs = [] } = data;
  const workerAlive = Boolean(worker);
  const checking = (worker && worker.checking) || [];
  const gameCheck = checks.game;
  const modsCheck = checks.mods;
  const game = gameCheck && gameCheck.result;
  const modsResult = (modsCheck && modsCheck.result) || {};
  const outdated = modsResult.outdated || [];
  const heldBack = modsResult.held_back || [];
  const anythingAvailable = Boolean((game && game.update_available) || outdated.length || heldBack.length);
  const endsAt = run && run.countdown_ends_at ? (parseDate(run.countdown_ends_at)?.getTime() ?? null) : null;

  const savePolicy = async (form) => {
    const result = await act(() => api.admin.maintenance.savePolicy(token, form), 'Policy saved');
    return result.ok ? {} : result.errors;
  };

  const toggleExclude = async (itemId) => {
    const current = policy.excluded_mods || [];
    const next = current.includes(itemId)
      ? current.filter((id) => id !== itemId)
      : [...current, itemId];
    await act(() => api.admin.maintenance.savePolicy(token, { excluded_mods: next }),
      'Exclusions saved');
  };

  const plan = async (choice) => {
    const result = await act(() => api.admin.maintenance.plan(token, choice), 'Maintenance planned');
    if (result.ok) setPlanning(false);
  };

  const goNow = async () => {
    if (!(await confirm({
      title: 'Start maintenance now?',
      message: 'Players are warned on the configured countdown, then every server '
        + 'saves and stops while the update runs. If nobody is on, it starts at once.',
      confirmLabel: 'Start now'
    }))) return;
    act(() => api.admin.maintenance.now(token, run.id), 'Starting the countdown');
  };

  const cancel = async () => {
    if (!(await confirm({
      title: 'Cancel this maintenance?',
      message: 'The servers go back to what they were doing'
        + (run.status === 'scheduled' ? '.' : ', and players who were warned are told it is off.')
        + ' These same updates will not be planned again on their own before the next '
        + 'maintenance window.',
      confirmLabel: 'Cancel maintenance'
    }))) return;
    act(() => api.admin.maintenance.cancel(token, run.id), 'Maintenance cancelled');
  };

  return (
    <div className="card mb-4">
      <div className="card-header d-flex align-items-center flex-wrap gap-2">
        <span className="font-display">Maintenance</span>
        <span className={`badge text-bg-${policy.enabled ? 'success' : 'secondary'}`}>
          {policy.enabled ? 'Automatic' : 'Manual'}
        </span>
        {run && (
          <span className={`badge text-bg-${runBadge(run.status)}`}>{RUN_LABELS[run.status]}</span>
        )}
        <button
          className="btn btn-sm btn-outline-secondary border-0 ms-auto"
          onClick={load}
          title="Refresh"
          aria-label="Refresh"
        >
          <i className="fas fa-sync-alt"></i>
        </button>
      </div>
      <div className="card-body">
        {error && <div className="alert alert-danger" role="alert">{error}</div>}
        {notice && <div className="alert alert-success" role="alert">{notice}</div>}
        {!workerAlive && (
          <div className="alert alert-warning" role="alert">
            The maintenance worker is not reporting. Nothing will be checked or
            carried out until it is back — see the game-server container&rsquo;s log.
          </div>
        )}

        {/* ---------------------------------------------- The open run --- */}
        {run && (
          <div className={`alert alert-${run.status === 'scheduled' ? 'info' : 'warning'}`}>
            <div className="d-flex flex-wrap align-items-start gap-2">
              <div className="flex-grow-1">
                <strong>{RUN_LABELS[run.status]}:</strong> {describeTargets(run.targets)}
                {run.status === 'scheduled' && (
                  <div className="small">
                    {run.force_at ? 'Starting on the next tick.' : (
                      <>
                        Waiting for {policy.apply_when_empty ? 'every server to be empty' : 'the window'}
                        {policy.apply_when_empty && policy.window_cron ? ' or the maintenance window' : ''}
                        {run.deadline ? `; forced with a countdown at ${fmtIso(run.deadline)}` : ''}.
                      </>
                    )}
                  </div>
                )}
                {run.status === 'announcing' && endsAt && (
                  <div className="small">
                    Every server stops in <strong>{fmtRemaining(endsAt - now)}</strong>
                    {run.reason ? ` (${run.reason})` : ''}.
                  </div>
                )}
                {run.status === 'stopping' && (
                  <div className="small">Waiting for every server to save and stop.</div>
                )}
                {run.status === 'updating' && (
                  <div className="small">
                    Every server is down while the files are replaced —{' '}
                    <Link to="/admin/tasks">follow it on Tasks</Link>. This cannot be
                    cancelled halfway.
                  </div>
                )}
                <div className="small text-body-secondary">
                  Planned {fmtIso(run.created_at)}
                  {run.requested_by ? ` by ${run.requested_by}` : ` (${TRIGGER_LABELS[run.trigger] || run.trigger})`}
                </div>
              </div>
              <div className="d-flex gap-2">
                {admin && run.status === 'scheduled' && !run.force_at && (
                  <button className="btn btn-sm btn-danger" onClick={goNow} disabled={busy}>
                    Start now
                  </button>
                )}
                {run.cancellable && (
                  <button className="btn btn-sm btn-outline-dark" onClick={cancel} disabled={busy}>
                    Cancel
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ---------------------------------------------- What is due ---- */}
        <div className="row g-3 mb-3">
          <div className="col-md-6">
            <div className="small text-body-secondary mb-1">Game</div>
            {!gameCheck ? (
              <div className="text-body-secondary">Not checked yet.</div>
            ) : (
              <>
                {game && game.update_available && (
                  <div>
                    <span className="badge text-bg-warning me-1">Update available</span>
                    <span className="font-monospace">{game.installed_build} → {game.available_build}</span>
                    <span className="text-body-secondary small"> on {game.branch}</span>
                  </div>
                )}
                {game && !game.update_available && (
                  <div>
                    {game.installed_build
                      ? <>Up to date <span className="font-monospace text-body-secondary">({game.installed_build})</span></>
                      : (game.reason || 'Nothing to update')}
                  </div>
                )}
                {gameCheck.error && <div className="small text-warning-emphasis">{gameCheck.error}</div>}
                <div className="small text-body-secondary">Checked {fmtIso(gameCheck.checked_at)}</div>
              </>
            )}
          </div>
          <div className="col-md-6">
            <div className="small text-body-secondary mb-1">Workshop mods</div>
            {!modsCheck ? (
              <div className="text-body-secondary">Not checked yet.</div>
            ) : (
              <>
                {outdated.length > 0 ? (
                  <div>
                    <span className="badge text-bg-warning me-1">{outdated.length} to update</span>
                    {outdated.slice(0, 4).map((m) => m.title || m.id).join(', ')}
                    {outdated.length > 4 ? '…' : ''}
                  </div>
                ) : modsCheck.result && (
                  <div>Up to date <span className="text-body-secondary small">({modsResult.checked || 0} in use)</span></div>
                )}
                {heldBack.length > 0 && (
                  <div className="small text-body-secondary">
                    {heldBack.length} excluded mod{heldBack.length === 1 ? ' has' : 's have'} an update waiting.
                  </div>
                )}
                {modsCheck.error && <div className="small text-warning-emphasis">{modsCheck.error}</div>}
                <div className="small text-body-secondary">Checked {fmtIso(modsCheck.checked_at)}</div>
              </>
            )}
          </div>
        </div>

        {admin && (
          <div className="d-flex gap-2 flex-wrap mb-4">
            <button
              className="btn btn-outline-secondary"
              onClick={() => act(() => api.admin.maintenance.check(token), 'Check requested')}
              disabled={busy || checking.length > 0 || data.check_requested}
            >
              {checking.length > 0 || data.check_requested ? (
                <><span className="spinner-border spinner-border-sm me-1" role="status"></span>Checking…</>
              ) : (
                <><i className="fas fa-magnifying-glass"></i> Check now</>
              )}
            </button>
            <button
              className="btn btn-danger"
              onClick={() => setPlanning(true)}
              disabled={busy || !anythingAvailable
                || (run && !['scheduled', 'announcing'].includes(run.status))}
            >
              <i className="fas fa-screwdriver-wrench"></i> Review and plan…
            </button>
          </div>
        )}

        {/* ---------------------------------------------- Policy -------- */}
        <details className="mb-3">
          <summary className="font-display mb-2">Policy</summary>
          {!admin && (
            <p className="small text-body-secondary">
              Only an admin can change the policy. You can cancel a planned run.
            </p>
          )}
          <PolicyForm
            policy={policy}
            meta={data.policy_meta}
            worker={worker}
            admin={admin}
            busy={busy}
            onSave={savePolicy}
          />
        </details>

        {/* ---------------------------------------------- History ------- */}
        <details>
          <summary className="font-display mb-2">History</summary>
          {runs.length === 0 ? (
            <p className="text-body-secondary small mb-0">No maintenance has run yet.</p>
          ) : (
            <div className="table-responsive">
              <table className="table table-sm align-middle mb-0">
                <thead>
                  <tr>
                    <th>Planned</th>
                    <th>What</th>
                    <th>Status</th>
                    <th>Result</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <React.Fragment key={r.id}>
                      <tr>
                        <td className="text-nowrap small">
                          {fmtIso(r.created_at)}
                          <div className="text-body-secondary">
                            {r.requested_by || TRIGGER_LABELS[r.trigger] || r.trigger}
                          </div>
                        </td>
                        <td className="small">{describeTargets(r.targets)}</td>
                        <td>
                          <span className={`badge text-bg-${runBadge(r.status)}`}>{RUN_LABELS[r.status] || r.status}</span>
                          {r.cancelled_by && <div className="small text-body-secondary">by {r.cancelled_by}</div>}
                        </td>
                        <td className="small">{r.message || r.reason || '—'}</td>
                        <td className="text-end">
                          <button
                            className="btn btn-sm btn-outline-secondary border-0"
                            onClick={() => setShowLog(showLog === r.id ? null : r.id)}
                            title="Show the log"
                            aria-label="Show the log"
                          >
                            <i className={`fas fa-chevron-${showLog === r.id ? 'up' : 'down'}`}></i>
                          </button>
                        </td>
                      </tr>
                      {showLog === r.id && (
                        <tr>
                          <td colSpan="5" className="bg-body-tertiary">
                            <ul className="list-unstyled small mb-0 font-monospace">
                              {(r.log || []).map((entry, i) => (
                                <li key={i}>
                                  <span className="text-body-secondary">{fmtIso(entry.at)}</span> {entry.text}
                                </li>
                              ))}
                            </ul>
                            {(r.task_ids || []).length > 0 && (
                              <div className="small mt-1">
                                Tasks {r.task_ids.join(', ')} — <Link to="/admin/tasks">open Tasks</Link>
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </details>
      </div>

      {planning && (
        <PlanModal
          checks={checks}
          policy={policy}
          openRun={run}
          busy={busy}
          onPlan={plan}
          onToggleExclude={toggleExclude}
          onClose={() => setPlanning(false)}
        />
      )}
    </div>
  );
}

export default MaintenancePanel;
