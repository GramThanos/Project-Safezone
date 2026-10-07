// Everything about one stack of rewards, over its card: what it is, how many,
// what it would sell for and when it runs out.
//
// Opens on hover and keyboard focus, and from the card's info button for
// touch screens, where nothing hovers. Built here rather than with Bootstrap's
// tooltip so it can carry a few lines of layout and follow React's state
// without being re-initialised on every render.
import React, { useEffect, useRef, useState } from 'react';
import Coins, { coinWord } from './Coins';
import { formatDateTime, parseDate } from '../utils/dates';

const KIND = { item: 'Item', usable: 'Action' };

function untilText(iso) {
  const ms = parseDate(iso).getTime() - Date.now();
  if (ms <= 0) return 'Expired';
  const hours = Math.floor(ms / 3600000);
  if (hours < 1) return 'Expires within the hour';
  if (hours < 48) return `Expires in ${hours} hour${hours === 1 ? '' : 's'}`;
  return `Expires in ${Math.floor(hours / 24)} days`;
}

// `details` is what the tooltip shows; `children` is the card it belongs to.
function RewardTooltip({ details, children }) {
  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const wrapper = useRef(null);
  const open = hovered || pinned;

  // A pinned tooltip closes on a tap anywhere else, or on Escape.
  useEffect(() => {
    if (!pinned) return undefined;
    const onPointer = (e) => {
      if (wrapper.current && !wrapper.current.contains(e.target)) setPinned(false);
    };
    const onKey = (e) => { if (e.key === 'Escape') setPinned(false); };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [pinned]);

  const { name, quantity, kind, description, sellValue, coinsOn, sellable, expiresAt, status } = details;

  return (
    <div
      ref={wrapper}
      className="position-relative h-100"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        type="button"
        className="btn btn-link btn-sm p-0 position-absolute top-0 start-0 m-2 text-body-secondary"
        style={{ zIndex: 2, lineHeight: 1 }}
        aria-label={`About ${name}`}
        aria-expanded={open}
        onClick={() => setPinned(!pinned)}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
      >
        <i className="fas fa-circle-info" aria-hidden="true"></i>
      </button>
      {children}
      {open && (
        <div
          role="tooltip"
          className="position-absolute start-50 translate-middle-x bg-body border rounded shadow p-3 small text-start"
          style={{ bottom: 'calc(100% + .4rem)', width: 'min(17rem, 90vw)', zIndex: 1040 }}
        >
          <div className="fw-semibold">
            {name}
            {quantity > 1 && <span className="badge text-bg-light text-dark ms-1">×{quantity}</span>}
          </div>
          <div className="text-body-secondary mb-1">{KIND[kind] || kind}</div>
          {description && <div className="mb-2">{description}</div>}
          <dl className="row g-0 mb-0">
            {coinsOn && (
              <>
                <dt className="col-5 fw-normal text-body-secondary">If sold</dt>
                <dd className="col-7 mb-1">
                  {sellValue > 0
                    ? <><Coins amount={sellValue} /> {coinWord(sellValue)}</>
                    : sellable ? 'Cannot be sold' : 'Nothing - only unsent rewards sell'}
                </dd>
              </>
            )}
            {/* Only what is still waiting can run out. */}
            {(sellable || status === 'expired') && (
              <>
                <dt className="col-5 fw-normal text-body-secondary">Expires</dt>
                <dd className="col-7 mb-0">
                  {status === 'expired' ? 'Expired'
                    : expiresAt ? <span title={formatDateTime(expiresAt)}>{untilText(expiresAt)}</span>
                      : 'Never'}
                </dd>
              </>
            )}
          </dl>
        </div>
      )}
    </div>
  );
}

export default RewardTooltip;
