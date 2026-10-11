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

// How many bundles one send may carry, until the server says otherwise.
const SEND_MAX = { item: 20, usable: 5 };

// What one bundle holds. A usable runs once, whatever its row says.
const perBundle = (item) => (item.reward?.kind === 'usable' ? 1 : (item.count || 1));

// How a number of bundles reads: "Bandage", "Bandage ×5", "3 × Bandage ×5".
// The number after the name is what one bundle holds and the one before it is
// how many bundles - the same words the server uses in its messages, because
// three drops of five bandages are not one drop of fifteen.
const bundleLabel = (reward, per, n = 1) => {
  const name = `${reward?.name || 'Reward'}${per > 1 ? ` ×${per}` : ''}`;
  return n > 1 ? `${n} × ${name}` : name;
};

// Soonest deadline first, then oldest: the order bundles are sent and sold in,
// so what stays behind is what lasts longest.
const bySoonest = (a, b) => {
  if (a.expires_at && b.expires_at) {
    const diff = parseDate(a.expires_at) - parseDate(b.expires_at);
    if (diff) return diff;
  } else if (a.expires_at || b.expires_at) {
    return a.expires_at ? -1 : 1;
  }
  return a.id - b.id;
};

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
  const [sendMax, setSendMax] = useState(SEND_MAX);
  const [sending, setSending] = useState(null);       // the group whose send modal is open
  const [discarding, setDiscarding] = useState(null); // the group whose next bundle awaits a sell/discard confirm
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
      if (data.send_max) setSendMax(data.send_max);
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
  // One toast per delivery and outcome, not per bundle - a stack of five sent
  // together is one thing to the player, and a delivery that stopped part-way
  // says both what arrived and what came back.
  const [wasSending, setWasSending] = useState([]);
  useEffect(() => {
    const sending = new Set(inventory.filter((i) => i.status === 'sending').map((i) => i.id));
    const outcomes = new Map();
    wasSending.filter((id) => !sending.has(id)).forEach((id) => {
      const item = inventory.find((i) => i.id === id);
      if (!item) return;
      const key = `${item.task_id ?? `row${item.id}`}|${item.status}`;
      if (!outcomes.has(key)) outcomes.set(key, []);
      outcomes.get(key).push(item);
    });
    outcomes.forEach((items) => {
      const what = bundleLabel(items[0].reward, perBundle(items[0]), items.length);
      if (items[0].status === 'delivered') push(`${what} arrived in game.`, { kind: 'success' });
      else push(`${what} came back to your inventory - it could not be delivered.`, { kind: 'error' });
    });
    setWasSending([...sending]);
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

  // Stack identical bundles. Two holdings are "the same" when they are the same
  // reward, holding the same amount, in the same state - three drops of five
  // bandages are one stack of three bundles, while a drop of ten is a stack of
  // its own, because sending "one" of each means different things. Status is
  // part of the key so a delivered axe never merges with one still waiting.
  const inventoryGroups = React.useMemo(() => {
    const map = new Map();
    for (const item of inventory) {
      const per = perBundle(item);
      const key = `${item.reward_id}|${per}|${item.status}`;
      if (!map.has(key)) {
        map.set(key, {
          key, status: item.status, reward: item.reward,
          reward_id: item.reward_id, per, items: []
        });
      }
      map.get(key).items.push(item);
    }
    return Array.from(map.values()).map((group) => {
      const items = group.items.sort(bySoonest);
      // The nearest deadline, so a stack warns as early as its most urgent
      // bundle would have.
      const soonest = group.status === 'held' ? items.find((i) => i.expires_at)?.expires_at : null;
      return { ...group, bundles: items.length, soonest: soonest || null };
    });
  }, [inventory]);

  // Sends `amount` bundles out of a stack as one delivery: the soonest to
  // expire go, so what stays behind is what lasts longest. The server checks
  // every bundle before dispatching any, so it all goes or none of it does.
  const handleSendGroup = async (group, target, amount) => {
    setError('');
    setBusy(group.key);
    const what = bundleLabel(group.reward, group.per, amount);
    try {
      await api.inventory.send(token, group.items.slice(0, amount).map((i) => i.id),
        parseInt(target, 10));
      push(`Sending ${what}…`, { kind: 'info' });
    } catch (err) {
      console.error('Send items error:', err);
      push(err.message || `Could not send ${what}.`, { kind: 'error' });
    }
    setBusy(null);
    setSending(null);
    loadInventory();
    refreshCounts();
  };

  // A bundle's worth when sold, as the server worked it out. Zero when coins
  // are off or the reward has no value, and then discarding is just that.
  const sellValueOf = (item) => (coins.enabled && item ? item.sell_value || 0 : 0);

  // Selling or discarding takes one bundle - the next to expire - after a
  // confirm that says exactly which and what is left. Used and expired ones
  // are only cleared off the page, all of a stack at once, with no confirm.
  const removeItems = async (group, items) => {
    setError('');
    setBusy(`x:${group.key}`);
    try {
      const data = await api.inventory.remove(token, items.map((i) => i.id));
      const gone = new Set(items.map((i) => i.id));
      setInventory((current) => current.filter((i) => !gone.has(i.id)));
      setBalance(data.balance);
      if (data.coins > 0) {
        push(`Sold ${bundleLabel(group.reward, group.per, items.length)} for ${data.coins} ${coinWord(data.coins)}.`,
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
    else removeItems(group, group.items);
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
              const name = group.reward?.name || `Reward #${group.reward_id}`;
              const isUsable = group.reward?.kind === 'usable';
              // What goes on a sell or discard: the next bundle, never the stack.
              const next = canSend ? group.items[0] : null;
              const value = sellValueOf(next);
              const details = {
                name, per: group.per, bundles: group.bundles, kind: group.reward?.kind,
                description: group.reward?.description, sellValue: value, coinsOn: coins.enabled,
                sellable: canSend, expiresAt: group.soonest, status: group.status
              };
              const removeLabel = value > 0 ? 'Sell one' : canSend ? 'Discard one' : 'Clear';
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
                        aria-label={`${removeLabel}: ${bundleLabel(group.reward, group.per)}`}
                        title={value > 0 ? `Sell one for ${value} ${coinWord(value)}` : removeLabel}
                        onClick={() => onRemove(group)}
                        disabled={busy === `x:${group.key}`}
                      ></button>
                    )}
                    {group.bundles > 1 && (
                      <span
                        className="badge rounded-pill text-bg-danger position-absolute"
                        style={{ top: '2.25rem', right: '.5rem' }}
                        title={`You have ${group.bundles} of these`}
                      >
                        ×{group.bundles}
                      </span>
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
                      <div className="fw-semibold">{name}</div>
                      {/* The two numbers, said apart: what one holds, and how many there are. */}
                      <div className="small text-body-secondary mb-2">
                        {isUsable
                          ? (group.bundles > 1 ? `${group.bundles} uses` : 'One use')
                          : group.per > 1
                            ? (group.bundles > 1
                              ? `${group.bundles} bundles of ${group.per} · ${group.bundles * group.per} in all`
                              : `Bundle of ${group.per}`)
                            : (group.bundles > 1 ? `${group.bundles} in all` : 'Single item')}
                      </div>
                      <span className={`badge text-bg-${status.badge} mb-2`}>{status.label}</span>
                      {deadline && (
                        <div className={`small mb-2 ${deadline.urgent ? 'text-danger' : 'text-body-secondary'}`}>
                          {group.bundles > 1 ? `Next: ${deadline.text.toLowerCase()}` : deadline.text}
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
          max={sending.bundles}
          limit={sendMax[sending.reward?.kind] ?? SEND_MAX.item}
          per={sending.per}
          usable={sending.reward?.kind === 'usable'}
          itemName={sending.reward?.name || 'reward'}
          busy={busy === sending.key}
          onSend={(target, amount) => handleSendGroup(sending, target, amount)}
          onCancel={() => setSending(null)}
        />
      )}

      {discarding && (() => {
        const bundle = discarding.items[0];
        const value = sellValueOf(bundle);
        const left = discarding.bundles - 1;
        const isUsable = discarding.reward?.kind === 'usable';
        const name = discarding.reward?.name || 'this reward';
        return (
          <ConfirmDialog
            title={value > 0 ? 'Sell one?' : 'Discard one?'}
            confirmLabel={value > 0 ? `Sell for ${value} ${coinWord(value)}` : 'Discard'}
            danger={value === 0}
            busy={busy === `x:${discarding.key}`}
            onConfirm={() => removeItems(discarding, [bundle])}
            onCancel={() => setDiscarding(null)}
          >
            <div className="d-flex align-items-center gap-3 p-2 mb-3 border rounded">
              {discarding.reward?.icon
                ? <img src={discarding.reward.icon} alt="" style={{ width: 40, height: 40, objectFit: 'contain' }} />
                : <i className="fas fa-gift fa-2x"></i>}
              <div className="flex-grow-1">
                <div className="fw-semibold">{bundleLabel(discarding.reward, discarding.per)}</div>
                <div className="small text-body-secondary">
                  {isUsable ? 'One use' : discarding.per > 1 ? `One bundle of ${discarding.per} ${name}` : `One ${name}`}
                  {bundle.expires_at && ` · ${expiresIn(bundle.expires_at).text.toLowerCase()}`}
                </div>
              </div>
              {value > 0 && <Coins amount={value} className="fw-semibold" />}
            </div>
            <div>
              {value > 0
                ? `It will be removed from your inventory and you will receive ${value} ${coinWord(value)}.`
                : 'It will be thrown away.'}
              {' '}It has not been sent yet, and this cannot be undone.
            </div>
            <div className="mt-2 text-body-secondary">
              {left > 0 ? `You will still have ${left} more.` : 'It is the last one you have.'}
            </div>
          </ConfirmDialog>
        );
      })()}
    </section>
  );
}

export default Rewards;
