#!/usr/bin/env python3
"""The maintenance worker: checks for updates and carries runs out.

A fourth process under supervisord rather than a job in the task worker,
because a run spends most of its life waiting - for an empty server, for the
maintenance window, for a fifteen-minute countdown - and the task worker is a
single queue that reward deliveries sit behind.

Every second it:

  * keeps the hold in step with the open run (`maintenance_store.sync_hold`);
  * starts any checks that are due - on the policy's cron schedules, when a
    server stops, sleeps or fails, or because staff pressed "Check now";
  * moves the open run along: plan -> countdown -> stop everything -> update ->
    release.

Checks and the update itself run on their own threads, because a SteamCMD call
takes minutes and the countdown and the hold must keep ticking meanwhile.

Restart-safe by construction: the run's state is in the database, the hold is
re-derived from it, and the countdown remembers which warnings it already gave.
The one thing that cannot resume is an update interrupted halfway, which is
failed on startup so the servers are released and somebody looks at it.
"""
import datetime
import threading
import time

import cache
import config
import database
import events
import maintenance
import maintenance_store as store
import models
import mods
import servers
import steam
import tasks
import workshop

TICK_SECONDS = 1.0
# A state the server can be in without anybody playing on it - the moment an
# update costs nothing, and so the moment to look for one.
QUIET_STATES = ('stopped', 'sleeping', 'failed')
# Once the hold is placed, every server should report this.
DOWN_STATES = ('maintenance',)
# How long the update waits for a SteamCMD task somebody started by hand.
STEAM_BUSY_TIMEOUT = 1800
# A server's state key is rewritten every reconcile pass (five seconds), so for
# a moment after the hold is placed it can still say "maintenance" from a hold
# that has only just ended - a run planned straight after another would then
# start replacing files under a server that is in fact relaunching. Waiting a
# few passes means every state read afterwards was written under this hold.
MIN_STOPPING_SECONDS = 15


def _log(message):
    ts = datetime.datetime.now().isoformat()
    print(f"[{ts}][Maintenance Worker] {message}")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_game(trigger):
    """Ask Steam whether the installed build is the latest. Records the answer."""
    record = {'checked_at': store.iso(store.utcnow()), 'trigger': trigger,
              'result': None, 'error': None}
    installed, error = steam.installed_app_state(config.STEAM_APP_ID, config.STEAM_INSTALL_DIR)
    if error:
        record['error'] = error
    elif not installed:
        record['result'] = maintenance.game_update(None, None)
    elif tasks.steam_busy():
        # Two SteamCMD runs at once share its state and corrupt each other's
        # output. Keep the previous answer and say why there is no new one.
        previous = store.read_check('game') or {}
        record['result'] = previous.get('result')
        record['error'] = 'Skipped: another SteamCMD task was running'
    else:
        info, error = steam.app_info(config.STEAM_APP_ID)
        if not info:
            record['error'] = error or 'Steam did not answer'
        else:
            branches = (info.get('depots') or {}).get('branches') or {}
            record['result'] = maintenance.game_update(installed, branches)
    store.write_check('game', record)
    return record


def check_mods(trigger, policy):
    """Compare every Workshop item a server uses with the Workshop's version."""
    record = {'checked_at': store.iso(store.utcnow()), 'trigger': trigger,
              'result': None, 'error': None}
    used, _names = servers.mod_usage()
    installed, error = steam.installed_workshop_items(config.STEAM_INSTALL_DIR)
    if error:
        record['error'] = error
    elif not used:
        record['result'] = {'checked': 0, 'outdated': [], 'held_back': []}
    elif not config.WORKSHOP_METADATA:
        record['error'] = 'Workshop lookups are switched off (WORKSHOP_METADATA)'
    else:
        remote, error = workshop.lookup(list(used), use_cache=False)
        if error and not remote:
            record['error'] = f'Could not reach the Workshop: {error}'
        else:
            outdated, held_back = maintenance.outdated_mods(
                used, installed, remote, policy.get('excluded_mods'))
            # What is on disk now, by the mods' own names and versions. The new
            # version's number is unknowable before downloading it - the
            # Workshop has dates, not versions - so this is the "from" half.
            for target in outdated + held_back:
                target['mods'] = [{'name': m['name'], 'version': m.get('version')}
                                  for m in mods.item_mods(target['id'])]
            record['result'] = {'checked': len(used), 'outdated': outdated,
                                'held_back': held_back}
            if error:
                record['error'] = f'Only some items could be checked: {error}'
    store.write_check('mods', record)
    return record


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------

class MaintenanceWorker:

    def __init__(self):
        self._schedules = {}                # name -> (expression, next local firing)
        self._last_check = {'game': 0.0, 'mods': 0.0}
        self._queued = {}                   # kind -> (trigger, forced)
        self._queue_lock = threading.Lock()
        self._check_thread = None
        self._checking = []
        self._update_thread = None
        self._last_states = {}

    # -- schedules ---------------------------------------------------------

    def _cron_due(self, name, expression, tz, now_local):
        """Whether ``name``'s schedule fired since the last tick.

        Next firings are computed forward from the moment an expression is
        first seen, so a restart does not replay the firings it slept through -
        the boot check covers that gap instead.
        """
        expression = ' '.join(str(expression or '').split())
        if not expression:
            self._schedules.pop(name, None)
            return False
        current = self._schedules.get(name)
        if not current or current[0] != expression or current[1] is None \
                or current[1].tzinfo != now_local.tzinfo:
            try:
                spec = maintenance.parse_cron(expression)
            except ValueError:
                self._schedules.pop(name, None)
                return False
            self._schedules[name] = (expression, maintenance.next_cron(spec, now_local))
            return False
        if now_local < current[1]:
            return False
        spec = maintenance.parse_cron(expression)
        self._schedules[name] = (expression, maintenance.next_cron(spec, now_local))
        return True

    def _next(self, name):
        entry = self._schedules.get(name)
        return store.iso(store.to_utc_naive(entry[1])) if entry and entry[1] else None

    # -- checks ------------------------------------------------------------

    def queue_check(self, kinds, trigger, forced=False):
        now = time.monotonic()
        floors = {'game': config.MAINTENANCE_GAME_CHECK_MIN_INTERVAL,
                  'mods': config.MAINTENANCE_MODS_CHECK_MIN_INTERVAL}
        with self._queue_lock:
            for kind in kinds:
                if not forced and self._last_check[kind] \
                        and now - self._last_check[kind] < floors[kind]:
                    continue
                if kind not in self._queued or forced:
                    self._queued[kind] = (trigger, forced)

    def _start_checks(self, policy):
        if self._check_thread and self._check_thread.is_alive():
            return
        with self._queue_lock:
            if not self._queued:
                return
            batch, self._queued = self._queued, {}
        self._checking = sorted(batch)
        self._check_thread = threading.Thread(target=self._run_checks, args=(batch, policy),
                                              daemon=True)
        self._check_thread.start()

    def _run_checks(self, batch, policy):
        try:
            game_check = mods_check = None
            trigger = 'manual'
            if 'game' in batch:
                trigger = batch['game'][0]
                self._last_check['game'] = time.monotonic()
                game_check = check_game(trigger)
            if 'mods' in batch:
                trigger = batch['mods'][0]
                self._last_check['mods'] = time.monotonic()
                mods_check = check_mods(trigger, policy)
            self._after_checks(game_check, mods_check, trigger, policy)
        except Exception as e:
            _log(f"Check failed: {e}")
        finally:
            self._checking = []

    def _after_checks(self, game_check, mods_check, trigger, policy):
        # Use the freshest answer for each kind, whether or not this batch
        # asked again - a mods-only check should not forget the game update the
        # last game check found.
        game_check = game_check or store.read_check('game')
        mods_check = mods_check or store.read_check('mods')

        everything = maintenance.empty_targets()
        if ((game_check or {}).get('result') or {}).get('update_available'):
            everything['game'] = game_check['result']
        everything['mods'] = list(((mods_check or {}).get('result') or {}).get('outdated') or [])
        if maintenance.has_targets(everything) and store.note_new_updates(everything):
            needs_approval = []
            if everything['game'] and policy.get('game_requires_approval'):
                needs_approval.append('game')
            if everything['mods'] and policy.get('mods_requires_approval'):
                needs_approval.append('mods')
            events.emit('maintenance.available',
                        summary=maintenance.describe_targets(everything),
                        mods=[m.get('title') or m['id'] for m in everything['mods']],
                        game=everything['game'], needs_approval=needs_approval)

        if not policy.get('enabled'):
            return
        targets = maintenance.automatic_targets(game_check, mods_check, policy)
        if maintenance.has_targets(targets):
            _run, error = store.plan(targets, trigger, policy=policy, automatic=True)
            if error and not error.startswith('suppressed'):
                _log(f"Could not plan: {error}")

    def _watch_states(self, states, policy):
        """Queue a check when a server goes quiet."""
        changed = False
        for server in states:
            previous = self._last_states.get(server['id'])
            state = server['state']
            if previous is not None and state != previous and state in QUIET_STATES:
                changed = True
            self._last_states[server['id']] = state
        if changed and policy.get('enabled') and policy.get('check_on_state_change'):
            self.queue_check(('mods', 'game'), 'state_change')

    # -- the run -----------------------------------------------------------

    def _sync_hold(self, run):
        if run and run['status'] in models.MaintenanceRun.HOLD_STATES:
            store.set_hold(run['id'])
        elif store.hold_info() is not None:
            store.release_hold()

    def _advance(self, run, policy, states, window_fired, now):
        players = sum(s['players'] for s in states)
        status = run['status']

        if status == 'scheduled':
            force_at = _parse(run['force_at'])
            deadline = _parse(run['deadline'])
            action, reason = maintenance.decide_scheduled(
                force_at, deadline, players, window_fired, policy, now)
            length = maintenance.countdown_length(policy)
            if action == 'countdown' and length:
                run = store.transition(
                    run['id'], 'scheduled', 'announcing', reason=reason,
                    countdown_ends_at=now + datetime.timedelta(seconds=length),
                    announced=[],
                    note=f"Countdown started ({maintenance.format_duration(length)}): {reason}")
                if run:
                    store.emit('maintenance.started', run['id'], countdown=length,
                               players=players)
                    self._announce(run, policy, now)
            elif action in ('countdown', 'stop'):
                self._begin_stopping(run, 'scheduled', reason, now, players)
            return

        if status == 'announcing':
            if players == 0:
                self._begin_stopping(run, 'announcing', 'everybody has left', now, 0)
                return
            ends = _parse(run['countdown_ends_at']) or now
            if now >= ends:
                self._begin_stopping(run, 'announcing', run.get('reason'), now, players)
                return
            self._announce(run, policy, now)
            return

        if status == 'stopping':
            started = _parse(run['started_at']) or now
            # A server with no published state has no manager reporting for it,
            # and so no game process this stack is running; waiting on it would
            # only turn a missing manager into a failed update.
            not_down = [s for s in states if s['state'] is not None
                        and s['state'] not in DOWN_STATES]
            settled = (now - started).total_seconds() >= MIN_STOPPING_SECONDS
            if not not_down and settled:
                updating = store.transition(
                    run['id'], 'stopping', 'updating',
                    note='Every server is down; updating')
                if updating:
                    self._start_update(updating)
                return
            if (now - started).total_seconds() > config.MAINTENANCE_STOP_TIMEOUT:
                names = ', '.join(f"{s['name']} ({s['state']})" for s in not_down)
                failed = store.transition(
                    run['id'], 'stopping', 'failed', reason='servers did not stop',
                    message=f'Gave up waiting for: {names}. Nothing was updated.',
                    note=f'Servers did not stop in time: {names}')
                if failed:
                    store.emit('maintenance.failed', failed['id'], error=failed['message'])
            return

        if status == 'updating':
            if not (self._update_thread and self._update_thread.is_alive()):
                # The thread that was updating is not in this process: the
                # worker restarted mid-update. It cannot be resumed - SteamCMD
                # went with it - so fail it and let the servers come back.
                failed = store.transition(
                    run['id'], 'updating', 'failed', reason='interrupted',
                    message='The maintenance worker restarted during the update. '
                            'Check the installation and run the update again.',
                    note='Interrupted by a restart of the maintenance worker')
                if failed:
                    store.emit('maintenance.failed', failed['id'], error=failed['message'])

    def _begin_stopping(self, run, expected, reason, now, players):
        moved = store.transition(
            run['id'], expected, 'stopping', reason=reason, started_at=now,
            note=f"Taking every server down: {reason}")
        if moved:
            store.set_hold(moved['id'])
            if expected == 'scheduled':
                store.emit('maintenance.started', moved['id'], countdown=0, players=players)

    def _announce(self, run, policy, now):
        ends = _parse(run['countdown_ends_at'])
        if not ends:
            return
        remaining = (ends - now).total_seconds()
        say, sent = maintenance.due_announcement(policy.get('countdown'), remaining,
                                                 run.get('announced'))
        if say is None:
            return
        # Recorded before it is said, so a crash between the two skips one
        # warning rather than repeating it on every restart.
        store.update_run(run['id'], announced=sent)
        text = maintenance.render_message(policy.get('message'), say)
        delivered = store.broadcast(text)
        _log(f"Announced '{text}' on {delivered} server(s)")

    def _start_update(self, run):
        self._update_thread = threading.Thread(target=self._run_update, args=(run,),
                                               daemon=True)
        self._update_thread.start()

    def _run_update(self, run):
        run_id = run['id']
        targets = run.get('targets') or maintenance.empty_targets()
        notes, task_ids, ok = [], [], True
        try:
            waited = 0
            while tasks.steam_busy() and waited < STEAM_BUSY_TIMEOUT:
                if waited == 0:
                    store.update_run(run_id, note='Waiting for a running SteamCMD task to finish')
                time.sleep(5)
                waited += 5

            game = targets.get('game')
            if game:
                branch = game.get('branch') or 'public'
                data = {'action': 'update_server', 'maintenance_run': run_id,
                        'beta': '' if branch == 'public' else branch}
                store.update_run(run_id, note=f"Updating the game on branch '{branch}'")
                game_ok, task = tasks.run_inline(data)
                task_ids.append(task['id'])
                ok = ok and game_ok
                notes.append(f"game: {(task.get('data') or {}).get('message')}")

            mod_targets = targets.get('mods') or []
            if mod_targets:
                ids = [m['id'] for m in mod_targets]
                store.update_run(run_id, task_ids=task_ids,
                                 note=f"Downloading {len(ids)} Workshop item(s)")
                data = {'action': 'download_workshop', 'maintenance_run': run_id,
                        'workshop_ids': ids}
                mods_ok, task = tasks.run_inline(data)
                task_ids.append(task['id'])
                ok = ok and mods_ok
                notes.append(f"mods: {(task.get('data') or {}).get('message')}")
        except Exception as e:
            ok = False
            notes.append(f'error: {e}')
            _log(f"Run {run_id} update raised: {e}")

        message = '; '.join(notes) or 'Nothing to update'
        status = 'completed' if ok else 'failed'
        finished = store.transition(
            run_id, 'updating', status, task_ids=task_ids, message=message,
            reason=None if ok else 'update failed',
            note=('Update finished; releasing the servers' if ok
                  else 'Update failed; releasing the servers'))
        store.release_hold()
        if finished:
            store.emit('maintenance.completed' if ok else 'maintenance.failed',
                       run_id, error=None if ok else message)
        # Refresh what the panel shows as outstanding.
        self.queue_check(('game', 'mods'), 'after_update', forced=True)

    # -- loop --------------------------------------------------------------

    def tick(self):
        now = store.utcnow()
        policy, _meta = store.get_policy()
        tz = store.site_timezone()
        now_local = store.to_local(now, tz)
        states = store.server_states()

        # Evaluated every tick, not only while a run waits, so a window that
        # opened before a run existed does not count as "just opened" later.
        window_fired = self._cron_due('window', policy.get('window_cron'), tz, now_local)
        if policy.get('enabled'):
            if self._cron_due('game', policy.get('game_check_cron'), tz, now_local):
                self.queue_check(('game',), 'schedule', forced=True)
            if self._cron_due('mods', policy.get('mods_check_cron'), tz, now_local):
                self.queue_check(('mods',), 'schedule', forced=True)
        else:
            self._schedules.pop('game', None)
            self._schedules.pop('mods', None)
        self._watch_states(states, policy)

        request = store.pop_check_request()
        if request:
            kinds = [k for k in request.get('kinds') or [] if k in ('game', 'mods')]
            self.queue_check(kinds, 'manual', forced=True)
        self._start_checks(policy)

        run = store.open_run()
        if run:
            self._advance(run, policy, states, window_fired, now)
            run = store.open_run()
        self._sync_hold(run)
        store.write_public_notice(run)

        store.write_worker_status({
            'alive_at': store.iso(now),
            'timezone': getattr(tz, 'key', None) or 'UTC',
            'checking': list(self._checking),
            'next': {'game': self._next('game'), 'mods': self._next('mods'),
                     'window': self._next('window')},
        })

    def run(self):
        _log('Maintenance worker started')
        self._recover()
        policy, _meta = store.get_policy()
        if policy.get('enabled'):
            self.queue_check(('game', 'mods'), 'boot')
        while True:
            started = time.monotonic()
            try:
                self.tick()
            except Exception as e:
                _log(f"Tick failed: {e}")
            time.sleep(max(0.0, TICK_SECONDS - (time.monotonic() - started)))

    def _recover(self):
        """Fail an update this process was running before it restarted."""
        run = store.open_run()
        if run and run['status'] == 'updating':
            failed = store.transition(
                run['id'], 'updating', 'failed', reason='interrupted',
                message='The maintenance worker restarted during the update. '
                        'Check the installation and run the update again.',
                note='Interrupted by a restart of the maintenance worker')
            if failed:
                store.emit('maintenance.failed', failed['id'], error=failed['message'])
        if not run or run['status'] not in models.MaintenanceRun.HOLD_STATES:
            store.release_hold()


def _parse(value):
    """A stored ISO time back to naive UTC."""
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).rstrip('Z'))
    except ValueError:
        return None


if __name__ == '__main__':
    _log('Checking database availability...')
    database.wait_table(models.MaintenanceRun, timeout=60 * 5)
    _log('Checking cache availability...')
    cache.wait()
    try:
        MaintenanceWorker().run()
    except KeyboardInterrupt:
        _log('Service stopped')
