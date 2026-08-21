// Opening a crate.
import React, { useState, useEffect, useRef } from 'react';

const STEP_MS = 550;

const prefersReducedMotion = () =>
	typeof window !== 'undefined'
	&& window.matchMedia
	&& window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function CrateReveal({ items, size, onClose }) {
	const reduced = prefersReducedMotion();
	const [shown, setShown] = useState(reduced ? items.length : 0);
	const closeRef = useRef(null);

	useEffect(() => {
		if (shown >= items.length) return undefined;
		const id = setTimeout(() => setShown((n) => n + 1), STEP_MS);
		return () => clearTimeout(id);
	}, [shown, items.length]);

	useEffect(() => {
		closeRef.current?.focus();
		const onKey = (e) => { if (e.key === 'Escape') onClose(); };
		document.addEventListener('keydown', onKey);
		return () => document.removeEventListener('keydown', onKey);
	}, [onClose]);

	const revealAll = () => setShown(items.length);
	const done = shown >= items.length;

	return (
		<div
			className="modal show d-block"
			style={{ backgroundColor: 'rgba(0,0,0,.75)' }}
			onClick={done ? onClose : revealAll}
			role="dialog"
			aria-modal="true"
			aria-label="Crate contents"
		>
			<div className="modal-dialog modal-dialog-centered" onClick={(e) => e.stopPropagation()}>
				<div className="modal-content text-center">
					<div className="modal-body py-4">
						<div className="text-body-secondary text-uppercase small font-display mb-1">
							{size ? `${size} crate` : 'Crate'} opened
						</div>

						{items.length === 0 ? (
							<p className="mb-0 mt-3">
								This crate was empty - its loot pool has nothing active in it.
								Worth telling an admin.
							</p>
						) : (
							<>
								<h4 className="font-display mb-3">
									{items.length === 1 ? 'You got' : `You got ${items.length} things`}
								</h4>
								<div className="d-flex flex-column gap-2" aria-live="polite">
									{items.slice(0, shown).map((item) => (
										<div
											key={item.id}
											className="d-flex align-items-center gap-3 border rounded p-2 text-start"
											style={reduced ? undefined : { animation: 'none' }}
										>
											{item.reward?.icon ? (
												<img
													src={item.reward.icon}
													alt=""
													style={{ width: 40, height: 40, objectFit: 'contain' }}
												/>
											) : (
												<i className="fas fa-box-open fa-lg text-body-secondary" style={{ width: 40 }}></i>
											)}
											<div>
												<div className="fw-bold">{item.reward?.name || `Reward #${item.reward_id}`}</div>
												<div className="small text-body-secondary">
													{item.reward?.kind === 'usable'
														? 'Activate it on a character in game'
														: 'Send it to a character in game'}
												</div>
											</div>
										</div>
									))}
								</div>
								{!done && (
									<p className="text-body-secondary small mt-3 mb-0">Click to reveal the rest</p>
								)}
							</>
						)}
					</div>
					<div className="modal-footer justify-content-center">
						<button ref={closeRef} className="btn btn-danger" onClick={onClose}>
							{items.length === 0 ? 'Close' : 'Take it'}
						</button>
					</div>
				</div>
			</div>
		</div>
	);
}

export default CrateReveal;
