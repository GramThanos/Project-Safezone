// Servers list - Show the servers deployied
import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import usePageTitle from '../hooks/usePageTitle';
import PlayerActivityChart from '../components/PlayerActivityChart';

function Servers() {
	usePageTitle('Servers');
	const { user, token } = useAuth();
	const [servers, setServers] = useState([]);
	const [history, setHistory] = useState({});
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState('');

	useEffect(() => {
		loadServers();
		// Refresh every 5 mins
		const interval = setInterval(loadServers, 5 * 60 * 1000);
		return () => clearInterval(interval);
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [token]);

	const loadServers = async () => {
		try {
			const data = await api.servers.getStatus(token);
			const list = data.servers || [];
			setServers(list);
			setLoading(false);
			loadHistory(list);
		} catch (err) {
			console.error('Load servers error:', err);
			setError('Failed to load servers');
			setLoading(false);
		}
	};

	// Fetch the 24h activity series for each server
	const loadHistory = async (list) => {
		const results = await Promise.all(list.map(async (server) => {
			try {
				const data = await api.servers.getHistory(server.id, 24);
				return [server.id, data.history || []];
			} catch (err) {
				console.error(`Load history error (server ${server.id}):`, err);
				return [server.id, []];
			}
		}));
		setHistory(Object.fromEntries(results));
	};

	const getStatusBadge = (state) => {
		const statusMap = {
			'running': 'success',
			'sleeping': 'warning',
			'restarting': 'info',
			'failed': 'danger',
			'stopped': 'secondary'
		};
		return statusMap[state?.toLowerCase()] || 'secondary';
	};

	// The address players type into the game client: host plus the primary port.
	const connectionString = (server) => {
		//const port = Array.isArray(server.ports) && server.ports.length ? server.ports[0] : null;
		//if (!server.hostname) return null;
		//return port ? `${server.hostname}:${port}` : server.hostname;
		if (!server.hostname) return null;
		return server.hostname;
	};

	if (loading) {
		return (
			<section className="py-5" style={{ minHeight: '50vh' }}>
				<div className="container text-center">
					<div className="spinner-border text-light" role="status">
						<span className="visually-hidden">Loading...</span>
					</div>
					<p className="mt-3">Loading servers...</p>
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
							Game Servers
						</h2>
						<p className="text-body-secondary">View active servers and their status</p>
					</div>
					{/*
					<button className="btn btn-danger" onClick={loadServers}>
						<i className="fas fa-sync-alt"></i> Refresh
					</button>
					*/}
				</div>

				{error && (
					<div className="alert alert-danger" role="alert">
						{error}
					</div>
				)}

				{servers.length === 0 ? (
					<div className="text-center py-5">
						<p className="text-body-secondary">No servers configured yet</p>
					</div>
				) : (
					<div className="row g-4">
						{servers.map((server) => {
							const address = connectionString(server);
							return (
								<div key={server.id} className="col-md-6 col-lg-4">
									<div className="card h-100">
										<div className="card-body d-flex flex-column">
											<div className="d-flex justify-content-between align-items-start mb-2">
												<h5 className="card-title font-display mb-0">{server.name}</h5>
												<span className={`badge text-bg-${getStatusBadge(server.state)}`}>
													{server.state || server.default_state}
												</span>
											</div>

											{/* Activity over the last 24 hours */}
											<PlayerActivityChart history={history[server.id] || []} height={80} />
											{/* Online right now */}
											{typeof server.online_count === 'number' && (
												<div className="text-body-secondary small mt-1 text-end">
													{server.online_count} {server.online_count === 1 ? 'survivor online' : 'survivors online'}
												</div>
											)}

											{/* Server description */}
											{server.description && (
												<p className="card-text text-body-secondary mt-1 mb-3">
													{server.description || 'No description provided.'}
												</p>
											)}

											{/* Connection details - Members only */}
											{user && (
												<>
													<div className="d-flex justify-content-between">
														<span className="text-body-secondary">
															<i className="fas fa-plug"></i> Host:
														</span>
														<span className="font-monospace">
															{address}
														</span>
													</div>
													<div className="d-flex justify-content-between">
														<span className="text-body-secondary">
															<i className="fas fa-network-wired"></i> Ports:
														</span>
														<span className="font-monospace">
															{Array.isArray(server.ports) ? server.ports.join(', ') : '-'}
														</span>
													</div>
												</>
											)}
										</div>
									</div>
								</div>
							);
						})}
					</div>
				)}
			</div>
		</section>
	);
}

export default Servers;
