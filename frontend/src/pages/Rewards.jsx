// Rewards: daily crates, the weekly streak, and getting what you won in game.
//
// The daily grant no longer happens here — it happens once per session from
// PlayerContext, so a player who never opens this page still gets their crate.
// This page opens crates and sends what comes out.
import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { usePlayer } from '../context/PlayerContext';
import { useToast } from '../context/ToastContext';
import api from '../services/api';
import CrateReveal from '../components/CrateReveal';
import usePageTitle from '../hooks/usePageTitle';

const SIZE_BADGE = { small: 'secondary', medium: 'info', big: 'warning', bonus: 'warning' };

// Player-facing words for the internal statuses. "held" and "sending" are how
// the database thinks; they are not how anyone waiting for an axe thinks.
const STATUS = {
  held: { label: 'Ready to send', badge: 'info' },
  sending: { label: 'On its way', badge: 'warning' },
  delivered: { label: 'Delivered', badge: 'success' },
  failed: { label: 'Did not arrive', badge: 'danger' },
  expired: { label: 'Expired', badge: 'secondary' }
};

// While anything is in flight, keep looking — delivery is a background job and
// the player should not have to reload to learn it landed.
const DELIVERY_POLL_MS = 4000;
const LAST_TARGET_KEY = 'safezone.lastSendTarget';

// A deadline is only useful if it reads like one.
const expiresIn = (iso) => {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return { text: 'Expired', urgent: true };
  const hours = Math.floor(ms / 3600000);
  if (hours < 1) return { text: 'Expires within the hour', urgent: true };
  if (hours < 48) return { text: `Expires in ${hours} hour${hours === 1 ? '' : 's'}`, urgent: true };
  return { text: `Expires in ${Math.floor(hours / 24)} days`, urgent: false };
};

function Rewards() {
  usePageTitle('Rewards');
  const { token } = useAuth();
  const { push } = useToast();
  const {
    boxes, streak, onlineCharacters, characters, refresh, refreshCounts
  } = usePlayer();

  const [inventory, setInventory] = useState([]);
  const [target, setTarget] = useState(() => localStorage.getItem(LAST_TARGET_KEY) || '');
  const [reveal, setReveal] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    loadInventory(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadInventory = async (first = false) => {
    try {
      const data = await api.inventory.list(token);
      setInventory(data.inventory || []);
      setError('');
    } catch (err) {
      console.error('Load inventory error:', err);
      // Distinguish "you have nothing" from "we could not ask" — they look
      // identical otherwise, and one of them is an outage nobody reports.
      setError('Could not load your inventory. It is still there — try again in a moment.');
    }
    if (first) setLoading(false);
  };

  // Follow deliveries while any are in flight, then stop. Delivery is a
  // background job; without this the player reloads the page to find out
  // whether the thing they are standing in game waiting for has arrived.
  const inFlight = inventory.some((i) => i.status === 'sending');
  useEffect(() => {
    if (!inFlight) return undefined;
    const id = setInterval(loadInventory, DELIVERY_POLL_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inFlight]);

  // Announce arrivals: compare each reload against what was in flight before.
  const [wasSending, setWasSending] = useState([]);
  useEffect(() => {
    const sending = inventory.filter((i) => i.status === 'sending').map((i) => i.id);
    const landed = wasSending.filter((id) => !sending.includes(id));
    landed.forEach((id) => {
      const item = inventory.find((i) => i.id === id);
      if (!item) return;
      const name = item.reward?.name || 'Your reward';
      if (item.status === 'delivered') push(`${name} arrived in game.`, { kind: 'success' });
      if (item.status === 'failed') push(`${name} could not be delivered.`, { kind: 'error' });
    });
    setWasSending(sending);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inventory]);

  const handleOpen = async (box) => {
    setError('');
    setBusy(box.id);
    try {
      const data = await api.boxes.open(token, box.id);
      setReveal({ items: data.items || [], size: box.size });
      await Promise.all([loadInventory(), refresh()]);
    } catch (err) {
      console.error('Open crate error:', err);
      setError(err.message || 'Could not open that crate');
    }
    setBusy(null);
  };

  const sendOne = async (itemId, characterId) => {
    await api.inventory.send(token, itemId, parseInt(characterId, 10));
  };

  const handleSend = async (item) => {
    if (!target) {
      setError('Pick which character should receive it');
      return;
    }
    setError('');
    setBusy(item.id);
    try {
      await sendOne(item.id, target);
      localStorage.setItem(LAST_TARGET_KEY, target);
      push(`Sending ${item.reward?.name || 'your reward'}…`);
      loadInventory();
    } catch (err) {
      console.error('Send item error:', err);
      setError(err.message || 'Could not send that');
    }
    setBusy(null);
  };

  const sendable = inventory.filter((i) => i.status === 'held' || i.status === 'failed');

  const handleSendAll = async () => {
    if (!target) {
      setError('Pick which character should receive them');
      return;
    }
    setError('');
    setBusy('all');
    let sent = 0;
    for (const item of sendable) {
      try {
        await sendOne(item.id, target);
        sent += 1;
      } catch (err) {
        console.error('Send item error:', err);
      }
    }
    localStorage.setItem(LAST_TARGET_KEY, target);
    push(sent === sendable.length
      ? `Sending ${sent} reward${sent === 1 ? '' : 's'}…`
      : `Sent ${sent} of ${sendable.length}. The rest are still here.`,
    { kind: sent === sendable.length ? 'info' : 'error' });
    setBusy(null);
    loadInventory();
    refreshCounts();
  };

  // The target must still be online; a remembered choice can go stale.
  const targetValid = onlineCharacters.some((c) => String(c.id) === String(target));
  useEffect(() => {
    if (!targetValid && onlineCharacters.length === 1) {
      setTarget(String(onlineCharacters[0].id));
    }
  }, [targetValid, onlineCharacters]);

  return (
    <section className="py-5" style={{ minHeight: '50vh' }}>
      <div className="container">
        <h2 className="text-uppercase font-display mb-4">Rewards</h2>

        {error && <div className="alert alert-danger">{error}</div>}

        {/* Streak — the mechanic that was previously invisible */}
        {streak?.enabled && (
          <div className="card mb-4">
            <div className="card-body">
              <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
                <h5 className="card-title font-display mb-0">
                  <i className="fas fa-fire text-danger me-2"></i>
                  This week
                </h5>
                <span className="text-body-secondary small">
                  {streak.earned
                    ? 'Bonus crate earned — it arrives when the week ends'
                    : streak.remaining <= streak.days_left + 1
                      ? `${streak.remaining} more day${streak.remaining === 1 ? '' : 's'} for a bonus crate`
                      : 'Not enough days left for the bonus this week'}
                </span>
              </div>
              <div className="d-flex gap-1" aria-label={`${streak.collected} of ${streak.threshold} days collected`}>
                {[1, 2, 3, 4, 5, 6, 7].map((day) => {
                  const got = streak.days.includes(day);
                  const future = day > streak.today;
                  return (
                    <div
                      key={day}
                      className={`flex-fill rounded text-center small py-1 ${
                        got ? 'bg-danger text-white' : future ? 'bg-body-tertiary text-body-secondary' : 'bg-body-tertiary text-body-secondary opacity-50'
                      }`}
                      title={got ? 'Collected' : future ? 'Still to come' : 'Missed'}
                    >
                      {['M', 'T', 'W', 'T', 'F', 'S', 'S'][day - 1]}
                    </div>
                  );
                })}
              </div>
              <div className="form-text mt-2">
                Collect {streak.threshold} daily crates in a week for a bonus crate.
                You have {streak.collected}.
              </div>
            </div>
          </div>
        )}

        {/* Crates */}
        <h5 className="font-display mb-3">My Crates</h5>
        {boxes.length === 0 ? (
          <p className="text-body-secondary">
            No crates waiting. A new one arrives each day you visit.
          </p>
        ) : (
          <div className="row g-3 mb-4">
            {boxes.map((box) => {
              const deadline = box.expires_at ? expiresIn(box.expires_at) : null;
              return (
                <div key={box.id} className="col-6 col-md-3">
                  <div className="card text-center h-100">
                    <div className="card-body">
                      <i className="fas fa-box-open fa-2x mb-2"></i>
                      <div className="mb-2">
                        <span className={`badge text-bg-${SIZE_BADGE[box.size] || 'secondary'}`}>{box.size}</span>
                        {box.source === 'bonus' && (
                          <span className="badge text-bg-warning ms-1">weekly bonus</span>
                        )}
                      </div>
                      {deadline && (
                        <div className={`small mb-2 ${deadline.urgent ? 'text-danger' : 'text-body-secondary'}`}>
                          {deadline.text}
                        </div>
                      )}
                      <button
                        className="btn btn-danger btn-sm w-100"
                        onClick={() => handleOpen(box)}
                        disabled={busy === box.id}
                      >
                        {busy === box.id ? 'Opening…' : 'Open'}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Where things go */}
        <div className="d-flex flex-wrap justify-content-between align-items-end gap-2 mb-3">
          <h5 className="font-display mb-0">My Inventory</h5>
          {sendable.length > 0 && (
            <div className="d-flex flex-wrap align-items-center gap-2">
              <label className="text-body-secondary small mb-0" htmlFor="send-target">
                Send to
              </label>
              <select
                id="send-target"
                className="form-select form-select-sm"
                style={{ width: 'auto' }}
                value={targetValid ? target : ''}
                onChange={(e) => setTarget(e.target.value)}
                disabled={onlineCharacters.length === 0}
              >
                <option value="">
                  {onlineCharacters.length === 0 ? 'Nobody online' : 'Pick a character…'}
                </option>
                {onlineCharacters.map((c) => (
                  <option key={c.id} value={c.id}>{c.in_game_username}</option>
                ))}
              </select>
              {sendable.length > 1 && (
                <button
                  className="btn btn-sm btn-outline-light"
                  onClick={handleSendAll}
                  disabled={!targetValid || busy === 'all'}
                >
                  {busy === 'all' ? 'Sending…' : `Send all ${sendable.length}`}
                </button>
              )}
            </div>
          )}
        </div>

        {/* The dead end this used to be: a disabled control and no way to learn why */}
        {sendable.length > 0 && onlineCharacters.length === 0 && (
          <div className="alert alert-warning">
            {characters.length === 0 ? (
              <>
                <strong>You have no linked character yet.</strong> Rewards are
                handed to a character in game, so link one first —{' '}
                <Link to="/characters">claim a character</Link> while you are
                online on the server.
              </>
            ) : (
              <>
                <strong>None of your characters is online.</strong> Rewards are
                handed over in game, so log into the server as one of them and
                the send button here will wake up. This page keeps checking.
              </>
            )}
          </div>
        )}

        {loading ? (
          <div className="d-flex flex-column gap-2" aria-hidden="true">
            {[0, 1, 2].map((n) => (
              <div key={n} className="bg-body-tertiary rounded" style={{ height: '3rem' }}></div>
            ))}
          </div>
        ) : inventory.length === 0 ? (
          <div className="text-center py-4">
            <p className="text-body-secondary">Nothing here yet — open a crate to win rewards.</p>
            {boxes.length > 0 && (
              <button className="btn btn-danger" onClick={() => handleOpen(boxes[0])}>
                Open a crate
              </button>
            )}
          </div>
        ) : (
          <div className="d-flex flex-column gap-2">
            {inventory.map((item) => {
              const status = STATUS[item.status] || { label: item.status, badge: 'secondary' };
              const deadline = item.expires_at && item.status === 'held'
                ? expiresIn(item.expires_at)
                : null;
              const canSend = item.status === 'held' || item.status === 'failed';
              return (
                <div key={item.id} className="card">
                  <div className="card-body d-flex flex-wrap align-items-center gap-3 py-2">
                    {item.reward?.icon && (
                      <img
                        src={item.reward.icon}
                        alt=""
                        style={{ width: 32, height: 32, objectFit: 'contain' }}
                      />
                    )}
                    <div className="flex-grow-1" style={{ minWidth: '10rem' }}>
                      <div>{item.reward?.name || `Reward #${item.reward_id}`}</div>
                      {deadline && (
                        <div className={`small ${deadline.urgent ? 'text-danger' : 'text-body-secondary'}`}>
                          {deadline.text}
                        </div>
                      )}
                    </div>
                    <span className={`badge text-bg-${status.badge}`}>{status.label}</span>
                    {canSend && (
                      <button
                        className="btn btn-sm btn-danger"
                        onClick={() => handleSend(item)}
                        disabled={!targetValid || busy === item.id}
                        title={targetValid ? undefined : 'Pick an online character first'}
                      >
                        {busy === item.id
                          ? 'Sending…'
                          : item.reward?.kind === 'usable' ? 'Activate' : 'Send'}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {reveal && (
        <CrateReveal
          items={reveal.items}
          size={reveal.size}
          onClose={() => setReveal(null)}
        />
      )}
    </section>
  );
}

export default Rewards;
