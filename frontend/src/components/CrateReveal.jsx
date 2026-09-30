// Opening a crate — a slot-machine reveal.
//
// The reel rolls through the box's *real* loot pool (fetched from the public
// odds endpoint) and decelerates onto whatever the server actually drew, so the
// animation is honest: every icon that flies past is something the box could
// have given, and the one it lands on is the one you got. A multi-draw box gets
// one reel per item, spun in a short stagger. Reduced-motion skips straight to
// the result.
import React, { useState, useEffect, useLayoutEffect, useRef } from 'react';
import api from '../services/api';

const VISIBLE = 3;          // reward cells across the reel window
const CENTER = 1;           // index of the centered cell within the window
const STRIP_LEN = 36;       // cells the reel scrolls through before landing
const WIN_INDEX = STRIP_LEN - 2; // where the won reward is locked into the strip
const SPIN_MS = 2600;       // one reel's spin duration
const STAGGER_MS = 420;     // gap between successive reels starting
const CELL_FALLBACK = 104;  // px cell width before the viewport is measured
const CELL_H = 128;         // px reel height

const prefersReducedMotion = () =>
	typeof window !== 'undefined'
	&& window.matchMedia
	&& window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const rewardName = (r, id) => (r && r.name) || `Reward #${id}`;

// How many of an item a draw delivers. It lives on the box's loot pool entry,
// so the same item can be worth three in one box and one in another — showing
// only the name made a five-bandage drop look identical to a single one.
const qty = (n) => (n && n > 1 ? n : null);

// One cell in a reel: an icon (or a fallback glyph) with the reward name under.
function Cell({ reward, rewardId, count, width }) {
	const n = qty(count);
	return (
		<div
			className="flex-shrink-0 d-flex flex-column align-items-center justify-content-center px-1"
			style={{ width, height: CELL_H }}
		>
			<div className="position-relative">
				{reward && reward.icon ? (
					<img
						src={reward.icon}
						alt=""
						style={{ width: 52, height: 52, objectFit: 'contain' }}
					/>
				) : (
					<i className="fas fa-box-open fa-2x text-body-secondary"></i>
				)}
				{n && (
					<span className="badge text-bg-light text-dark position-absolute bottom-0 end-0">
						×{n}
					</span>
				)}
			</div>
			<div className="small text-truncate w-100 text-center mt-1" style={{ maxWidth: width }}>
				{rewardName(reward, rewardId)}
			</div>
		</div>
	);
}

// A single spinning reel for one won item. It measures its own viewport so the
// cell size and the landing offset are correct on any screen width.
function Reel({ won, pool, index, skip, onLanded }) {
	const viewportRef = useRef(null);
	const [cellW, setCellW] = useState(0);
	const [offset, setOffset] = useState(0);      // px the strip has scrolled
	const [animating, setAnimating] = useState(false);
	const landedRef = useRef(false);

	// Build the strip once. Fillers are drawn from the real pool; if the pool is
	// unknown we fall back to repeating the won reward so the reel still spins.
	const stripRef = useRef(null);
	if (stripRef.current === null) {
		const winCell = { reward: won.reward, reward_id: won.reward_id, count: won.count };
		const source = (pool && pool.length) ? pool : [winCell];
		const cells = [];
		for (let i = 0; i < STRIP_LEN; i += 1) {
			cells.push(source[Math.floor(Math.random() * source.length)]);
		}
		cells[WIN_INDEX] = winCell;
		stripRef.current = cells;
	}

	const land = () => {
		if (landedRef.current) return;
		landedRef.current = true;
		onLanded();
	};

	const measure = () => {
		const w = viewportRef.current ? viewportRef.current.offsetWidth : 0;
		return w > 0 ? w / VISIBLE : CELL_FALLBACK;
	};

	useLayoutEffect(() => {
		const cw = measure();
		setCellW(cw);
		const finalOffset = (WIN_INDEX - CENTER) * cw;
		// Start each reel after a stagger so they land in sequence, not at once.
		const id = setTimeout(() => {
			setAnimating(true);
			setOffset(finalOffset);
		}, 140 + index * STAGGER_MS);
		return () => clearTimeout(id);
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	// Clicking through fast-forwards: jump to the landing spot with no transition.
	useEffect(() => {
		if (!skip || landedRef.current) return;
		const cw = cellW || CELL_FALLBACK;
		setAnimating(false);
		setOffset((WIN_INDEX - CENTER) * cw);
		land();
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [skip]);

	// A phone turned sideways changes the cell size, and the offset is in
	// pixels. Re-fit and land rather than finish the spin on a stale target.
	// Width only: a mobile address bar hiding fires resize with a new height.
	useEffect(() => {
		let lastW = viewportRef.current ? viewportRef.current.offsetWidth : 0;
		const onResize = () => {
			const w = viewportRef.current ? viewportRef.current.offsetWidth : 0;
			if (!w || w === lastW) return;
			lastW = w;
			const cw = measure();
			setCellW(cw);
			setAnimating(false);
			setOffset((WIN_INDEX - CENTER) * cw);
			land();
		};
		window.addEventListener('resize', onResize);
		return () => window.removeEventListener('resize', onResize);
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	const width = cellW || CELL_FALLBACK;

	return (
		<div className="position-relative mx-auto w-100" style={{ maxWidth: VISIBLE * 140 }}>
			{/* The strip is taken out of flow on purpose. In flow, its 36 cells
			    count toward the modal's minimum width (the centered dialog is a
			    flex row), and on a phone that pushed the modal past the screen. */}
			<div
				ref={viewportRef}
				className="position-relative overflow-hidden rounded bg-body-tertiary border"
				style={{ width: '100%', height: CELL_H }}
			>
				<div
					className="d-flex position-absolute top-0 start-0"
					style={{
						transform: `translateX(-${offset}px)`,
						transition: animating ? `transform ${SPIN_MS}ms cubic-bezier(.11,.67,.16,1)` : 'none',
						willChange: 'transform'
					}}
					onTransitionEnd={land}
				>
					{stripRef.current.map((cell, i) => (
						<Cell
							key={i}
							reward={cell.reward}
							rewardId={cell.reward_id}
							count={cell.count}
							width={width}
						/>
					))}
				</div>
			</div>
			{/* The window marker: frames whatever sits in the centre cell. */}
			<div
				className="position-absolute top-0 bottom-0 start-50 translate-middle-x rounded border border-2 border-danger"
				style={{ width, pointerEvents: 'none' }}
				aria-hidden="true"
			></div>
		</div>
	);
}

function CrateReveal({ items, boxId, boxName, onClose }) {
	const reduced = prefersReducedMotion();
	const closeRef = useRef(null);
	const [pool, setPool] = useState(null);       // reward-cell array, or [] once resolved
	const [landed, setLanded] = useState(0);
	const [skip, setSkip] = useState(false);

	const total = items.length;
	const done = reduced || landed >= total;

	// Fetch the box's real loot pool so the reel rolls through genuine
	// possibilities. Public endpoint, no token. Any failure just means the reel
	// falls back to the won rewards — the reveal still works.
	useEffect(() => {
		let cancelled = false;
		if (total === 0) { setPool([]); return undefined; }
		(async () => {
			try {
				const data = await api.boxes.odds();
				let contents = null;
				for (const ev of (data.events || [])) {
					const box = (ev.boxes || []).find((b) => b.id === boxId);
					if (box) { contents = box.contents; break; }
				}
				if (!cancelled) {
					setPool((contents || []).map((c) => ({
						reward: c.reward, reward_id: c.reward.id, count: c.count
					})));
				}
			} catch (err) {
				console.error('Load box odds error:', err);
				if (!cancelled) setPool([]);
			}
		})();
		return () => { cancelled = true; };
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [boxId, total]);

	useEffect(() => {
		closeRef.current?.focus();
		const onKey = (e) => { if (e.key === 'Escape') onClose(); };
		document.addEventListener('keydown', onKey);
		return () => document.removeEventListener('keydown', onKey);
	}, [onClose]);

	// Clicking the backdrop skips ahead while spinning, and closes once landed.
	const onBackdrop = () => {
		if (done) onClose();
		else setSkip(true);
	};

	return (
		<div
			className="modal show d-block"
			style={{ backgroundColor: 'rgba(0,0,0,.75)' }}
			onClick={onBackdrop}
			role="dialog"
			aria-modal="true"
			aria-label="Crate contents"
		>
			<div className="modal-dialog modal-dialog-centered" onClick={(e) => e.stopPropagation()}>
				<div className="modal-content text-center">
					<div className="modal-body py-4">
						<div className="text-body-secondary text-uppercase small font-display mb-1">
							{boxName ? `${boxName} crate` : 'Crate'} opened
						</div>

						{total === 0 ? (
							<p className="mb-0 mt-3">
								This crate was empty - its loot pool has nothing active in it.
								Worth telling an admin.
							</p>
						) : reduced ? (
							// Reduced motion: no reel, just the results.
							<>
								<h4 className="font-display mb-3">
									{total === 1 ? 'You got' : `You got ${total} things`}
								</h4>
								<div className="d-flex flex-column gap-2" aria-live="polite">
									{items.map((item) => (
										<div
											key={item.id}
											className="d-flex align-items-center gap-3 border rounded p-2 text-start"
										>
											{item.reward?.icon ? (
												<img src={item.reward.icon} alt="" style={{ width: 40, height: 40, objectFit: 'contain' }} />
											) : (
												<i className="fas fa-box-open fa-lg text-body-secondary" style={{ width: 40 }}></i>
											)}
											<div>
												<div className="fw-bold">
													{rewardName(item.reward, item.reward_id)}
													{qty(item.count) && (
														<span className="badge text-bg-light text-dark ms-2">
															×{item.count}
														</span>
													)}
												</div>
												<div className="small text-body-secondary">
													{item.reward?.kind === 'usable'
														? 'Activate it on a character in game'
														: 'Send it to a character in game'}
												</div>
											</div>
										</div>
									))}
								</div>
							</>
						) : pool === null ? (
							// Brief pause while the pool loads, so the first spin has real symbols.
							<div className="py-5">
								<div className="spinner-border text-danger" role="status">
									<span className="visually-hidden">Opening…</span>
								</div>
							</div>
						) : (
							<>
								<h4 className="font-display mb-3">
									{done
										? (total === 1 ? 'You got' : `You got ${total} things`)
										: 'Rolling…'}
								</h4>
								<div className="d-flex flex-column gap-3">
									{items.map((item, i) => (
										<Reel
											key={item.id}
											won={item}
											pool={pool}
											index={i}
											skip={skip}
											onLanded={() => setLanded((n) => n + 1)}
										/>
									))}
								</div>
								<div className="mt-3" style={{ minHeight: '1.5rem' }} aria-live="polite">
									{done ? (
										<div className="small text-body-secondary">
											{items.length === 1 && items[0].reward?.kind === 'usable'
												? 'Activate it on a character in game.'
												: 'Send it to a character in game.'}
										</div>
									) : (
										<p className="text-body-secondary small mb-0">Click to skip</p>
									)}
								</div>
							</>
						)}
					</div>
					<div className="modal-footer justify-content-center">
						<button ref={closeRef} className="btn btn-danger" onClick={onClose} disabled={!done}>
							{total === 0 ? 'Close' : 'Take it'}
						</button>
					</div>
				</div>
			</div>
		</div>
	);
}

export default CrateReveal;
