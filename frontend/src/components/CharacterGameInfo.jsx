// What the game last saved about a linked character, read from the server's
// players.db by the game-server and cut to its reader by the backend.
//
// Two ways in:
//   <CharacterGameInfo characterId>      the owner's card: a summary that loads
//                                        with the card, plus a Details dialog
//   <CharacterGameButton characterId>    staff (claims, user manage): a button
//                                        that loads on click - every staff view
//                                        is audited, so nothing loads unasked
//
// The staff view carries the zombie infection; the owner's never does, because
// in the game a player does not know until the symptoms show. That is decided
// by the backend - this only renders `infection` when it is there.
import React, { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import { formatDateTime } from '../utils/dates';

// The map of Knox Country, opened at a tile: `?XxY` in whole tiles.
const MAP_URL = (x, y) => `https://pzmap.org?${Math.floor(x)}x${Math.floor(y)}`;

// The save's perk ids, where the game shows a different name.
const SKILL_NAMES = {
	Doctor: 'First Aid',
	Woodwork: 'Carpentry',
	PlantScavenging: 'Foraging',
	Lightfoot: 'Lightfooted',
	Sneak: 'Sneaking',
	Blunt: 'Long Blunt',
	SmallBlunt: 'Short Blunt',
	LongBlade: 'Long Blade',
	SmallBlade: 'Short Blade',
	Electricity: 'Electrical',
	MetalWelding: 'Metalworking',
	Husbandry: 'Animal Care',
	FlintKnapping: 'Knapping',
};
// Everyone starts these around 5; ranking them would crowd out what a
// character actually trained.
const PASSIVE_SKILLS = ['Fitness', 'Strength'];
const MAX_LEVEL = 10;

const STAT_LABELS = {
	hunger: 'Hunger',
	thirst: 'Thirst',
	fatigue: 'Tiredness',
	endurance: 'Endurance',
	stress: 'Stress',
	panic: 'Panic',
	boredom: 'Boredom',
	unhappiness: 'Unhappiness',
	pain: 'Pain',
	sickness: 'Sickness',
	wetness: 'Wetness',
	anger: 'Anger',
	intoxication: 'Drunkenness',
	drunkenness: 'Drunkenness',
	fear: 'Fear',
	zombie_infection: 'Zombie infection',
	zombie_fever: 'Zombie fever',
};
// Stats where a high value is good, so the bar is not painted as a warning.
const GOOD_STATS = ['endurance'];

const spaced = (id) => String(id || '')
	.replace(/^[a-z0-9_]+:/i, '')          // namespace: "base:doctor"
	.replace(/[_-]+/g, ' ')
	.replace(/([a-z])([A-Z])/g, '$1 $2')
	.trim();
const titled = (text) => text.replace(/\b\w/g, (c) => c.toUpperCase());

export const skillName = (id) => SKILL_NAMES[id] || spaced(id);
export const tagName = (id) => titled(spaced(id));

// "UpperArm_L" -> "Left upper arm", "Torso_Upper" -> "Upper torso".
export const bodyPartName = (id) => {
	const [base, side] = String(id || '').split('_');
	const name = spaced(base).toLowerCase();
	const prefix = { L: 'left', R: 'right', Upper: 'upper', Lower: 'lower' }[side];
	const text = prefix ? `${prefix} ${name}` : name;
	return text.charAt(0).toUpperCase() + text.slice(1);
};

const formatTime = (iso) => formatDateTime(iso, null);

const skillList = (skills) => Object.entries(skills || {})
	.map(([id, s]) => ({ id, name: skillName(id), level: s.level || 0, xp: s.xp || 0 }))
	.sort((a, b) => b.level - a.level || b.xp - a.xp || a.name.localeCompare(b.name));

// Loads one character's game data. `enabled` false holds the request until
// asked, which is how the staff button stays unaudited until clicked.
function useCharacterGame(characterId, staff, enabled) {
	const { token } = useAuth();
	const [state, setState] = useState({ status: 'idle', data: null, error: '' });

	const load = useCallback(async () => {
		setState((s) => ({ ...s, status: 'loading', error: '' }));
		try {
			const data = staff
				? await api.admin.characters.game(token, characterId)
				: await api.characters.game(token, characterId);
			setState({ status: 'ready', data, error: '' });
		} catch (err) {
			setState({
				status: err.status === 404 ? 'missing' : 'error',
				data: null,
				error: err.message || 'Could not load the character',
			});
		}
	}, [token, characterId, staff]);

	useEffect(() => {
		if (enabled) load();
	}, [enabled, load]);

	return { ...state, reload: load };
}

function LevelBar({ level }) {
	return (
		<span className="d-inline-flex gap-1 align-middle" aria-label={`Level ${level} of ${MAX_LEVEL}`}>
			{Array.from({ length: MAX_LEVEL }, (_, i) => (
				<span
					key={i}
					className={`d-inline-block rounded-1 ${i < level ? 'bg-warning' : 'bg-secondary bg-opacity-25'}`}
					style={{ width: 8, height: 10 }}
				/>
			))}
		</span>
	);
}

function StatusBadge({ character }) {
	if (character.status === 'dead') {
		return <span className="badge text-bg-secondary"><i className="fas fa-skull"></i> Dead</span>;
	}
	return (
		<span className="badge text-bg-success">
			<i className="fas fa-heart-pulse"></i> Alive
			{character.asleep && ' · asleep'}
			{character.in_vehicle && ' · driving'}
		</span>
	);
}

function Location({ location }) {
	if (!location?.text) return <span className="text-body-secondary">Unknown</span>;
	return (
		<>
			<code>{location.text}</code>
			{location.x != null && location.y != null && (
				<a
					className="ms-2"
					href={MAP_URL(location.x, location.y)}
					target="_blank"
					rel="noopener noreferrer"
					title="Open this spot on the map of Knox Country"
				>
					<i className="fas fa-map-location-dot"></i> Map
				</a>
			)}
		</>
	);
}

function AsOf({ data }) {
	return (
		<div className="small text-body-secondary">
			{data.stale && (
				<span className="text-warning me-1" title="The game server could not be reached; this is the last copy">
					<i className="fas fa-triangle-exclamation"></i> May be out of date ·
				</span>
			)}
			Saved by the game {formatTime(data.saved_at) || 'at an unknown time'}
		</div>
	);
}

function Unavailable({ status, error, reload }) {
	if (status === 'missing') {
		return (
			<div className="small text-body-secondary">
				<i className="fas fa-hourglass-half"></i> No save data yet - the game writes it a
				few minutes after the character joins.
			</div>
		);
	}
	return (
		<div className="small text-body-secondary">
			<i className="fas fa-plug-circle-xmark"></i> {error || 'Game data unavailable.'}{' '}
			<button type="button" className="btn btn-link btn-sm p-0 align-baseline" onClick={reload}>
				Try again
			</button>
		</div>
	);
}

function SkillsTab({ skills }) {
	const list = skillList(skills);
	if (list.length === 0) return <p className="text-body-secondary">No skills recorded.</p>;
	const passive = list.filter((s) => PASSIVE_SKILLS.includes(s.id));
	const trained = list.filter((s) => !PASSIVE_SKILLS.includes(s.id));
	const rows = (items) => items.map((s) => (
		<tr key={s.id}>
			<td>{s.name}</td>
			<td className="text-nowrap"><LevelBar level={s.level} /></td>
			<td className="text-end text-body-secondary small">{s.level}</td>
		</tr>
	));
	return (
		<table className="table table-sm align-middle mb-0">
			<tbody>
				{passive.length > 0 && (
					<>
						<tr><th colSpan="3" className="small text-body-secondary">Passive</th></tr>
						{rows(passive)}
					</>
				)}
				<tr><th colSpan="3" className="small text-body-secondary">Skills</th></tr>
				{rows(trained)}
			</tbody>
		</table>
	);
}

function StatBar({ name, stat }) {
	if (name === 'temperature') return null;
	const label = STAT_LABELS[name] || tagName(name);
	if (stat.percent == null) {
		return (
			<div className="d-flex justify-content-between small mb-2">
				<span>{label}</span>
				<span className="text-body-secondary">{Number(stat.value).toFixed(2)}</span>
			</div>
		);
	}
	const percent = Math.max(0, Math.min(100, stat.percent));
	const good = GOOD_STATS.includes(name);
	const tone = good
		? (percent < 25 ? 'danger' : percent < 50 ? 'warning' : 'success')
		: (percent > 75 ? 'danger' : percent > 40 ? 'warning' : 'success');
	return (
		<div className="mb-2">
			<div className="d-flex justify-content-between small">
				<span>{label}</span>
				<span className="text-body-secondary">{Math.round(percent)}%</span>
			</div>
			<div className="progress" style={{ height: 6 }} role="progressbar"
				aria-label={label} aria-valuenow={Math.round(percent)} aria-valuemin="0" aria-valuemax="100">
				<div className={`progress-bar bg-${tone}`} style={{ width: `${percent}%` }}></div>
			</div>
		</div>
	);
}

function HealthTab({ character }) {
	const { injuries = [], stats = {}, weight, infection } = character;
	const temperature = stats.temperature?.value;
	return (
		<>
			{infection && (
				<div className={`alert ${infection.infected ? 'alert-danger' : 'alert-secondary'} py-2`}>
					<div className="fw-semibold">
						<i className="fas fa-biohazard"></i>{' '}
						{infection.infected ? 'Infected with the zombie virus' : 'Not infected'}
						<span className="badge text-bg-dark ms-2">staff only</span>
					</div>
					{infection.infected && (
						<div className="small mt-1">
							{infection.parts.length > 0 && <>Through: {infection.parts.map(bodyPartName).join(', ')}. </>}
							{Object.entries(infection.stats || {}).map(([name, s]) => (
								<span key={name} className="me-2">
									{STAT_LABELS[name] || name}: {s.percent != null ? `${Math.round(s.percent)}%` : s.value}
								</span>
							))}
						</div>
					)}
				</div>
			)}

			<h6 className="text-body-secondary small text-uppercase">Injuries</h6>
			{injuries.length === 0 ? (
				<p className="small text-body-secondary">No injuries.</p>
			) : (
				<ul className="list-unstyled small mb-3">
					{injuries.map((injury) => (
						<li key={injury.part} className="mb-1">
							<span className="fw-semibold">{bodyPartName(injury.part)}</span>
							{injury.health != null && injury.health < 100 && (
								<span className="text-body-secondary"> · {Math.round(injury.health)}%</span>
							)}
							{injury.conditions.length > 0 && (
								<span className="text-body-secondary"> · {injury.conditions.join(', ')}</span>
							)}
						</li>
					))}
				</ul>
			)}

			<h6 className="text-body-secondary small text-uppercase">Condition</h6>
			<div className="d-flex gap-4 small mb-3">
				{weight != null && <span><i className="fas fa-weight-scale"></i> {weight.toFixed(1)} kg</span>}
				{temperature != null && <span><i className="fas fa-temperature-half"></i> {temperature.toFixed(1)} °C</span>}
			</div>
			{Object.entries(stats).map(([name, stat]) => <StatBar key={name} name={name} stat={stat} />)}
		</>
	);
}

function CharacterGameModal({ game, title, onClose }) {
	const [tab, setTab] = useState('skills');
	const character = game.data?.character;

	return (
		<div className="modal show d-block" style={{ backgroundColor: 'rgba(0,0,0,0.8)' }} onClick={onClose}>
			<div className="modal-dialog modal-dialog-centered modal-dialog-scrollable" onClick={(e) => e.stopPropagation()}>
				<div className="modal-content">
					<div className="modal-header">
						<h5 className="modal-title font-display">
							{character?.name || title}
							{character?.name && title && (
								<small className="text-body-secondary fs-6 ms-2">
									<i className="fas fa-gamepad"></i> {title}
								</small>
							)}
						</h5>
						<button type="button" className="btn-close" aria-label="Close" onClick={onClose}></button>
					</div>
					<div className="modal-body">
						{game.status === 'loading' || game.status === 'idle' ? (
							<div className="text-center py-4"><div className="spinner-border" role="status"></div></div>
						) : !character ? (
							<Unavailable {...game} reload={game.reload} />
						) : (
							<>
								<div className="d-flex flex-wrap gap-2 align-items-center mb-2">
									<StatusBadge character={character} />
									{character.profession && <span className="badge text-bg-dark">{tagName(character.profession)}</span>}
									{character.traits.map((t) => (
										<span key={t} className="badge text-bg-secondary">{tagName(t)}</span>
									))}
								</div>
								<div className="small mb-3">
									<i className="fas fa-location-dot"></i> <Location location={character.location} />
								</div>
								<ul className="nav nav-tabs mb-3">
									{[['skills', 'Skills'], ['health', 'Health']].map(([key, label]) => (
										<li className="nav-item" key={key}>
											<button type="button" className={`nav-link${tab === key ? ' active' : ''}`} onClick={() => setTab(key)}>
												{label}
											</button>
										</li>
									))}
								</ul>
								{tab === 'skills' ? <SkillsTab skills={character.skills} /> : <HealthTab character={character} />}
								{!character.complete && (
									<div className="small text-warning mt-3">
										<i className="fas fa-circle-info"></i> Part of this save could not be read; some details may be missing.
									</div>
								)}
							</>
						)}
					</div>
					{game.data && (
						<div className="modal-footer justify-content-start"><AsOf data={game.data} /></div>
					)}
				</div>
			</div>
		</div>
	);
}

// The owner's card: loads with the card, summary first, details on request.
export default function CharacterGameInfo({ characterId, title }) {
	const game = useCharacterGame(characterId, false, true);
	const [open, setOpen] = useState(false);
	const character = game.data?.character;

	if (game.status === 'idle' || game.status === 'loading') {
		return (
			<div className="placeholder-glow mb-2" aria-busy="true">
				<span className="placeholder col-6"></span>
				<span className="placeholder col-8 d-block mt-1"></span>
			</div>
		);
	}
	if (!character) return <div className="mb-2"><Unavailable {...game} reload={game.reload} /></div>;

	const top = skillList(character.skills).filter((s) => !PASSIVE_SKILLS.includes(s.id) && s.level > 0).slice(0, 3);

	return (
		<div className="border rounded p-2 mb-2 small">
			{character.name && (
				<div className="fw-semibold fs-6 mb-1">
					<i className="fas fa-user"></i> {character.name}
				</div>
			)}
			<div className="d-flex flex-wrap gap-2 align-items-center mb-1">
				<StatusBadge character={character} />
				{character.profession && <span className="badge text-bg-dark">{tagName(character.profession)}</span>}
			</div>
			<div className="mb-1">
				<i className="fas fa-clock"></i>{' '}
				{character.status === 'dead' ? 'Lived ' : 'Survived '}
				{character.time_alive || '-'}
				<span className="ms-3"><i className="fas fa-skull-crossbones"></i> {character.zombie_kills ?? 0} kills</span>
			</div>
			<div className="mb-1">
				<i className="fas fa-location-dot"></i> <Location location={character.location} />
			</div>
			{top.length > 0 && (
				<div className="mb-1">
					{top.map((s) => (
						<div key={s.id} className="d-flex justify-content-between align-items-center">
							<span>{s.name}</span>
							<LevelBar level={s.level} />
						</div>
					))}
				</div>
			)}
			<div className="d-flex justify-content-between align-items-center mt-2">
				<AsOf data={game.data} />
				<button type="button" className="btn btn-outline-light btn-sm" onClick={() => setOpen(true)}>
					<i className="fas fa-chart-simple"></i> Details
				</button>
			</div>
			{open && <CharacterGameModal game={game} title={title} onClose={() => setOpen(false)} />}
		</div>
	);
}

// Staff: nothing is fetched until the button is pressed, since each view is audited.
export function CharacterGameButton({ characterId, title, className = 'btn btn-sm btn-outline-secondary' }) {
	const [open, setOpen] = useState(false);
	const game = useCharacterGame(characterId, true, open);
	return (
		<>
			<button type="button" className={className} onClick={() => setOpen(true)} title="What the game last saved about this character">
				<i className="fas fa-chart-simple"></i> Game data
			</button>
			{open && <CharacterGameModal game={game} title={title} onClose={() => setOpen(false)} />}
		</>
	);
}
