// Characters management page
import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { usePlayer } from '../context/PlayerContext';
import { useToast } from '../context/ToastContext';
import api from '../services/api';
import ConfirmDialog from '../components/ConfirmDialog';
import usePageTitle from '../hooks/usePageTitle';

function Characters() {
	usePageTitle('My Characters');
	const { token } = useAuth();
	const { refresh } = usePlayer();
	const { push } = useToast();
	const [roster, setRoster] = useState([]);
	const [rosterState, setRosterState] = useState('idle'); // idle|loading|ready|error
	const [unlinking, setUnlinking] = useState(null);
	const [characters, setCharacters] = useState([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState('');
	const [showModal, setShowModal] = useState(false);
	const [editingCharacter, setEditingCharacter] = useState(null);
	const [formData, setFormData] = useState({ description: '' });
	const [servers, setServers] = useState([]);
	const [claims, setClaims] = useState([]);
	const [claimForm, setClaimForm] = useState({ server_id: '', in_game_username: '' });
	const [claimMsg, setClaimMsg] = useState('');

	useEffect(() => {
		loadCharacters();
		loadServers();
		loadClaims();
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	const loadCharacters = async () => {
		try {
			const data = await api.characters.getAll(token);
			if (data.characters) {
				setCharacters(data.characters);
			}
			setLoading(false);
		} catch (err) {
			console.error('Load characters error:', err);
			setError('Failed to load characters');
			setLoading(false);
		}
	};

	const loadServers = async () => {
		try {
			const data = await api.servers.getAll();
			if (data.servers) setServers(data.servers);
		} catch (err) {
			console.error('Load servers error:', err);
			setError('Could not load the server list. Reload to try again.');
		}
	};

	const loadClaims = async () => {
		try {
			const data = await api.claims.getMine(token);
			if (data.claims) setClaims(data.claims);
		} catch (err) {
			console.error('Load claims error:', err);
			setError('Could not load your character links. Reload to try again.');
		}
	};

	const loadRoster = async (serverId) => {
		if (!serverId) {
			setRoster([]);
			setRosterState('idle');
			return;
		}
		setRosterState('loading');
		try {
			const data = await api.servers.getOnline(token, parseInt(serverId, 10));
			setRoster(data.online || []);
			setRosterState('ready');
		} catch (err) {
			console.error('Load roster error:', err);
			setRoster([]);
			setRosterState('error');
		}
	};

	const chooseServer = (serverId) => {
		setClaimForm({ ...claimForm, server_id: serverId });
		loadRoster(serverId);
	};

	const handleClaimSubmit = async (e) => {
		e.preventDefault();
		setClaimMsg('');
		setError('');
		if (!claimForm.server_id || !claimForm.in_game_username.trim()) {
			setError('Pick a server and enter your in-game username');
			return;
		}
		try {
			await api.claims.create(token, {
				server_id: parseInt(claimForm.server_id, 10),
				in_game_username: claimForm.in_game_username.trim()
			});
			setClaimForm({ server_id: '', in_game_username: '' });
			setRoster([]);
			setRosterState('idle');
			setClaimMsg('Character linked to your account. You can send rewards to it now.');
			push('Character linked.', { kind: 'success' });
			loadClaims();
			loadCharacters();
			refresh();
		} catch (err) {
			console.error('Submit claim error:', err);
			setError(err.message || 'Failed to submit claim');
		}
	};

	const claimStatusBadge = (status) => {
		const map = {
			approved: 'success',
			pending: 'warning',
			rejected: 'secondary',
			revoked: 'danger'
		};
		return map[status] || 'secondary';
	};

	const serverName = (id) => {
		const s = servers.find((sv) => sv.id === id);
		return s ? s.name : `#${id}`;
	};

	const handleEdit = (character) => {
		setEditingCharacter(character);
		setFormData({ description: character.description || '' });
		setShowModal(true);
	};

	const handleSubmit = async (e) => {
		e.preventDefault();
		setError('');

		try {
			await api.characters.update(token, editingCharacter.id, formData);
			setShowModal(false);
			loadCharacters();
		} catch (err) {
			console.error('Save character error:', err);
			setError('Failed to save character');
		}
	};

	const handleUnlink = async () => {
		const character = unlinking;
		try {
			await api.characters.unlink(token, character.id);
			push(`${character.in_game_username || character.name} unlinked.`);
			loadCharacters();
			loadClaims();
			refresh();
		} catch (err) {
			console.error('Unlink character error:', err);
			setError(err.message || 'Failed to unlink character');
		}
		setUnlinking(null);
	};

	if (loading) {
		return (
			<section className="py-5" style={{ minHeight: '50vh' }}>
				<div className="container text-center">
					<div className="spinner-border text-light" role="status">
						<span className="visually-hidden">Loading...</span>
					</div>
				</div>
			</section>
		);
	}

	return (
		<section className="py-5" style={{ minHeight: '50vh' }}>
			<div className="container">
				<div className="d-flex justify-content-between align-items-center mb-4">
					<div>
						<h2 className="text-uppercase font-display">
							My Characters
						</h2>
						<p className="text-body-secondary">
							Claim your in-game characters to link them to your account
						</p>
					</div>
				</div>

				{error && (
					<div className="alert alert-danger" role="alert">
						{error}
					</div>
				)}

				<div className="row g-4 mb-4">
					{/* List claimed characters */}
					{(characters.length > 0) && (
						characters.map((character) => (
							<div key={character.id} className="col-md-6 col-lg-4">
								<div className="card h-100">
									<img
										className="card-img-top card-banner object-fit-cover"
										src={character.avatar && character.avatar.startsWith('http')
											? character.avatar.replace(/['"]/g, '')
											: '/assets/images/safezone-banner-1.png'}
										alt={character.name}
									/>
									<div className="card-body d-flex flex-column">
										<h5 className="card-title font-display">
											{character.name}
											{character.verified && (
												<span className="badge text-bg-success ms-2" title="Linked in-game character">
													<i className="fas fa-check"></i> Linked
												</span>
											)}
										</h5>
										{character.verified && (
											<div className="text-body-secondary mb-2">
												<i className="fas fa-gamepad"></i> {character.in_game_username} @ {serverName(character.server_id)}
												{character.last_seen_at && (
													<div className="small">
														<i className="fas fa-clock"></i> Last online{' '}
														{new Date(character.last_seen_at).toLocaleString()}
													</div>
												)}
											</div>
										)}
										{/* Player-written, and labelled as such: the badge above
												vouches for the identity, not for anything below it. */}
										<p className="card-text text-body-secondary flex-grow-1 fst-italic">
											{character.description || 'No notes yet'}
										</p>
										<div className="d-flex gap-2">
											<button
												className="btn btn-outline-light btn-sm"
												onClick={() => handleEdit(character)}
											>
												<i className="fas fa-edit"></i> Edit
											</button>
											<button
												className="btn btn-outline-danger btn-sm"
												onClick={() => setUnlinking(character)}
											>
												<i className="fas fa-link-slash"></i> Unlink
											</button>
										</div>
									</div>
								</div>
							</div>
						))
					)}

					{/* Claim an in-game character */}
					<div className="col-md-6 col-lg-4">
						<div className="card h-100">
							<div className="card-body d-flex flex-column">

								<h5 className="card-title font-display mb-1">Claim a Character</h5>
								<p className="text-body-secondary">
									Link an in-game character to your account so you can receive items.
									You must be <strong>online</strong> on the server as that character when
									you claim it.
								</p>
								{claimMsg && <div className="alert alert-success py-2">{claimMsg}</div>}
								<form className="row" onSubmit={handleClaimSubmit}>
									<div className="col-md-12 mb-2">
										<label className="form-label text-body-secondary" htmlFor="claim-server">
											Server
										</label>
										<select
											id="claim-server"
											className="form-select"
											value={claimForm.server_id}
											onChange={(e) => chooseServer(e.target.value)}
										>
											<option value="">Select a server…</option>
											{servers.map((s) => (
												<option key={s.id} value={s.id} disabled={s.state === 'stopped'}>
													{s.name}{s.state === 'stopped' ? ' — offline' : ''}
												</option>
											))}
										</select>
									</div>
									<div className="col-md-12 mb-2">
										<label className="form-label text-body-secondary" htmlFor="claim-name">
											In-game username
										</label>
										{rosterState === 'ready' && roster.length > 0 ? (
											<select
												id="claim-name"
												className="form-select"
												value={claimForm.in_game_username}
												onChange={(e) => setClaimForm({ ...claimForm, in_game_username: e.target.value })}
											>
												<option value="">Who are you, of those online…</option>
												{roster.map((name) => (
													<option key={name} value={name}>{name}</option>
												))}
											</select>
										) : (
											<input
												id="claim-name"
												type="text"
												className="form-control"
												placeholder="YourInGameName"
												value={claimForm.in_game_username}
												onChange={(e) => setClaimForm({ ...claimForm, in_game_username: e.target.value })}
											/>
										)}
										{claimForm.server_id && (
											<div className="form-text">
												{rosterState === 'loading' && 'Checking who is online…'}
												{rosterState === 'ready' && roster.length > 0
													&& `${roster.length} online right now — pick yourself from the list.`}
												{rosterState === 'ready' && roster.length === 0
													&& 'Nobody is online on that server yet. Log in as your character, then claim.'}
												{rosterState === 'error'
													&& 'Could not read who is online; type the name exactly as it appears in game.'}
											</div>
										)}
									</div>
									<div className="col-md-12">
										<button type="submit" className="btn btn-danger w-100">Claim</button>
									</div>
								</form>
							</div>
						</div>
					</div>

				</div>

				{/* List any links */}
				{claims.length > 0 && (
					<div className="card mb-4" id="claim">
						<div className="card-body">
							<div className="mt-0">
								<div className="text-body-secondary mb-2">My character links</div>
								<ul className="list-group">
									{claims.map((c) => (
										<li key={c.id} className="list-group-item d-flex justify-content-between align-items-center">
											<span>
												{c.in_game_username} @ {serverName(c.server_id)}
												{c.reason && (
													<small className="d-block text-body-secondary">{c.reason}</small>
												)}
											</span>
											<span className={`badge text-bg-${claimStatusBadge(c.status)}`}>{c.status}</span>
										</li>
									))}
								</ul>
							</div>
						</div>
					</div>
				)}

				{unlinking && (
					<ConfirmDialog
						title={`Unlink ${unlinking.in_game_username || unlinking.name}?`}
						confirmLabel="Unlink"
						onCancel={() => setUnlinking(null)}
						onConfirm={handleUnlink}
					>
						{unlinking.verified ? (
							<>
								<p>
									Rewards will stop reaching this character, and anyone else will
									be able to claim <strong>{unlinking.in_game_username}</strong> on
									that server.
								</p>
								<p className="mb-0 text-body-secondary">
									Anything already in your inventory stays with your account.
								</p>
							</>
						) : (
							<p className="mb-0">This character will be removed from your account.</p>
						)}
					</ConfirmDialog>
				)}

				{/* Modal */}
				{showModal && (
					<div className="modal show d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }}>
						<div className="modal-dialog modal-dialog-centered">
							<div className="modal-content">
								<div className="modal-header">
									<h5 className="modal-title font-display">
										Notes on {editingCharacter?.in_game_username || editingCharacter?.name}
									</h5>
									<button
										type="button"
										className="btn-close"
										onClick={() => setShowModal(false)}
									></button>
								</div>
								<form onSubmit={handleSubmit}>
									<div className="modal-body">
										<div className="mb-3">
											<label className="form-label">Your notes</label>
											<textarea
												className="form-control"
												rows="3"
												value={formData.description}
												onChange={(e) => setFormData({ ...formData, description: e.target.value })}
												placeholder="Anything you want to remember about this character"
											></textarea>
											<div className="form-text">
												Notes you write yourself. Nothing here is read from the
												game — the only fact the site knows is when the character
												was last online.
											</div>
										</div>
									</div>
									<div className="modal-footer">
										<button
											type="button"
											className="btn btn-outline-light"
											onClick={() => setShowModal(false)}
										>
											Cancel
										</button>
										<button type="submit" className="btn btn-danger">
											Save
										</button>
									</div>
								</form>
							</div>
						</div>
					</div>
				)}
			</div>
		</section>
	);
}

export default Characters;
