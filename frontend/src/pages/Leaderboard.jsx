// The leaderboard: every living character on a server, most zombie kills first.
//
// Characters only - never the account behind one. Who may open it is a
// setting (public, signed-in players, or staff only), enforced by the API; this
// page just explains a refusal.
import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import usePageTitle from '../hooks/usePageTitle';
import LeaderboardTable, { LeaderboardHeader } from '../components/LeaderboardTable';

function Leaderboard() {
	usePageTitle('Leaderboard');
	const { token } = useAuth();
	const [serverId, setServerId] = useState(null);
	const [data, setData] = useState(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState(null);

	useEffect(() => {
		let cancelled = false;
		setLoading(true);
		api.leaderboard.get(token, serverId)
			.then((result) => {
				if (cancelled) return;
				setData(result);
				setError(null);
			})
			.catch((err) => {
				if (cancelled) return;
				console.error('Load leaderboard error:', err);
				setError(err);
			})
			.finally(() => { if (!cancelled) setLoading(false); });
		return () => { cancelled = true; };
	}, [token, serverId]);

	let body;
	if (loading && !data) {
		body = (
			<div className="text-center py-5">
				<div className="spinner-border text-light" role="status">
					<span className="visually-hidden">Loading...</span>
				</div>
			</div>
		);
	} else if (error?.status === 401) {
		body = (
			<div className="text-center py-5">
				<p className="text-body-secondary">Sign in to see the leaderboard.</p>
				<Link className="btn btn-danger" to="/signin">
					<i className="fas fa-right-to-bracket me-1" aria-hidden="true"></i>Sign in
				</Link>
			</div>
		);
	} else if (error?.status === 404 && !data) {
		body = <p className="text-body-secondary text-center py-5">The leaderboard is not available.</p>;
	} else if (error) {
		body = <div className="alert alert-danger" role="alert">{error.message || 'Failed to load the leaderboard'}</div>;
	} else {
		body = (
			<>
				<LeaderboardHeader data={data} serverId={serverId} onServer={setServerId} />
				<LeaderboardTable rows={data.characters} />
			</>
		);
	}

	return (
		<section className="py-5" style={{ minHeight: '50vh' }}>
			<div className="container">
				<h2 className="text-uppercase font-display">Leaderboard</h2>
				<p className="text-body-secondary">
					Every survivor still alive, most zombie kills first. Time alive is in-game time.
				</p>
				{body}
			</div>
		</section>
	);
}

export default Leaderboard;
