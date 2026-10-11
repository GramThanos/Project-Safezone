// The leaderboard table, shared by the player page and the admin panel.
//
// Rows arrive ranked by zombie kills (then time alive); a header click re-sorts
// the view without changing the ranks, which stay the server's. `staff` adds
// the owner, the linked account and why a hidden character is hidden - fields
// the player endpoint never sends.
import React, { useMemo, useState } from 'react';
import { tagName } from './CharacterGameInfo';
import { formatDateTime } from '../utils/dates';

const COLUMNS = [
	{ key: 'rank', label: '#', numeric: true },
	{ key: 'name', label: 'Character' },
	{ key: 'profession', label: 'Profession' },
	{ key: 'zombie_kills', label: 'Zombie kills', numeric: true },
	{ key: 'survivor_kills', label: 'Survivor kills', numeric: true },
	{ key: 'hours_survived', label: 'Time alive', numeric: true }
];

const HIDDEN_LABELS = {
	excluded: ['Excluded', 'text-bg-secondary'],
	banned: ['Banned', 'text-bg-danger']
};

const compare = (key, numeric) => (a, b) => {
	if (numeric) {
		// Missing numbers sort last whichever way round.
		const x = typeof a[key] === 'number' ? a[key] : -Infinity;
		const y = typeof b[key] === 'number' ? b[key] : -Infinity;
		return x - y;
	}
	return String(a[key] || '').localeCompare(String(b[key] || ''));
};

const number = (value) => (typeof value === 'number' ? value.toLocaleString() : '—');

// Which servers have a board, and the save it was read from.
export function LeaderboardHeader({ data, serverId, onServer }) {
	if (!data) return null;
	return (
		<div className="d-flex flex-wrap align-items-center gap-3 mb-3">
			{data.servers.length > 1 && (
				<select
					className="form-select w-auto"
					aria-label="Server"
					value={serverId ?? data.server_id ?? ''}
					onChange={(e) => onServer(Number(e.target.value))}
				>
					{data.servers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
				</select>
			)}
			{data.saved_at && (
				<span className="small text-body-secondary">
					As of the game's last save, {formatDateTime(data.saved_at)}
					{data.stale && ' (the server is not answering, so this may be out of date)'}
				</span>
			)}
		</div>
	);
}

export default function LeaderboardTable({ rows, staff = false }) {
	const [sort, setSort] = useState({ key: 'rank', desc: false });

	const sorted = useMemo(() => {
		const column = COLUMNS.find((c) => c.key === sort.key) || COLUMNS[0];
		const list = [...rows];
		if (column.key === 'rank') {
			// The server's order; hidden rows (no rank) keep their place in it.
			return sort.desc ? list.reverse() : list;
		}
		list.sort(compare(column.key, column.numeric));
		return sort.desc ? list.reverse() : list;
	}, [rows, sort]);

	const toggle = (column) => setSort((current) => (
		current.key === column.key
			? { key: column.key, desc: !current.desc }
			// Numbers read best biggest first, names A to Z.
			: { key: column.key, desc: column.numeric && column.key !== 'rank' }
	));

	if (rows.length === 0) {
		return <p className="text-body-secondary text-center py-4">No living characters yet.</p>;
	}

	return (
		<div className="table-responsive">
			<table className="table table-hover align-middle">
				<thead>
					<tr>
						{COLUMNS.map((column) => (
							<th
								key={column.key}
								scope="col"
								className={column.numeric ? 'text-end' : ''}
								aria-sort={sort.key === column.key ? (sort.desc ? 'descending' : 'ascending') : undefined}
							>
								<button
									type="button"
									className="btn btn-link p-0 text-reset text-decoration-none fw-semibold text-nowrap"
									onClick={() => toggle(column)}
								>
									{column.label}
									{sort.key === column.key && (
										<i className={`fas fa-caret-${sort.desc ? 'down' : 'up'} ms-1`} aria-hidden="true"></i>
									)}
								</button>
							</th>
						))}
						{staff && <th scope="col">In-game user</th>}
						{staff && <th scope="col">Account</th>}
						{staff && <th scope="col">Shown</th>}
					</tr>
				</thead>
				<tbody>
					{sorted.map((row, index) => {
						const hidden = staff && row.hidden ? HIDDEN_LABELS[row.hidden] : null;
						return (
							<tr key={`${row.username || ''}:${row.name}:${index}`} className={hidden ? 'opacity-50' : ''}>
								<td className="text-end">{row.rank ?? '—'}</td>
								<td className="fw-semibold">{row.name || '—'}</td>
								<td>{row.profession ? tagName(row.profession) : '—'}</td>
								<td className="text-end">{number(row.zombie_kills)}</td>
								<td className="text-end">{number(row.survivor_kills)}</td>
								<td className="text-end text-nowrap">{row.time_alive || '—'}</td>
								{staff && <td className="font-monospace small">{row.username}</td>}
								{staff && <td>{row.account ? row.account.username : <span className="text-body-secondary">not linked</span>}</td>}
								{staff && (
									<td>
										{hidden
											? <span className={`badge ${hidden[1]}`}>{hidden[0]}</span>
											: <span className="badge text-bg-success">Yes</span>}
									</td>
								)}
							</tr>
						);
					})}
				</tbody>
			</table>
		</div>
	);
}
