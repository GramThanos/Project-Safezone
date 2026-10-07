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
import SendRewardModal from '../components/SendRewardModal';
import ConfirmDialog from '../components/ConfirmDialog';
import Coins, { coinWord } from '../components/Coins';
import RewardTooltip from '../components/RewardTooltip';
import usePageTitle from '../hooks/usePageTitle';
import { parseDate } from '../utils/dates';

// Crates are badged by where they came from, not by a fixed size.
const SOURCE_BADGE = { daily: 'secondary', custom: 'info', bonus: 'warning' };
const SOURCE_LABEL = { bonus: 'weekly bonus', custom: 'event' };

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

// A deadline is only useful if it reads like one.
const expiresIn = (iso) => {
  const ms = parseDate(iso).getTime() - Date.now();
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
  const { boxes, streak, coins, refresh, refreshCounts, setBalance } = usePlayer();

  const [inventory, setInventory] = useState([]);
  const [sending, setSending] = useState(null);       // the group whose send modal is open
  const [discarding, setDiscarding] = useState(null); // the group awaiting a discard confirm
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
      setReveal({
        items: data.items || [],
        boxId: box.box_id,
        boxName: box.label || box.box_name
      });
      await Promise.all([loadInventory(), refresh()]);
    } catch (err) {
      console.error('Open crate error:', err);
      setError(err.message || 'Could not open that crate');
    }
    setBusy(null);
  };

  const sendOne = async (itemId, characterId, count) => {
    await api.inventory.send(token, itemId, parseInt(characterId, 10), count);
  };

  // Stack identical rewards. Two items are "the same" when they are the same
  // reward in the same state — a pile of three held axes reads as one box ×3,
  // not three near-duplicate rows. Status is part of the key so a delivered
  // axe never merges with one still waiting to send.
  const inventoryGroups = React.useMemo(() => {
    const map = new Map();
    for (const item of inventory) {
      const key = `${item.reward_id}|${item.status}`;
      if (!map.has(key)) {
        map.set(key, {
          key, status: item.status, reward: item.reward,
          reward_id: item.reward_id, items: [], quantity: 0, soonest: null
        });
      }
      const group = map.get(key);
      group.items.push(item);
      // What the player actually receives, which is not the number of rows: a
      // single holding can deliver five of an item, because the quantity lives
      // on the box's loot pool entry and was captured here when the box was
      // opened. Counting rows showed five bandages as "×1".
      group.quantity += item.count || 1;
      // Surface the nearest deadline so a stack warns as early as its most
      // urgent member would have.
      if (item.expires_at && item.status === 'held'
        && (!group.soonest || parseDate(item.expires_at) < parseDate(group.soonest))) {
        group.soonest = item.expires_at;
      }
    }
    return Array.from(map.values());
  }, [inventory]);

  // How many of a holding arrive in game. A usable runs once per holding,
  // whatever its count says.
  const unitsOf = (item) => (item.reward?.kind === 'usable' ? 1 : (item.count || 1));

  // Sends `amount` units out of a stack, which may be fewer than it holds.
  // Whole holdings go first, the one that would overshoot is split (the
  // server keeps the remainder as its own row), and the soonest to expire go
  // first so what stays behind is what lasts longest. The sent part leaves
  // 'held' and reappears under 'sending'; anything that failed stays here.
  const handleSendGroup = async (group, target, amount) => {
    setError('');
    setBusy(group.key);
    const items = [...group.items].sort((a, b) => {
      if (!a.expires_at || !b.expires_at) return (a.expires_at ? -1 : 0) + (b.expires_at ? 1 : 0);
      return parseDate(a.expires_at) - parseDate(b.expires_at);
    });
    // Counted in units delivered, not holdings sent: one holding can carry
    // several of an item, and "Sending 2 × Bandage" for six bandages is wrong.
    let remaining = amount;
    let quantity = 0;
    let lastError = null;
    for (const item of items) {
      if (remaining <= 0) break;
      const units = unitsOf(item);
      const take = Math.min(units, remaining);
      try {
        await sendOne(item.id, target, take < units ? take : undefined);
        quantity += take;
      } catch (err) {
        console.error('Send item error:', err);
        lastError = err;
      }
      remaining -= take;
    }
    const name = group.reward?.name || 'your reward';
    push(quantity === amount
      ? (quantity === 1 ? `Sending ${name}…` : `Sending ${quantity} × ${name}…`)
      : quantity === 0
        ? (lastError?.message || `Could not send ${name}.`)
        : `Sent ${quantity} of ${amount} ${name}. The rest are still here.`,
    { kind: quantity === amount ? 'info' : 'error' });
    setBusy(null);
    setSending(null);
    loadInventory();
    refreshCounts();
  };

  // What a stack sells back for, as the server worked it out. Zero when coins
  // are off or the reward has no value, and then discarding is just that.
  const sellValueOf = (group) => (coins.enabled
    ? group.items.reduce((sum, item) => sum + (item.sell_value || 0), 0)
    : 0);

  // Unsent rewards are thrown away - or sold, with coins on - after a confirm;
  // used and expired ones are just cleared off the page. All the same call.
  const removeGroup = async (group) => {
    setError('');
    setBusy(`x:${group.key}`);
    try {
      const data = await api.inventory.remove(token, group.items.map((i) => i.id));
      const gone = new Set(group.items.map((i) => i.id));
      setInventory((current) => current.filter((i) => !gone.has(i.id)));
      setBalance(data.balance);
      if (data.coins > 0) {
        push(`Sold ${group.reward?.name || 'reward'} for ${data.coins} ${coinWord(data.coins)}.`,
          { kind: 'success' });
      }
    } catch (err) {
      console.error('Remove inventory error:', err);
      push(err.message || 'Could not remove that reward.', { kind: 'error' });
    }
    setBusy(null);
    setDiscarding(null);
  };

  const onRemove = (group) => {
    if (group.status === 'held' || group.status === 'failed') setDiscarding(group);
    else removeGroup(group);
  };

  return (
    <section className="py-5" style={{ minHeight: '50vh' }}>
      <div className="container">
        <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-4">
          <h2 className="text-uppercase font-display mb-0">Rewards</h2>
          {coins.enabled && (
            <div className="d-flex align-items-center gap-3">
              <Coins amount={coins.balance} className="fs-5 fw-semibold" />
              <Link className="btn btn-outline-warning btn-sm" to="/shop">
                <i className="fas fa-store me-1" aria-hidden="true"></i>Shop
              </Link>
            </div>
          )}
        </div>

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
                    ? 'Bonus crate earned this week — find it in My Crates'
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
                        <span className={`badge text-bg-${SOURCE_BADGE[box.source] || 'secondary'}`}>
                          {box.label || box.box_name || 'Crate'}
                        </span>
                        {SOURCE_LABEL[box.source] && (
                          <span className="badge text-bg-light text-dark ms-1">
                            {SOURCE_LABEL[box.source]}
                          </span>
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

        <h5 className="font-display mb-3">My Inventory</h5>

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
          <div className="row g-3">
            {inventoryGroups.map((group) => {
              const status = STATUS[group.status] || { label: group.status, badge: 'secondary' };
              const deadline = group.soonest ? expiresIn(group.soonest) : null;
              const canSend = group.status === 'held' || group.status === 'failed';
              // `holdings` is how many separate sends this button makes;
              // `quantity` is how many of the item arrive in game. They differ
              // whenever a box drops an item in multiples.
              const holdings = group.items.length;
              const name = group.reward?.name || `Reward #${group.reward_id}`;
              const isUsable = group.reward?.kind === 'usable';
              // A usable runs once per holding, so its quantity is its holdings.
              const quantity = isUsable ? holdings : group.quantity;
              const selling = canSend && sellValueOf(group) > 0;
              const details = {
                name, quantity, kind: group.reward?.kind, description: group.reward?.description,
                sellValue: canSend ? sellValueOf(group) : 0, coinsOn: coins.enabled,
                sellable: canSend, expiresAt: group.soonest, status: group.status
              };
              const removeLabel = selling ? 'Sell' : canSend ? 'Discard' : 'Clear';
              return (
                <div key={group.key} className="col-6 col-md-3">
                  <RewardTooltip details={details}>
                  <div className="card text-center h-100 position-relative">
                    {/* In flight has a task on the manager; it cannot be taken back. */}
                    {group.status !== 'sending' && (
                      <button
                        type="button"
                        className="btn-close position-absolute top-0 end-0 m-2"
                        style={{ fontSize: '.65rem' }}
                        aria-label={`${removeLabel} ${name}`}
                        title={selling ? `Sell for ${sellValueOf(group)} ${coinWord(sellValueOf(group))}` : removeLabel}
                        onClick={() => onRemove(group)}
                        disabled={busy === `x:${group.key}`}
                      ></button>
                    )}
                    <div className="card-body d-flex flex-column align-items-center">
                      {group.reward?.icon ? (
                        <img
                          src={group.reward.icon}
                          alt=""
                          style={{ width: 48, height: 48, objectFit: 'contain' }}
                          className="mb-2"
                        />
                      ) : (
                        <i className="fas fa-gift fa-2x mb-2"></i>
                      )}
                      <div className="fw-semibold mb-1">
                        {name}
                        {quantity > 1 && (
                          <span className="badge text-bg-light text-dark ms-1">×{quantity}</span>
                        )}
                      </div>
                      <span className={`badge text-bg-${status.badge} mb-2`}>{status.label}</span>
                      {deadline && (
                        <div className={`small mb-2 ${deadline.urgent ? 'text-danger' : 'text-body-secondary'}`}>
                          {deadline.text}
                        </div>
                      )}
                      {canSend && (
                        <button
                          className="btn btn-sm btn-danger w-100 mt-auto"
                          onClick={() => setSending(group)}
                          disabled={busy === group.key}
                        >
                          {busy === group.key ? 'Sending…' : isUsable ? 'Activate' : 'Send'}
                        </button>
                      )}
                    </div>
                  </div>
                  </RewardTooltip>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {reveal && (
        <CrateReveal
          items={reveal.items}
          boxId={reveal.boxId}
          boxName={reveal.boxName}
          onClose={() => setReveal(null)}
        />
      )}

      {sending && (
        <SendRewardModal
          title={`${sending.reward?.kind === 'usable' ? 'Activate' : 'Send'} ${sending.reward?.name || 'reward'}`}
          actionLabel={sending.reward?.kind === 'usable' ? 'Activate' : 'Send'}
          max={sending.items.reduce((sum, item) => sum + unitsOf(item), 0)}
          busy={busy === sending.key}
          onSend={(target, amount) => handleSendGroup(sending, target, amount)}
          onCancel={() => setSending(null)}
        />
      )}

      {discarding && (() => {
        const value = sellValueOf(discarding);
        const what = discarding.items.length > 1
          ? `All ${discarding.items.length} × ${discarding.reward?.name || 'this reward'}`
          : (discarding.reward?.name || 'This reward');
        return (
          <ConfirmDialog
            title={value > 0 ? 'Sell reward?' : 'Discard reward?'}
            confirmLabel={value > 0 ? `Sell for ${value} ${coinWord(value)}` : 'Discard'}
            danger={value === 0}
            busy={busy === `x:${discarding.key}`}
            onConfirm={() => removeGroup(discarding)}
            onCancel={() => setDiscarding(null)}
          >
            {value > 0
              ? `${what} will be removed from your inventory and you will receive ${value} ${coinWord(value)}.`
              : `${what} will be thrown away.`}
            {' '}It has not been sent yet, and this cannot be undone.
          </ConfirmDialog>
        );
      })()}
    </section>
  );
}

export default Rewards;
