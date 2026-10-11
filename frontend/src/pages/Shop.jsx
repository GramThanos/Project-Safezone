// Shop: spend coins on rewards.
//
// What is bought lands in the inventory on the Rewards page and is sent from
// there like anything won from a crate - the shop only takes the coins. Every
// purchase carries the price the player saw, so a price changed in the meantime
// is refused rather than charged.
//
// Laid out as a storefront: the wallet and the sections down the side (a strip
// of chips above the grid below `lg`), a search and a sort over whatever is
// shown. The section is kept in the URL (`?c=<id>`) by the category's id - never
// its name, which admins decorate with emoji - so a section can be linked to
// and survives a reload. "All" lists every section in turn, each listing once.
import React, { useState, useEffect, useMemo } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { usePlayer } from '../context/PlayerContext';
import { useToast } from '../context/ToastContext';
import { useDialog } from '../context/DialogContext';
import api from '../services/api';
import Coins, { coinWord } from '../components/Coins';
import CoinWallet from '../components/CoinWallet';
import usePageTitle from '../hooks/usePageTitle';

const ALL = 'all';

const SORTS = {
  featured: { label: 'Featured', compare: null },
  'price-asc': { label: 'Price: low to high', compare: (a, b) => a.price - b.price },
  'price-desc': { label: 'Price: high to low', compare: (a, b) => b.price - a.price },
  name: { label: 'Name', compare: (a, b) => a.reward.name.localeCompare(b.reward.name) }
};

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

function ItemCard({ item, balance, busy, buying, onBuy }) {
  const short = item.price - balance;
  const soldOut = item.left_today === 0;
  const unavailable = soldOut || short > 0;

  return (
    <div className={`card h-100 shop-card${unavailable ? ' is-unavailable' : ''}`}>
      <div className="shop-card-media">
        {item.reward.icon ? (
          <img src={item.reward.icon} alt="" loading="lazy" />
        ) : (
          <i className={`fas ${item.reward.kind === 'usable' ? 'fa-bolt' : 'fa-gift'}`} aria-hidden="true"></i>
        )}
        {item.count > 1 && (
          <span className="badge text-bg-dark border shop-card-count">×{item.count}</span>
        )}
        {item.daily_limit && (
          <span className={`badge shop-card-limit ${soldOut ? 'text-bg-secondary' : 'text-bg-dark border'}`}>
            {soldOut ? 'Sold out today' : `${item.left_today} of ${item.daily_limit} left today`}
          </span>
        )}
      </div>
      <div className="card-body pb-2">
        <h3 className="h6 fw-semibold mb-1">{item.reward.name}</h3>
        {item.reward.description && (
          <p className="small text-body-secondary mb-0 shop-card-desc" title={item.reward.description}>
            {item.reward.description}
          </p>
        )}
      </div>
      <div className="card-footer bg-transparent border-0 pt-0 d-flex flex-wrap align-items-center gap-2">
        <Coins amount={item.price} className={`fs-5 fw-bold${short > 0 ? ' text-body-secondary' : ''}`} />
        <button
          type="button"
          className="btn btn-sm btn-warning ms-auto"
          onClick={() => onBuy(item)}
          disabled={busy || unavailable}
          title={soldOut ? 'Bought as many as allowed today'
            : short > 0 ? `You need ${short} more ${coinWord(short)}` : undefined}
        >
          {buying ? 'Buying…'
            : soldOut ? 'Back tomorrow'
              : short > 0 ? `Need ${short.toLocaleString()} more` : 'Buy'}
        </button>
      </div>
    </div>
  );
}

function Shop() {
  usePageTitle('Shop');
  const { token } = useAuth();
  const { coins, setBalance } = usePlayer();
  const { push } = useToast();
  const { confirm } = useDialog();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();

  const [categories, setCategories] = useState([]);
  const [closed, setClosed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [buying, setBuying] = useState(null);
  const [expiryDays, setExpiryDays] = useState(0);
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('featured');

  useEffect(() => {
    loadShop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadShop = async () => {
    try {
      const data = await api.shop.get(token);
      setCategories(data.categories || []);
      setBalance(data.balance);
      setExpiryDays(data.expiry_days || 0);
      setClosed(false);
      setError('');
    } catch (err) {
      if (err.status === 404) setClosed(true);
      else setError('Could not load the shop. Try again in a moment.');
    }
    setLoading(false);
  };

  // With one section there is nothing to choose between, and "All" would only
  // repeat it under a second name.
  const sectioned = categories.length > 1;
  const requested = Number(params.get('c'));
  const active = !sectioned
    ? categories[0]?.id ?? ALL
    : categories.some((c) => c.id === requested) ? requested : ALL;

  const choose = (id) => {
    // Replace rather than push: back leaves the shop instead of stepping
    // through every section looked at.
    setParams(id === ALL ? {} : { c: String(id) }, { replace: true });
  };

  // What the grid shows: one group per section, searched and sorted. In "All"
  // a listing in several sections appears under the first of them only.
  const groups = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const matches = (item) => !needle
      || item.reward.name.toLocaleLowerCase().includes(needle)
      || (item.reward.description || '').toLocaleLowerCase().includes(needle);
    const compare = SORTS[sort]?.compare;
    const seen = new Set();
    return categories
      .filter((c) => active === ALL || c.id === active)
      .map((c) => {
        let items = c.items.filter((item) => {
          if (seen.has(item.id) || !matches(item)) return false;
          seen.add(item.id);
          return true;
        });
        if (compare) items = [...items].sort(compare);
        return { ...c, items };
      })
      .filter((c) => c.items.length > 0);
  }, [categories, active, query, sort]);

  const shownCount = groups.reduce((n, g) => n + g.items.length, 0);
  const totalCount = useMemo(
    () => new Set(categories.flatMap((c) => c.items.map((item) => item.id))).size,
    [categories]
  );
  const current = categories.find((c) => c.id === active);

  const buy = async (item) => {
    const name = item.reward.name;
    const what = item.count > 1 ? `${item.count} × ${name}` : name;
    if (!(await confirm({
      title: 'Buy this?',
      message: `${what} for ${item.price} ${coinWord(item.price)}. It goes to your `
        + 'inventory, ready to send to a character that is online.'
        + (expiryDays > 0 ? ` Send it within ${plural(expiryDays, 'day')}, or it expires.` : '')
        + (item.left_today !== null ? ` You can buy this ${plural(item.left_today - 1, 'more time')} today after this.` : ''),
      confirmLabel: `Buy for ${item.price}`,
      danger: false
    }))) return;

    setBuying(item.id);
    try {
      const data = await api.shop.buy(token, item.id, item.price);
      setBalance(data.balance);
      push(`${what} is in your inventory.`, {
        kind: 'success',
        action: { label: 'Send it', onClick: () => navigate('/rewards') }
      });
      // A daily limit just moved; the cards should say so.
      if (item.daily_limit) loadShop();
    } catch (err) {
      push(err.message || 'That purchase did not go through.', { kind: 'error' });
      if (typeof err.data?.balance === 'number') setBalance(err.data.balance);
      // The listing changed under the player, or a limit was reached: show
      // them what it is now.
      if (err.status === 404 || err.status === 409) loadShop();
    }
    setBuying(null);
  };

  const grid = (items) => (
    <div className="row row-cols-2 row-cols-md-3 row-cols-xl-4 g-3">
      {items.map((item) => (
        <div key={item.id} className="col">
          <ItemCard
            item={item}
            balance={coins.balance}
            busy={buying !== null}
            buying={buying === item.id}
            onBuy={buy}
          />
        </div>
      ))}
    </div>
  );

  const header = (
    <div className="mb-4">
      <h2 className="text-uppercase font-display mb-1">Shop</h2>
      <p className="text-body-secondary mb-0">
        Spend your coins on rewards. What you buy waits in your{' '}
        <Link to="/rewards">inventory</Link> until you send it to a character.
      </p>
    </div>
  );

  if (loading) {
    return (
      <section className="py-5" style={{ minHeight: '50vh' }}>
        <div className="container">
          {header}
          <div className="row g-4" aria-hidden="true">
            <div className="col-lg-3 d-none d-lg-block">
              <div className="bg-body-tertiary rounded" style={{ height: '16rem' }}></div>
            </div>
            <div className="col-lg-9">
              <div className="row row-cols-2 row-cols-md-3 row-cols-xl-4 g-3">
                {[0, 1, 2, 3, 4, 5, 6, 7].map((n) => (
                  <div key={n} className="col">
                    <div className="bg-body-tertiary rounded" style={{ height: '15rem' }}></div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>
    );
  }

  if (closed) {
    return (
      <section className="py-5" style={{ minHeight: '50vh' }}>
        <div className="container">
          {header}
          <div className="text-center py-5">
            <i className="fas fa-store-slash fa-2x text-body-secondary mb-3" aria-hidden="true"></i>
            <p className="text-body-secondary mb-0">The shop is closed right now.</p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="py-5" style={{ minHeight: '50vh' }}>
      <div className="container">
        {header}
        {error && <div className="alert alert-danger">{error}</div>}

        <div className="row g-4">
          {/* Side column: the wallet and the sections */}
          <aside className="col-lg-3 d-none d-lg-block">
            <div className="shop-aside d-flex flex-column gap-3">
              <CoinWallet compact />
              {sectioned && (
                <nav aria-label="Shop sections">
                  <div className="small text-body-secondary text-uppercase fw-semibold mb-2 px-1">Sections</div>
                  <div className="list-group shop-sections">
                    {[{ id: ALL, name: 'All items', count: totalCount }]
                      .concat(categories.map((c) => ({ id: c.id, name: c.name, count: c.items.length })))
                      .map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          className={`list-group-item list-group-item-action d-flex align-items-center gap-2${s.id === active ? ' active' : ''}`}
                          aria-current={s.id === active ? 'true' : undefined}
                          onClick={() => choose(s.id)}
                        >
                          <span className="text-truncate me-auto" title={s.name}>{s.name}</span>
                          <span className="badge rounded-pill text-bg-dark border">{s.count}</span>
                        </button>
                      ))}
                  </div>
                </nav>
              )}
            </div>
          </aside>

          <div className="col-lg-9">
            {/* Below lg: a slim wallet bar and a strip of section chips */}
            <div className="d-lg-none mb-3">
              <div className="d-flex align-items-center justify-content-between border rounded px-3 py-2 mb-3 bg-body-tertiary">
                <span className="small text-body-secondary text-uppercase">Balance</span>
                <Coins amount={coins.balance} className="fs-5 fw-bold" />
              </div>
              {sectioned && (
                <div className="shop-chips nav nav-pills flex-nowrap gap-2" role="tablist" aria-label="Shop sections">
                  {[{ id: ALL, name: 'All' }].concat(categories).map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      role="tab"
                      aria-selected={c.id === active}
                      className={`nav-link text-nowrap${c.id === active ? ' active' : ''}`}
                      onClick={() => choose(c.id)}
                    >
                      {c.name}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {categories.length === 0 ? (
              <div className="text-center py-5">
                <i className="fas fa-box-open fa-2x text-body-secondary mb-3" aria-hidden="true"></i>
                <p className="text-body-secondary mb-0">Nothing is for sale yet. Check back soon.</p>
              </div>
            ) : (
              <>
                {/* Toolbar: what is shown, and how to narrow it */}
                <div className="d-flex flex-wrap align-items-end gap-2 mb-3">
                  <div className="me-auto">
                    <h3 className="h4 font-display mb-0">{current ? current.name : 'All items'}</h3>
                    <div className="small text-body-secondary">
                      {query.trim() ? `${plural(shownCount, 'item')} found` : plural(shownCount, 'item')}
                    </div>
                  </div>
                  <div className="input-group input-group-sm shop-search">
                    <span className="input-group-text"><i className="fas fa-magnifying-glass" aria-hidden="true"></i></span>
                    <input
                      type="search"
                      className="form-control"
                      placeholder="Search the shop"
                      aria-label="Search the shop"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                    />
                  </div>
                  <select
                    className="form-select form-select-sm w-auto"
                    aria-label="Sort by"
                    value={sort}
                    onChange={(e) => setSort(e.target.value)}
                  >
                    {Object.entries(SORTS).map(([key, s]) => (
                      <option key={key} value={key}>{s.label}</option>
                    ))}
                  </select>
                </div>
                {current?.description && <p className="text-body-secondary">{current.description}</p>}

                {groups.length === 0 ? (
                  <div className="text-center py-5">
                    <i className="fas fa-magnifying-glass fa-2x text-body-secondary mb-3" aria-hidden="true"></i>
                    <p className="text-body-secondary mb-2">Nothing here matches “{query.trim()}”.</p>
                    <button type="button" className="btn btn-sm btn-outline-light" onClick={() => setQuery('')}>
                      Clear the search
                    </button>
                  </div>
                ) : active === ALL && sectioned ? (
                  <div className="d-flex flex-column gap-4">
                    {groups.map((g) => (
                      <section key={g.id} aria-labelledby={`shop-section-${g.id}`}>
                        <div className="d-flex align-items-baseline gap-2 mb-2">
                          <h4 id={`shop-section-${g.id}`} className="h5 font-display mb-0 me-auto text-truncate">{g.name}</h4>
                          <button type="button" className="btn btn-link btn-sm p-0 text-nowrap" onClick={() => choose(g.id)}>
                            See section <i className="fas fa-chevron-right small" aria-hidden="true"></i>
                          </button>
                        </div>
                        {grid(g.items)}
                      </section>
                    ))}
                  </div>
                ) : (
                  grid(groups[0].items)
                )}
              </>
            )}

            <p className="small text-body-secondary mt-4 mb-0">
              <i className="fas fa-circle-info me-1" aria-hidden="true"></i>
              {expiryDays > 0
                ? `Bought rewards expire ${plural(expiryDays, 'day')} after you buy them if they are not sent to a character, and expired rewards are not refunded.`
                : 'Bought rewards do not expire - they wait in your inventory until you send them.'}
              {' '}Sending needs a linked character that is online in game.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

export default Shop;
