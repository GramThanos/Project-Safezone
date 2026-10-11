// The account's coins as a wallet: the balance, and the ways to get more.
//
// Shown in the shop's side column and on the profile, so both explain earning
// the same way. Reads `usePlayer().coins`, which is loaded with the navbar's
// counts, so it costs no request of its own. Renders nothing while coins are off
// or for a banned account.
import React from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { usePlayer } from '../context/PlayerContext';
import Coins, { coinWord } from './Coins';

// One line per way of earning: selling back, then every source that pays.
export function WaysToEarn({ className = '' }) {
	const { coins } = usePlayer();
	const sources = coins.sources || [];
	return (
		<ul className={`list-unstyled small mb-0 d-flex flex-column gap-1 ${className}`}>
			<li className="d-flex gap-2">
				<i className="fas fa-recycle fa-fw text-body-secondary mt-1" aria-hidden="true"></i>
				<span>
					Sell rewards you do not need from your <Link to="/rewards">inventory</Link>
				</span>
			</li>
			{sources.map((s) => (
				<li key={s.key} className="d-flex gap-2">
					<i className="fas fa-skull fa-fw text-body-secondary mt-1" aria-hidden="true"></i>
					<span>
						{s.coins} {coinWord(s.coins)} for every {s.per} {s.label} by a{' '}
						<Link to="/characters">linked character</Link>
					</span>
				</li>
			))}
		</ul>
	);
}

// `compact` drops the heading and the links, for the shop, which is where the
// links lead anyway.
function CoinWallet({ compact = false, className = '' }) {
	const { user } = useAuth();
	const { coins } = usePlayer();
	// A banned account cannot spend or earn, so there is nothing to show it.
	if (!coins.enabled || user?.role === 'banned') return null;

	return (
		<div className={`card coin-wallet ${className}`}>
			<div className="card-body">
				{!compact && <h5 className="card-title font-display mb-3">Coins</h5>}
				<div className="small text-body-secondary text-uppercase">Balance</div>
				<div className="coin-wallet-balance fw-bold mb-3">
					<Coins amount={coins.balance} />
				</div>
				<div className="small fw-semibold mb-2">How to earn</div>
				<WaysToEarn />
				{!compact && (
					<div className="d-flex flex-wrap gap-2 mt-3">
						<Link className="btn btn-sm btn-warning" to="/shop">
							<i className="fas fa-store me-1" aria-hidden="true"></i>Open the shop
						</Link>
					</div>
				)}
			</div>
		</div>
	);
}

export default CoinWallet;
