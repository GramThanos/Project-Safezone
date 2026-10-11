// Admin › Shop: the categories players browse, and the listings shown in them.
//
// A listing is a reward from the catalog, how many of it one purchase gives, a
// price, an optional daily limit per player, and the categories it appears in -
// as many as fit. Listings are edited in a dialog and saved with its Save
// button, so a half-made change never reaches the shop. The price fills itself
// in at 20 × the reward's sell value until the admin types in it; the server
// refuses anything below the sell value itself, so buying and selling back can
// never make coins. Moderators can look; admins can change.
import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useDialog } from '../../context/DialogContext';
import api from '../../services/api';
import { RewardIcon, Spinner } from './helpers';
import Coins from '../../components/Coins';
import RewardPickerModal from '../../components/RewardPickerModal';
import { downloadJson, readJsonFile } from '../../utils/jsonTransfer';

// Mirrors the server (`coins.min_price` / `coins.suggested_price`): a reward
// sells for its coin value once, whatever the count.
const floorPrice = (reward) => Math.max(1, reward?.coin_value || 0);
const suggestedPrice = (reward, multiplier) => Math.max(1, multiplier * (reward?.coin_value || 0));

const wholeNumber = (text) => (/^\d+$/.test(String(text).trim()) ? Number(text) : null);

const emptyListing = { reward: null, count: '1', price: '', daily_limit: '', sort_order: '0',
  active: true, category_ids: [] };

const formFromListing = (item) => ({
  reward: item.reward,
  count: String(item.count),
  price: String(item.price),
  daily_limit: item.daily_limit ? String(item.daily_limit) : '',
  sort_order: String(item.sort_order || 0),
  active: item.active,
  category_ids: item.category_ids || []
});

// Create or edit one listing. Nothing is sent until Save.
function ListingModal({ item, categories, multiplier, onSave, onClose }) {
  const editing = Boolean(item);
  const [form, setForm] = useState(() => (item ? formFromListing(item) : { ...emptyListing }));
  // A new listing's price follows the reward until the admin types one; an
  // existing listing's price is the admin's already.
  const [priceTouched, setPriceTouched] = useState(editing);
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !picking) onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, picking]);

  const set = (patch) => setForm((current) => ({ ...current, ...patch }));
  const isUsable = form.reward?.kind === 'usable';

  const chooseReward = (reward) => set({
    reward,
    count: reward.kind === 'usable' ? '1' : form.count,
    ...(priceTouched ? {} : { price: String(suggestedPrice(reward, multiplier)) })
  });

  const toggleCategory = (id) => set({
    category_ids: form.category_ids.includes(id)
      ? form.category_ids.filter((x) => x !== id)
      : [...form.category_ids, id]
  });

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    const count = isUsable ? 1 : wholeNumber(form.count);
    const price = wholeNumber(form.price);
    const limit = form.daily_limit.trim() === '' ? null : wholeNumber(form.daily_limit);
    const order = Number(form.sort_order.trim() || 0);
    if (!form.reward) return setError('Choose a reward.');
    if (!count || count > 1000) return setError('The count must be a whole number from 1 to 1000.');
    if (price === null || price < floorPrice(form.reward)) {
      return setError(`The price must be at least ${floorPrice(form.reward)}, what the reward sells back for.`);
    }
    if (form.daily_limit.trim() !== '' && (!limit || limit > 1000)) {
      return setError('The daily limit must be empty, or a whole number from 1 to 1000.');
    }
    if (!Number.isInteger(order)) return setError('The order must be a whole number.');
    setBusy(true);
    try {
      await onSave({
        reward_id: form.reward.id, count, price, daily_limit: limit, sort_order: order,
        active: form.active, category_ids: form.category_ids
      });
      onClose();
    } catch (err) {
      setError(err.message || 'The listing was not saved');
      setBusy(false);
    }
  };

  const tooLow = form.reward && wholeNumber(form.price) !== null
    && wholeNumber(form.price) < floorPrice(form.reward);

  return (
    <>
      <div className="modal show d-block" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }} onClick={onClose}>
        <div className="modal-dialog modal-dialog-centered modal-lg" onClick={(e) => e.stopPropagation()}>
          <form className="modal-content" onSubmit={submit}>
            <div className="modal-header">
              <h5 className="modal-title font-display">{editing ? 'Edit listing' : 'New listing'}</h5>
              <button type="button" className="btn-close" aria-label="Close" onClick={onClose}></button>
            </div>
            <div className="modal-body">
              {error && <div className="alert alert-danger" role="alert">{error}</div>}

              <label className="form-label text-body-secondary small mb-1">Reward</label>
              <div className="d-flex align-items-center gap-3 border rounded p-2 mb-3">
                {form.reward ? (
                  <>
                    <RewardIcon reward={form.reward} size={32} />
                    <span className="flex-grow-1">
                      <span className="fw-semibold">{form.reward.name}</span>
                      <span className="d-block small text-body-secondary">
                        {isUsable ? 'Action' : form.reward.in_game_id} · sells back for{' '}
                        <Coins amount={form.reward.coin_value} />
                      </span>
                    </span>
                  </>
                ) : <span className="flex-grow-1 text-body-secondary">No reward chosen</span>}
                <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => setPicking(true)}>
                  <i className="fas fa-magnifying-glass me-1"></i>{form.reward ? 'Change' : 'Choose'}
                </button>
              </div>

              <div className="row g-2">
                <div className="col-6 col-md-3">
                  <label className="form-label text-body-secondary small mb-1" htmlFor="listing-count">Count</label>
                  <input id="listing-count" type="number" min="1" max="1000" className="form-control"
                    value={isUsable ? '1' : form.count} disabled={isUsable}
                    title={isUsable ? 'An action is delivered once' : undefined}
                    onChange={(e) => set({ count: e.target.value })} />
                </div>
                <div className="col-6 col-md-3">
                  <label className="form-label text-body-secondary small mb-1" htmlFor="listing-price">
                    Price {form.reward && <span className="text-body-tertiary">(min {floorPrice(form.reward)})</span>}
                  </label>
                  <input id="listing-price" type="number" min="1"
                    className={`form-control${tooLow ? ' is-invalid' : ''}`} value={form.price}
                    onChange={(e) => { set({ price: e.target.value }); setPriceTouched(true); }} />
                </div>
                <div className="col-6 col-md-3">
                  <label className="form-label text-body-secondary small mb-1" htmlFor="listing-limit">
                    Daily limit
                  </label>
                  <input id="listing-limit" type="number" min="1" max="1000" className="form-control"
                    placeholder="No limit" value={form.daily_limit}
                    onChange={(e) => set({ daily_limit: e.target.value })} />
                </div>
                <div className="col-6 col-md-3">
                  <label className="form-label text-body-secondary small mb-1" htmlFor="listing-order">Order</label>
                  <input id="listing-order" type="number" className="form-control" value={form.sort_order}
                    onChange={(e) => set({ sort_order: e.target.value })} />
                </div>
                <div className="col-12 form-text mt-0">
                  The price starts at {multiplier}× what the reward sells back for. The daily limit is
                  how many times one player may buy this a day; leave it empty for no limit.
                </div>

                <div className="col-12 mt-3">
                  <label className="form-label text-body-secondary small mb-1">Shown in</label>
                  {categories.length === 0 ? (
                    <div className="text-body-secondary small">
                      No categories yet. Create one first; a listing in no category is not shown to players.
                    </div>
                  ) : (
                    <div className="d-flex flex-wrap gap-3">
                      {categories.map((c) => (
                        <div key={c.id} className="form-check">
                          <input className="form-check-input" type="checkbox" id={`listing-cat-${c.id}`}
                            checked={form.category_ids.includes(c.id)}
                            onChange={() => toggleCategory(c.id)} />
                          <label className="form-check-label" htmlFor={`listing-cat-${c.id}`}>
                            {c.name}{!c.active && <span className="text-body-secondary"> (hidden)</span>}
                          </label>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="col-12 mt-2">
                  <div className="form-check">
                    <input className="form-check-input" type="checkbox" id="listing-active"
                      checked={form.active} onChange={(e) => set({ active: e.target.checked })} />
                    <label className="form-check-label" htmlFor="listing-active">Shown in the shop</label>
                  </div>
                </div>
                {form.reward && !form.reward.active && (
                  <div className="col-12 form-text text-warning">
                    This reward is inactive, so players will not see the listing until it is switched on.
                  </div>
                )}
              </div>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn btn-outline-secondary" onClick={onClose}>Cancel</button>
              <button type="submit" className="btn btn-danger" disabled={busy}>
                {busy ? 'Saving…' : 'Save'}
              </button>
            </div>
          </form>
        </div>
      </div>
      {picking && (
        <RewardPickerModal
          title="Choose the reward to sell"
          onSelect={chooseReward}
          onClose={() => setPicking(false)}
        />
      )}
    </>
  );
}

function Shop() {
  const { token, isAdmin } = useAuth();
  const { confirm, prompt } = useDialog();
  const admin = isAdmin();
  const [shop, setShop] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [filter, setFilter] = useState('');
  // false = closed; null = creating; a listing = editing it.
  const [editing, setEditing] = useState(false);
  const [transferBusy, setTransferBusy] = useState(false);
  const importInput = useRef(null);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    try {
      setShop(await api.admin.shop.get(token));
    } catch (err) {
      console.error('Load shop error:', err);
      setError('Failed to load the shop');
    }
    setLoading(false);
  };

  // Every change reports through the same notice/error pair and reloads, so
  // what is shown is always what the server holds.
  const run = async (action, success) => {
    setError('');
    setNotice('');
    try {
      await action();
      if (success) setNotice(success);
    } catch (err) {
      console.error('Shop change error:', err);
      setError(err.message || 'That change was not saved');
    }
    await loadData();
  };

  const categoryFields = (category) => [
    { name: 'name', label: 'Name', initial: category?.name || '', required: true },
    { name: 'description', label: 'Description (optional)', initial: category?.description || '' },
    { name: 'sort_order', label: 'Order (lower comes first)', initial: String(category?.sort_order ?? 0) }
  ];

  const categoryPayload = (answer) => {
    const order = Number(answer.sort_order.trim() || 0);
    if (!Number.isInteger(order)) throw new Error('The order must be a whole number');
    return { name: answer.name.trim(), description: answer.description.trim(), sort_order: order };
  };

  const addCategory = async () => {
    const answer = await prompt({ title: 'New category', confirmLabel: 'Save', fields: categoryFields(null) });
    if (!answer) return;
    run(() => api.admin.shop.createCategory(token, categoryPayload(answer)), `Category "${answer.name.trim()}" created.`);
  };

  const editCategory = async (category) => {
    const answer = await prompt({ title: 'Edit category', confirmLabel: 'Save', fields: categoryFields(category) });
    if (!answer) return;
    run(() => api.admin.shop.updateCategory(token, category.id, categoryPayload(answer)));
  };

  const toggleCategory = (category) => run(
    () => api.admin.shop.updateCategory(token, category.id, { active: !category.active })
  );

  const deleteCategory = async (category) => {
    if (!(await confirm({
      title: 'Delete category?',
      message: `Delete "${category.name}"? Its ${category.listings} listing(s) stay in any other `
        + 'categories they are in; one left in none is no longer shown.',
      confirmLabel: 'Delete'
    }))) return;
    run(() => api.admin.shop.deleteCategory(token, category.id), `Category "${category.name}" deleted.`);
  };

  // Throws, so the listing dialog can show the error over its own fields.
  const saveListing = async (payload) => {
    if (editing) await api.admin.shop.updateItem(token, editing.id, payload);
    else await api.admin.shop.createItem(token, payload);
    setNotice(editing ? 'Listing saved.' : 'Listed.');
    await loadData();
  };

  const deleteListing = async (item) => {
    if (!(await confirm({
      title: 'Remove listing?',
      message: `Take ${item.reward?.name || 'this reward'} out of the shop? Anything already bought stays bought.`,
      confirmLabel: 'Remove'
    }))) return;
    run(() => api.admin.shop.deleteItem(token, item.id));
  };

  const rewardKey = (reward) => reward?.kind === 'item'
    ? `item:${reward.in_game_id || ''}` : `usable:${String(reward?.name || '').trim().toLowerCase()}`;

  const exportShop = () => {
    const categoryNames = Object.fromEntries((shop?.categories || []).map((category) => [category.id, category.name]));
    const rewards = new Map();
    (shop?.items || []).forEach((item) => {
      if (item.reward) rewards.set(rewardKey(item.reward), item.reward);
    });
    downloadJson({
      type: 'project-safezone-shop', version: 1,
      // Include the reward definitions as well as the listings. A shop preset
      // is then portable on its own instead of silently skipping listings whose
      // rewards have not yet been created on the destination server.
      rewards: [...rewards.values()].map(({ kind, name, description, icon, in_game_id, commands, active, coin_value }) =>
        ({ kind, name, description, icon, in_game_id, commands, active, coin_value })),
      categories: (shop?.categories || []).map(({ name, description, sort_order, active }) =>
        ({ name, description, sort_order, active })),
      items: (shop?.items || []).map((item) => ({
        reward: {
          kind: item.reward?.kind, name: item.reward?.name, in_game_id: item.reward?.in_game_id
        },
        count: item.count, price: item.price, daily_limit: item.daily_limit,
        sort_order: item.sort_order, active: item.active,
        categories: (item.category_ids || []).map((id) => categoryNames[id]).filter(Boolean)
      }))
    }, 'project-safezone-shop.json');
  };

  const importShop = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setError('');
    setNotice('');
    try {
      const data = await readJsonFile(file);
      if (data?.type !== 'project-safezone-shop' || data.version !== 1
          || !Array.isArray(data.categories) || !Array.isArray(data.items)) {
        throw new Error('Choose a Project Safezone shop export file.');
      }
      if ((data.rewards !== undefined && !Array.isArray(data.rewards))
          || data.categories.length > 100 || data.items.length > 500
          || (data.rewards || []).length > 500) {
        throw new Error('The import contains too many categories or listings.');
      }
      setTransferBusy(true);
      const catalog = await api.admin.rewards.search(token, { limit: 500 });
      const existingRewards = new Map((catalog.rewards || []).map((reward) => [rewardKey(reward), reward]));
      const incomingRewards = new Set();
      let addedRewards = 0;
      let addedIcons = 0;
      for (const reward of data.rewards || []) {
        const key = rewardKey(reward);
        const existing = existingRewards.get(key);
        // Presets created before icons were bundled left empty icon fields.
        // Fill only that blank field; never overwrite an administrator's chosen
        // image, description, sell value, or enabled state.
        if (existing) {
          if (!existing.icon && reward.icon) {
            await api.admin.rewards.update(token, existing.id, { icon: reward.icon });
            addedIcons += 1;
          }
          continue;
        }
        if (incomingRewards.has(key)) continue;
        await api.admin.rewards.create(token, reward);
        incomingRewards.add(key);
        addedRewards += 1;
      }
      let current = shop;
      const categoryByName = new Map((current?.categories || []).map((category) => [category.name.toLowerCase(), category]));
      let addedCategories = 0;
      for (const category of data.categories) {
        if (!category || typeof category.name !== 'string' || !category.name.trim()) {
          throw new Error('Each imported category needs a name.');
        }
        const key = category.name.trim().toLowerCase();
        if (!categoryByName.has(key)) {
          const result = await api.admin.shop.createCategory(token, category);
          categoryByName.set(key, result.category);
          addedCategories += 1;
        }
      }
      current = await api.admin.shop.get(token);
      const freshCategories = new Map(current.categories.map((category) => [category.name.toLowerCase(), category.id]));
      const listed = new Set(current.items.map((item) => rewardKey(item.reward)));
      const refreshedCatalog = await api.admin.rewards.search(token, { limit: 500 });
      const rewardsByKey = new Map((refreshedCatalog.rewards || []).map((reward) => [rewardKey(reward), reward]));
      let addedListings = 0;
      let skipped = 0;
      for (const item of data.items) {
        const key = rewardKey(item.reward || {});
        if (listed.has(key)) { skipped += 1; continue; }
        const reward = rewardsByKey.get(key);
        if (!reward) { skipped += 1; continue; }
        const category_ids = (item.categories || []).map((name) => freshCategories.get(String(name).toLowerCase()))
          .filter((id) => id !== undefined);
        await api.admin.shop.createItem(token, {
          reward_id: reward.id, count: item.count, price: item.price,
          daily_limit: item.daily_limit, sort_order: item.sort_order,
          active: item.active, category_ids
        });
        listed.add(key);
        addedListings += 1;
      }
      await loadData();
      setNotice(`Imported ${addedRewards} reward(s), ${addedIcons} icon${addedIcons === 1 ? '' : 's'}, ${addedCategories} categor${addedCategories === 1 ? 'y' : 'ies'} and ${addedListings} listing(s)`
        + (skipped ? `; skipped ${skipped} already present or missing its reward.` : '.'));
    } catch (err) {
      setError(err.message || 'Could not import the shop.');
    } finally {
      setTransferBusy(false);
    }
  };

  if (loading) return <Spinner />;
  const categories = shop?.categories || [];
  const items = shop?.items || [];
  const multiplier = shop?.price_multiplier || 20;
  const nameOf = Object.fromEntries(categories.map((c) => [c.id, c]));
  const shown = filter === '' ? items
    : filter === 'none' ? items.filter((i) => (i.category_ids || []).length === 0)
      : items.filter((i) => (i.category_ids || []).includes(Number(filter)));

  return (
    <>
      <div className="d-flex flex-wrap justify-content-between align-items-baseline gap-2">
        <h4 className="font-display mb-1">Shop</h4>
        {admin && (
          <div className="d-flex gap-2">
            <input ref={importInput} type="file" accept="application/json,.json" className="d-none"
              onChange={importShop} />
            <button className="btn btn-sm btn-outline-secondary" onClick={() => importInput.current?.click()} disabled={transferBusy}>
              <i className="fas fa-upload me-1"></i> Import
            </button>
            <button className="btn btn-sm btn-outline-secondary" onClick={exportShop} disabled={transferBusy}>
              <i className="fas fa-download me-1"></i> Export
            </button>
          </div>
        )}
      </div>
      <p className="text-body-secondary">
        What players can buy with coins. A price cannot be lower than what the reward
        sells back for; new listings start at {multiplier}× that. Export JSON to move
        this configuration between servers; a shop import includes its required reward definitions.
      </p>

      {shop && !shop.enabled && (
        <div className="alert alert-warning">
          Coins are switched off, so players cannot see the shop.
          {admin && <> Turn them on in <Link to="/admin/settings">Settings</Link>.</>}
        </div>
      )}
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      {notice && <div className="alert alert-success" role="alert">{notice}</div>}

      <div className="card mb-4">
        <div className="card-header d-flex align-items-center">
          <span className="fw-semibold me-auto">
            <i className="fas fa-folder-open me-2"></i>Categories
            <span className="badge text-bg-secondary ms-2">{categories.length}</span>
          </span>
          {admin && (
            <button className="btn btn-sm btn-danger" onClick={addCategory}>
              <i className="fas fa-plus me-1"></i> Add category
            </button>
          )}
        </div>
        {categories.length === 0 ? (
          <div className="card-body text-body-secondary">
            No categories yet.{admin && ' Add one, then list rewards in it.'}
          </div>
        ) : (
          <div className="table-responsive">
            <table className="table table-sm align-middle mb-0">
              <thead>
                <tr>
                  <th>Name</th>
                  <th style={{ width: '5rem' }}>Order</th>
                  <th style={{ width: '6rem' }}>Listings</th>
                  <th style={{ width: '5rem' }}>Shown</th>
                  {admin && <th style={{ width: '8rem' }}></th>}
                </tr>
              </thead>
              <tbody>
                {categories.map((c) => (
                  <tr key={c.id} className={c.active ? '' : 'text-body-secondary'}>
                    <td>
                      <span className="fw-semibold">{c.name}</span>
                      {c.description && <div className="small text-body-secondary">{c.description}</div>}
                    </td>
                    <td>{c.sort_order}</td>
                    <td>{c.listings}</td>
                    <td>{c.active ? 'Yes' : 'Hidden'}</td>
                    {admin && (
                      <td className="text-end">
                        <div className="btn-group btn-group-sm">
                          <button className="btn btn-outline-secondary" title="Edit" onClick={() => editCategory(c)}>
                            <i className="fas fa-pen"></i>
                          </button>
                          <button className="btn btn-outline-secondary" onClick={() => toggleCategory(c)}
                            title={c.active ? 'Hide from players' : 'Show to players'}>
                            <i className={`fas ${c.active ? 'fa-eye-slash' : 'fa-eye'}`}></i>
                          </button>
                          <button className="btn btn-outline-danger" title="Delete" onClick={() => deleteCategory(c)}>
                            <i className="fas fa-trash"></i>
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-header d-flex flex-wrap align-items-center gap-2">
          <span className="fw-semibold me-auto">
            <i className="fas fa-tags me-2"></i>Listings
            <span className="badge text-bg-secondary ms-2">{items.length}</span>
          </span>
          <select className="form-select form-select-sm w-auto" value={filter}
            onChange={(e) => setFilter(e.target.value)} aria-label="Show listings in">
            <option value="">All categories</option>
            {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            <option value="none">In no category</option>
          </select>
          {admin && (
            <button className="btn btn-sm btn-danger" onClick={() => setEditing(null)}>
              <i className="fas fa-plus me-1"></i> Add listing
            </button>
          )}
        </div>
        {shown.length === 0 ? (
          <div className="card-body text-body-secondary">Nothing listed here.</div>
        ) : (
          <div className="table-responsive">
            <table className="table table-sm table-hover align-middle mb-0">
              <thead>
                <tr>
                  <th>Reward</th>
                  <th style={{ width: '5rem' }}>Count</th>
                  <th style={{ width: '6rem' }}>Price</th>
                  <th style={{ width: '6rem' }} title="What the reward sells back for">Sells for</th>
                  <th style={{ width: '6rem' }}>Per day</th>
                  <th>Categories</th>
                  <th style={{ width: '5rem' }} title="Times bought, all time">Sold</th>
                  <th style={{ width: '5rem' }}>Shown</th>
                  {admin && <th style={{ width: '6rem' }}></th>}
                </tr>
              </thead>
              <tbody>
                {shown.map((item) => {
                  const visible = item.active && item.reward?.active
                    && (item.category_ids || []).some((id) => nameOf[id]?.active);
                  return (
                    <tr key={item.id} className={visible ? '' : 'text-body-secondary'}>
                      <td>
                        <span className="d-inline-flex align-items-center gap-2">
                          <RewardIcon reward={item.reward} size={24} />
                          {item.reward?.name || `Reward #${item.reward_id}`}
                          {item.reward && !item.reward.active && (
                            <span className="badge text-bg-secondary" title="The reward itself is inactive">inactive</span>
                          )}
                        </span>
                      </td>
                      <td>×{item.count}</td>
                      <td><Coins amount={item.price} /></td>
                      <td><Coins amount={item.reward?.coin_value} className="text-body-secondary" /></td>
                      <td>{item.daily_limit || '—'}</td>
                      <td>
                        {(item.category_ids || []).length === 0
                          ? <span className="badge text-bg-warning">none</span>
                          : item.category_ids.map((id) => (
                            <span key={id} className="badge text-bg-secondary me-1">{nameOf[id]?.name || id}</span>
                          ))}
                      </td>
                      <td>{item.sold}</td>
                      <td>{visible ? 'Yes' : 'No'}</td>
                      {admin && (
                        <td className="text-end">
                          <div className="btn-group btn-group-sm">
                            <button className="btn btn-outline-secondary" title="Edit" onClick={() => setEditing(item)}>
                              <i className="fas fa-pen"></i>
                            </button>
                            <button className="btn btn-outline-danger" title="Remove from the shop"
                              onClick={() => deleteListing(item)}>
                              <i className="fas fa-trash"></i>
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {admin && editing !== false && (
        <ListingModal
          item={editing}
          categories={categories}
          multiplier={multiplier}
          onSave={saveListing}
          onClose={() => setEditing(false)}
        />
      )}
    </>
  );
}

export default Shop;
