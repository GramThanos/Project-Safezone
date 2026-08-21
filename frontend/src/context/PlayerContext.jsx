// What the signed-in player currently has waiting.
//
// This exists because three separate problems had the same root: things the
// site knew and never said.
//
//   - The daily crate was granted only by opening the Rewards page, so a player
//     who visited any other page simply did not get one that day — and crates
//     expire. The grant now happens once per session, from here, wherever the
//     player happens to land.
//   - Nothing carried a count except notifications, so a waiting crate was
//     invisible until you went looking for it.
//   - The online roster drove the claim check and the send control silently, so
//     the player was told what they could not do and never why.
//
// One place asks for all of it, one poll, and every page reads the answer.
import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { useAuth } from './AuthContext';
import api from '../services/api';

const EMPTY = {
  boxes: [],
  unread: 0,
  streak: null,
  onlineCharacters: [],
  characters: [],
  grantedToday: null,   // the crate granted this session, for the welcome panel
  loading: true
};

const PlayerContext = createContext({ ...EMPTY, refresh: () => {} });

export const usePlayer = () => useContext(PlayerContext);

// The unread badge is polled; a count is cheap and the stack has no websockets.
const POLL_MS = 60000;

export const PlayerProvider = ({ children }) => {
  const { token, user } = useAuth();
  const [state, setState] = useState(EMPTY);
  // The daily grant is attempted once per signed-in session, not once per
  // render or per navigation.
  const grantAttemptedFor = useRef(null);

  const loadCounts = useCallback(async () => {
    if (!token) return;
    const [boxes, unread, streak] = await Promise.all([
      api.boxes.list(token).then((d) => d.boxes || []).catch(() => null),
      api.notifications.unreadCount(token).then((d) => d.unread || 0).catch(() => null),
      api.boxes.streak(token).catch(() => null)
    ]);
    setState((current) => ({
      ...current,
      boxes: boxes ?? current.boxes,
      unread: unread ?? current.unread,
      streak: streak ?? current.streak,
      loading: false
    }));
  }, [token]);

  // Which of this account's characters the game currently reports as online.
  const loadCharacters = useCallback(async () => {
    if (!token) return;
    try {
      const data = await api.characters.getAll(token);
      const characters = data.characters || [];
      const deliverable = characters.filter((c) => c.deliverable);
      const serverIds = [...new Set(deliverable.map((c) => c.server_id))];
      const rosters = {};
      await Promise.all(serverIds.map(async (id) => {
        try {
          const res = await api.servers.getOnline(token, id);
          rosters[id] = new Set(res.online || []);
        } catch {
          rosters[id] = new Set();
        }
      }));
      setState((current) => ({
        ...current,
        characters,
        onlineCharacters: deliverable.filter(
          (c) => rosters[c.server_id]?.has(c.in_game_username)
        )
      }));
    } catch (err) {
      console.error('Load characters error:', err);
    }
  }, [token]);

  const refresh = useCallback(() => {
    loadCounts();
    loadCharacters();
  }, [loadCounts, loadCharacters]);

  useEffect(() => {
    if (!token || !user) {
      setState(EMPTY);
      grantAttemptedFor.current = null;
      return undefined;
    }

    let cancelled = false;

    const start = async () => {
      // Claim first, so the counts that follow include today's crate.
      if (grantAttemptedFor.current !== token) {
        grantAttemptedFor.current = token;
        try {
          const daily = await api.boxes.claimDaily(token);
          if (!cancelled && daily.granted && daily.box) {
            setState((current) => ({ ...current, grantedToday: daily.box }));
          }
        } catch (err) {
          // A failed grant must not stop the rest of the page loading; the
          // player simply sees no new crate, and tomorrow's attempt stands.
          console.error('Daily crate error:', err);
        }
      }
      if (!cancelled) refresh();
    };

    start();
    const id = setInterval(loadCounts, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, user]);

  // A banned account has none of this; showing counts to it would be noise
  // pointing at pages it cannot open. The refresh functions are still handed
  // over as no-ops rather than omitted - a page reached directly by URL calls
  // them, and `undefined is not a function` is a worse answer than nothing
  // happening.
  const banned = user?.role === 'banned';
  const value = banned
    ? {
        ...EMPTY,
        loading: false,
        refresh: () => {},
        refreshCounts: () => {},
        refreshCharacters: () => {}
      }
    : { ...state, refresh, refreshCounts: loadCounts, refreshCharacters: loadCharacters };

  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>;
};

export default PlayerContext;
