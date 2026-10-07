// How each linked character is doing at earning coins: what has been paid for,
// how far the next coin is, and when the game's numbers were last read.
//
// Earnings come from the server's save, which the game writes every few
// minutes, so nothing here is live - and the box says so, rather than letting
// a player wonder why the zombie they killed a moment ago is not counted yet.
import React, { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { usePlayer } from '../context/PlayerContext';
import api from '../services/api';
import Coins, { coinWord } from './Coins';
import { formatDateTime, parseDate } from '../utils/dates';

const ago = (iso) => {
	if (!iso) return null;
	const minutes = Math.round((Date.now() - parseDate(iso).getTime()) / 60000);
	if (minutes < 1) return 'just now';
	if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
	const hours = Math.round(minutes / 60);
	if (hours < 48) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
	return formatDateTime(iso);
};

function CoinProgress() {
	const { token } = useAuth();
	const { coins, refreshCounts } = usePlayer();
	const [data, setData] = useState(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState('');

	const load = useCallback(async () => {
		setLoading(true);
		try {
			setData(await api.coins.characters(token));
			setError('');
			// A check may have paid something; the badges should know.
			refreshCounts();
		} catch (err) {
			setError(err.message || 'Could not load your coin progress');
		}
		setLoading(false);
	}, [token, refreshCounts]);

	useEffect(() => {
		if (coins.enabled) load();
	}, [coins.enabled, load]);

	if (!coins.enabled) return null;

	const sources = data?.sources || [];
	const characters = data?.characters || [];

	return (
		<div className="card mt-4">
			<div className="card-header d-flex flex-wrap align-items-center gap-2">
				<span className="fw-semibold me-auto">
					<i className="fas fa-coins text-warning me-2" aria-hidden="true"></i>Coins from playing
				</span>
				<Coins amount={coins.balance} className="fw-semibold" />
				<button type="button" className="btn btn-sm btn-outline-secondary" onClick={load} disabled={loading}>
					<i className={`fas fa-rotate${loading ? ' fa-spin' : ''} me-1`} aria-hidden="true"></i>
					Check now
				</button>
			</div>
			<div className="card-body">
				{error && <div className="alert alert-danger py-2">{error}</div>}

				{sources.length > 0 ? (
					<p className="mb-3">
						{sources.map((s, i) => (
							<span key={s.key}>
								{i > 0 && ' and '}
								<strong>{s.coins} {coinWord(s.coins)}</strong> for every <strong>{s.per}</strong> {s.label}
							</span>
						))}
						{' '}by a linked character.
					</p>
				) : data && (
					<p className="mb-3 text-body-secondary">Playing does not earn coins right now.</p>
				)}

				{!data && loading ? (
					<div className="bg-body-tertiary rounded" style={{ height: '3rem' }} aria-hidden="true"></div>
				) : characters.length === 0 ? (
					<p className="text-body-secondary">Link a character above to start earning.</p>
				) : (
					<ul className="list-group mb-3">
						{characters.map((c) => (
							<li key={c.id} className="list-group-item">
								<div className="d-flex flex-wrap justify-content-between gap-2">
									<span className="fw-semibold">{c.in_game_username}</span>
									<span className="small text-body-secondary">
										Earned <Coins amount={c.earned} /> so far
									</span>
								</div>
								{c.sources.map((s) => (
									<div key={s.key} className="small mt-1">
										{s.seen === null ? (
											<span className="text-body-secondary">
												Not read yet - the game has not saved this character since it was linked.
											</span>
										) : (
											<>
												{s.seen.toLocaleString()} {s.label} in this life
												{s.to_next !== null && (
													<>
														{' · '}
														{s.to_next === 0
															? <strong>a coin is due at the next check</strong>
															: <><strong>{s.to_next}</strong> more for the next coin</>}
													</>
												)}
											</>
										)}
									</div>
								))}
								<div className="small text-body-secondary mt-1">
									{c.checked_at ? `Checked ${ago(c.checked_at)}` : 'Not checked yet'}
									{c.saved_at && ` · from the game's save of ${formatDateTime(c.saved_at)}`}
								</div>
							</li>
						))}
					</ul>
				)}

				<div className="small text-body-secondary">
					<i className="fas fa-circle-info me-1" aria-hidden="true"></i>
					Kills are read from the server's save, which the game writes every few minutes and
					when you log out, so new kills can take a while to count. Characters are checked
					when you open this page
					{data?.next_check_at
						? <>, and all of them together once a day - next around {formatDateTime(data.next_check_at)}.</>
						: '.'}
					{' '}Kills from before a character was linked never count, and when a character dies
					its replacement starts again from zero.
					{data?.daily_report && ' Each day you get a message with what you earned the day before.'}
				</div>
			</div>
		</div>
	);
}

export default CoinProgress;
