// Picking who receives a reward, asked at the moment of sending.
//
// Only characters the game currently reports online can receive anything, so
// that is the whole list. The roster is re-read on open: the page's copy can be
// a minute old, and a player who just logged in is exactly who clicks Send.
import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { usePlayer } from '../context/PlayerContext';

const LAST_TARGET_KEY = 'safezone.lastSendTarget';

const readLast = () => {
	try {
		return localStorage.getItem(LAST_TARGET_KEY) || '';
	} catch {
		return '';
	}
};

// `max` is how many the stack holds. Above one, the player picks how many of
// them go; it starts at all of them, which is what a send used to do.
function SendRewardModal({ title, actionLabel, max = 1, busy = false, onSend, onCancel }) {
	const { onlineCharacters, characters, refreshCharacters } = usePlayer();
	const [target, setTarget] = useState(readLast);
	const [amount, setAmount] = useState(String(max));
	const [checking, setChecking] = useState(true);
	const cancelRef = useRef(null);

	useEffect(() => {
		let cancelled = false;
		Promise.resolve(refreshCharacters()).finally(() => {
			if (!cancelled) setChecking(false);
		});
		return () => { cancelled = true; };
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	useEffect(() => {
		cancelRef.current?.focus();
		const onKey = (e) => { if (e.key === 'Escape' && !busy) onCancel(); };
		document.addEventListener('keydown', onKey);
		return () => document.removeEventListener('keydown', onKey);
	}, [onCancel, busy]);

	// A remembered choice can go stale; with only one option there is no choice.
	const targetValid = onlineCharacters.some((c) => String(c.id) === String(target));
	useEffect(() => {
		if (!targetValid && onlineCharacters.length === 1) {
			setTarget(String(onlineCharacters[0].id));
		}
	}, [targetValid, onlineCharacters]);

	// Kept as typed text so the field can be cleared while editing; it only has
	// to be a whole number in range by the time it is sent.
	const count = Number(amount);
	const amountValid = Number.isInteger(count) && count >= 1 && count <= max;
	const step = (by) => setAmount(String(Math.min(max, Math.max(1, (amountValid ? count : max) + by))));

	const send = () => {
		if (!targetValid || !amountValid) return;
		try {
			localStorage.setItem(LAST_TARGET_KEY, String(target));
		} catch {
			// pass
		}
		onSend(target, count);
	};

	return (
		<div
			className="modal show d-block"
			style={{ backgroundColor: 'rgba(0,0,0,.6)' }}
			onClick={() => { if (!busy) onCancel(); }}
			role="dialog"
			aria-modal="true"
			aria-labelledby="send-reward-title"
		>
			<div className="modal-dialog modal-dialog-centered" onClick={(e) => e.stopPropagation()}>
				<div className="modal-content">
					<div className="modal-header">
						<h5 className="modal-title font-display" id="send-reward-title">{title}</h5>
					</div>
					<div className="modal-body">
						{checking && onlineCharacters.length === 0 ? (
							<div className="text-center py-3">
								<div className="spinner-border spinner-border-sm text-danger" role="status">
									<span className="visually-hidden">Checking who is online…</span>
								</div>
							</div>
						) : onlineCharacters.length === 0 ? (
							characters.length === 0 ? (
								<p className="mb-0">
									Rewards are handed to a character in game, and you have none
									linked yet. <Link to="/characters">Claim a character</Link> while
									you are online on the server.
								</p>
							) : (
								<p className="mb-0">
									None of your characters is online right now. Log into the server
									as one of them and try again.
								</p>
							)
						) : (
							<>
								<p className="text-body-secondary small">Who should receive it?</p>
								<div className="list-group">
									{onlineCharacters.map((c) => (
										<label
											key={c.id}
											className={`list-group-item list-group-item-action d-flex align-items-center gap-2 ${
												String(c.id) === String(target) ? 'active' : ''
											}`}
										>
											<input
												type="radio"
												className="form-check-input mt-0"
												name="send-target"
												value={c.id}
												checked={String(c.id) === String(target)}
												onChange={(e) => setTarget(e.target.value)}
											/>
											<i className="fas fa-circle text-success small"></i>
											{c.in_game_username}
										</label>
									))}
								</div>
								{max > 1 && (
									<div className="mt-3">
										<label htmlFor="send-amount" className="form-label text-body-secondary small">
											How many? You have {max}.
										</label>
										<div className="input-group" style={{ maxWidth: '16rem' }}>
											<button
												type="button"
												className="btn btn-outline-secondary"
												aria-label="One fewer"
												onClick={() => step(-1)}
												disabled={busy || (amountValid && count <= 1)}
											>
												<i className="fas fa-minus"></i>
											</button>
											<input
												id="send-amount"
												type="number"
												className={`form-control text-center ${amountValid ? '' : 'is-invalid'}`}
												min={1}
												max={max}
												step={1}
												value={amount}
												onChange={(e) => setAmount(e.target.value)}
												disabled={busy}
											/>
											<button
												type="button"
												className="btn btn-outline-secondary"
												aria-label="One more"
												onClick={() => step(1)}
												disabled={busy || (amountValid && count >= max)}
											>
												<i className="fas fa-plus"></i>
											</button>
											<button
												type="button"
												className="btn btn-outline-secondary"
												onClick={() => setAmount(String(max))}
												disabled={busy || count === max}
											>
												All
											</button>
										</div>
										{!amountValid && (
											<div className="text-danger small mt-1">Pick a number from 1 to {max}.</div>
										)}
									</div>
								)}
							</>
						)}
					</div>
					<div className="modal-footer">
						<button
							ref={cancelRef}
							className="btn btn-outline-secondary"
							onClick={onCancel}
							disabled={busy}
						>
							Cancel
						</button>
						{onlineCharacters.length > 0 && (
							<button className="btn btn-danger" onClick={send} disabled={busy || !targetValid || !amountValid}>
								{busy ? 'Sending…' : (max > 1 && amountValid ? `${actionLabel} ${count}` : actionLabel)}
							</button>
						)}
					</div>
				</div>
			</div>
		</div>
	);
}

export default SendRewardModal;
