// Shop: spend coins on rewards.
//
// What is bought lands in the inventory on the Rewards page and is sent from
// there like anything won from a crate - the shop only takes the coins. Every
// purchase carries the price the player saw, so a price changed in the meantime
// is refused rather than charged.
import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { usePlayer } from '../context/PlayerContext';
import { useToast } from '../context/ToastContext';
import { useDialog } from '../context/DialogContext';
import api from '../services/api';
import Coins, { coinWord } from '../components/Coins';
import usePageTitle from '../hooks/usePageTitle';

function Shop() {
  usePageTitle('Shop');
  const { token } = useAuth();
  const { coins, setBalance } = usePlayer();
  const { push } = useToast();
  const { confirm } = useDialog();
  const navigate = useNavigate();

  const [categories, setCategories] = useState([]);
  const [active, setActive] = useState(null);
  const [closed, setClosed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [buying, setBuying] = useState(null);
  const [expiryDays, setExpiryDays] = useState(0);

  useEffect(() => {
    loadShop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadShop = async () => {
    try {
      const data = await api.shop.get(token);
      const list = data.categories || [];
      setCategories(list);
      setActive((current) => (list.some((c) => c.id === current) ? current : list[0]?.id ?? null));
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

  const buy = async (item) => {
    const name = item.reward.name;
    const what = item.count > 1 ? `${item.count} × ${name}` : name;
    if (!(await confirm({
      title: 'Buy this?',
      message: `${what} for ${item.price} ${coinWord(item.price)}. It goes to your `
        + 'inventory, ready to send to a character that is online.'
        + (expiryDays > 0 ? ` Send it within ${expiryDays} day${expiryDays === 1 ? '' : 's'}, or it expires.` : '')
        + (item.left_today !== null ? ` You can buy this ${item.left_today - 1} more time${item.left_today - 1 === 1 ? '' : 's'} today after this.` : ''),
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

  const shown = categories.find((c) => c.id === active);

  return (
    <section className="py-5" style={{ minHeight: '50vh' }}>
      <div className="container">
        <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
          <h2 className="text-uppercase font-display mb-0">Shop</h2>
          {!closed && <Coins amount={coins.balance} className="fs-5 fw-semibold" />}
        </div>
        {!closed && (
          <p className="text-body-secondary">
            Sell rewards you do not need from your{' '}
            <Link to="/rewards">inventory</Link>
            {coins.kills && (
              <>
                , or earn {coins.kills.coins} {coinWord(coins.kills.coins)} for every{' '}
                {coins.kills.kills} zombies a linked character kills
              </>
            )}
            . Bought rewards wait in your inventory until you send them.
          </p>
        )}

        {error && <div className="alert alert-danger">{error}</div>}

        {loading ? (
          <div className="row g-3" aria-hidden="true">
            {[0, 1, 2, 3].map((n) => (
              <div key={n} className="col-6 col-md-3">
                <div className="bg-body-tertiary rounded" style={{ height: '11rem' }}></div>
              </div>
            ))}
          </div>
        ) : closed ? (
          <div className="text-center py-5">
            <i className="fas fa-store-slash fa-2x text-body-secondary mb-3"></i>
            <p className="text-body-secondary mb-0">The shop is closed right now.</p>
          </div>
        ) : categories.length === 0 ? (
          <p className="text-body-secondary">Nothing is for sale yet. Check back soon.</p>
        ) : (
          <>
            {categories.length > 1 && (
              <ul className="nav nav-pills mb-3 flex-nowrap overflow-auto" role="tablist">
                {categories.map((c) => (
                  <li key={c.id} className="nav-item">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={c.id === active}
                      className={`nav-link text-nowrap${c.id === active ? ' active' : ''}`}
                      onClick={() => setActive(c.id)}
                    >
                      {c.name}
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {shown && (
              <>
                {shown.description && <p className="text-body-secondary">{shown.description}</p>}
                <div className="row g-3">
                  {shown.items.map((item) => {
                    const short = item.price - coins.balance;
                    const soldOut = item.left_today === 0;
                    return (
                      <div key={item.id} className="col-6 col-md-3">
                        <div className="card text-center h-100">
                          <div className="card-body d-flex flex-column align-items-center">
                            {item.reward.icon ? (
                              <img
                                src={item.reward.icon}
                                alt=""
                                style={{ width: 48, height: 48, objectFit: 'contain' }}
                                className="mb-2"
                              />
                            ) : (
                              <i className={`fas ${item.reward.kind === 'usable' ? 'fa-bolt' : 'fa-gift'} fa-2x mb-2`}></i>
                            )}
                            <div className="fw-semibold mb-1">
                              {item.reward.name}
                              {item.count > 1 && (
                                <span className="badge text-bg-light text-dark ms-1">×{item.count}</span>
                              )}
                            </div>
                            {item.reward.description && (
                              <div className="small text-body-secondary mb-2">{item.reward.description}</div>
                            )}
                            <Coins amount={item.price} className="fw-semibold mt-auto" />
                            <div className="small text-body-secondary mb-2">
                              {item.daily_limit
                                ? `${item.left_today} of ${item.daily_limit} left today`
                                : <>&nbsp;</> /* keeps the cards level */}
                            </div>
                            <button
                              className="btn btn-sm btn-warning w-100"
                              onClick={() => buy(item)}
                              disabled={buying !== null || short > 0 || soldOut}
                              title={soldOut ? 'Bought as many as allowed today'
                                : short > 0 ? `You need ${short} more ${coinWord(short)}` : undefined}
                            >
                              {buying === item.id ? 'Buying…'
                                : soldOut ? 'Back tomorrow'
                                  : short > 0 ? `Need ${short} more` : 'Buy'}
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}

            <p className="small text-body-secondary mt-4 mb-0">
              <i className="fas fa-circle-info me-1" aria-hidden="true"></i>
              {expiryDays > 0
                ? `Bought rewards expire ${expiryDays} day${expiryDays === 1 ? '' : 's'} after you buy them if they are not sent to a character, and expired rewards are not refunded.`
                : 'Bought rewards do not expire - they wait in your inventory until you send them.'}
              {' '}Sending needs a linked character that is online in game.
            </p>
          </>
        )}
      </div>
    </section>
  );
}

export default Shop;
