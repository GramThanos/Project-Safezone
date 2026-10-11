// Admin › Users › Leaderboard: who may see it, who is left out, and the board
// itself - hidden characters included and marked why, so an exclusion can be
// checked against what it hides.
//
// Moderators can read it (it is the only place to see a disabled board);
// changing the settings is admin-only, as every setting is.
import React, { useEffect, useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';
import LeaderboardTable, { LeaderboardHeader } from '../../components/LeaderboardTable';

const KEYS = ['leaderboard_visibility', 'leaderboard_hide_banned', 'leaderboard_excluded'];

const VISIBILITY = [
  ['public', 'Public - everyone, signed in or not'],
  ['authenticated', 'Signed in - players with an account'],
  ['disabled', 'Disabled - staff only, here']
];

function Leaderboard() {
  const { token, isAdmin } = useAuth();
  const admin = isAdmin();

  const [serverId, setServerId] = useState(null);
  const [board, setBoard] = useState(null);
  const [boardError, setBoardError] = useState('');
  const [boardLoading, setBoardLoading] = useState(true);

  const [saved, setSaved] = useState(null);
  const [draft, setDraft] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const loadBoard = async (id = serverId) => {
    setBoardLoading(true);
    try {
      setBoard(await api.admin.leaderboard.get(token, id));
      setBoardError('');
    } catch (err) {
      console.error('Load leaderboard error:', err);
      setBoardError(err.message || 'Failed to load the leaderboard');
    }
    setBoardLoading(false);
  };

  const loadSettings = async () => {
    try {
      const data = await api.admin.settings.getAll(token);
      const values = {};
      (data.settings || []).filter((s) => KEYS.includes(s.key))
        .forEach((s) => { values[s.key] = s.value; });
      setSaved(values);
      setDraft(values);
    } catch (err) {
      console.error('Load settings error:', err);
      setError('Failed to load the leaderboard settings');
    }
  };

  useEffect(() => {
    if (admin) loadSettings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [admin]);

  useEffect(() => {
    loadBoard(serverId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverId]);

  const handleSave = async (e) => {
    e.preventDefault();
    // Only what changed - a blind PUT would rewrite settings edited elsewhere.
    const changed = {};
    KEYS.forEach((key) => {
      if (draft[key] !== saved[key]) changed[key] = draft[key];
    });
    if (Object.keys(changed).length === 0) {
      setNotice('Nothing to save.');
      return;
    }

    setError('');
    setNotice('');
    setSaving(true);
    try {
      await api.admin.settings.update(token, changed);
      await loadSettings();
      setNotice('Saved. Players see the change within a few seconds.');
      loadBoard();
    } catch (err) {
      console.error('Save leaderboard settings error:', err);
      setError(err.message || 'Could not save those changes');
    }
    setSaving(false);
  };

  const hiddenCount = (board?.characters || []).filter((c) => c.hidden).length;

  return (
    <>
      <h4 className="font-display mb-1">Leaderboard</h4>
      <p className="text-body-secondary">
        Every living character in each server's save, most zombie kills first. Players see the
        character's name and numbers, never the account it belongs to. Time alive is in-game time.
      </p>

      {admin && (
        <form className="card mb-4" onSubmit={handleSave}>
          <div className="card-body">
            <h5 className="card-title font-display mb-3">Settings</h5>
            {error && <div className="alert alert-danger" role="alert">{error}</div>}
            {notice && <div className="alert alert-success" role="alert">{notice}</div>}
            {!saved ? <Spinner /> : (
              <>
                <div className="mb-3">
                  <label className="form-label text-body-secondary" htmlFor="leaderboard_visibility">
                    Who can see it
                  </label>
                  <select
                    id="leaderboard_visibility"
                    className="form-select"
                    value={draft.leaderboard_visibility ?? ''}
                    onChange={(e) => setDraft({ ...draft, leaderboard_visibility: e.target.value })}
                  >
                    {VISIBILITY.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </div>

                <div className="form-check form-switch mb-3">
                  <input
                    id="leaderboard_hide_banned"
                    type="checkbox"
                    className="form-check-input"
                    checked={!!draft.leaderboard_hide_banned}
                    onChange={(e) => setDraft({ ...draft, leaderboard_hide_banned: e.target.checked })}
                  />
                  <label className="form-check-label" htmlFor="leaderboard_hide_banned">
                    Hide characters linked to a banned account
                  </label>
                </div>

                <div className="mb-3">
                  <label className="form-label text-body-secondary" htmlFor="leaderboard_excluded">
                    Excluded usernames
                  </label>
                  <textarea
                    id="leaderboard_excluded"
                    className="form-control font-monospace"
                    rows="4"
                    value={draft.leaderboard_excluded ?? ''}
                    onChange={(e) => setDraft({ ...draft, leaderboard_excluded: e.target.value })}
                  ></textarea>
                  <div className="form-text">
                    One per line. Matches the in-game username a character belongs to, or the site
                    account it is linked to, ignoring case. Every character of a matching user is left out.
                  </div>
                </div>

                <div className="d-flex gap-2">
                  <button className="btn btn-danger" type="submit" disabled={saving}>
                    {saving ? 'Saving…' : 'Save changes'}
                  </button>
                  <button
                    className="btn btn-outline-secondary"
                    type="button"
                    disabled={saving}
                    onClick={() => { setDraft(saved); setNotice(''); }}
                  >
                    Discard
                  </button>
                </div>
              </>
            )}
          </div>
        </form>
      )}

      {boardError && <div className="alert alert-danger" role="alert">{boardError}</div>}
      {boardLoading && !board ? <Spinner /> : board && (
        <>
          <LeaderboardHeader data={board} serverId={serverId} onServer={setServerId} />
          {hiddenCount > 0 && (
            <p className="small text-body-secondary">
              {hiddenCount} {hiddenCount === 1 ? 'character is' : 'characters are'} hidden from players
              and shown faded here.
            </p>
          )}
          <LeaderboardTable rows={board.characters} staff />
        </>
      )}
    </>
  );
}

export default Leaderboard;
