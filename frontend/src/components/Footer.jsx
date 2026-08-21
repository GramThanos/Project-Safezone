// Page Footer
import React, { useState, useEffect } from 'react';
import { useLocation, Link } from 'react-router-dom';
import { useSite } from '../context/SiteContext';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';

// Bootstrap contextual colour for a dependency's state.
const dotColour = (value) => {
	if (value === 'connected' || value === 'running' || value === 'healthy') return 'success';
	if (!value || value === 'unknown') return 'secondary';
	return 'danger';
};

function AdminFooter({ year }) {
	const { brand_name: brand } = useSite();
	const [health, setHealth] = useState(null);

	useEffect(() => {
		let cancelled = false;
		api.health()
			.then((data) => { if (!cancelled) setHealth(data); })
			.catch((err) => console.error('Health check error:', err));
		return () => { cancelled = true; };
	}, []);

	const stat = (label, value) => (
		<span className="d-inline-flex align-items-center gap-1">
			<i className={`fas fa-circle text-${dotColour(value)}`} style={{ fontSize: '0.5rem' }}></i>
			{label} <span className="font-monospace">{value || 'unknown'}</span>
		</span>
	);

	return (
		<footer className="bg-body-tertiary border-top mt-5 py-3">
			<div className="container d-flex flex-wrap justify-content-between align-items-center gap-3 small text-body-secondary">
				<div className="d-flex flex-wrap align-items-center gap-3">
					<span>
						<span className="font-display text-uppercase fw-bold">{brand}</span>{' '}
						<span className="font-monospace">v{health?.version || '—'}</span>
					</span>
					{stat('database', health?.database)}
					{stat('cache', health?.cache)}
					{stat('game server', health?.game_server)}
				</div>
				<div>&copy; {year} {brand}</div>
			</div>
		</footer>
	);
}

// Icon and label per social network
const SOCIAL = [
	['discord', 'fab fa-discord', 'Discord'],
	['twitter', 'fab fa-x-twitter', 'X'],
	['youtube', 'fab fa-youtube', 'YouTube'],
	['steam', 'fab fa-steam', 'Steam']
];

function SiteFooter({ year }) {
	const { brand_name: brand, social, resources, legal } = useSite();
	const { user } = useAuth();
	const banned = user?.role === 'banned';
	const links = SOCIAL.filter(([key]) => social?.[key]);

	return (
		<footer className="bg-body-tertiary border-top mt-5 py-5">
			<div className="container">
				<div className="row gy-4">
					<div className="col-md-5">
						<h5 className="font-display text-uppercase">{brand}</h5>
						<p className="text-body-secondary">
							A Project Zomboid dedicated server web manager with a modern interface for managing servers, characters, and tasks.
						</p>
					</div>

					<div className="col-md-3 text-center">
						{links.length > 0 && (
							<>
								<h6>Follow</h6>
								<div className="d-flex gap-2">
									{links.map(([key, icon, label]) => (
										<a
											key={key}
											className="btn btn-outline-secondary btn-sm"
											href={social[key]}
											target="_blank"
											rel="noopener noreferrer"
											title={label}
											aria-label={label}
										>
											<i className={icon}></i>
										</a>
									))}
								</div>
							</>
						)}
					</div>

					<div className="col-md-4 text-end">
						<h6>Resources</h6>
						<ul className="list-unstyled">
							{resources.map((r) => (
								<li key={r.url}>
									<a
										className="link-body-emphasis text-decoration-none"
										href={r.url}
										target="_blank"
										rel="noopener noreferrer"
									>
										{r.text} <i className="fas fa-arrow-up-right-from-square small"></i>
									</a>
								</li>
							))}
						</ul>
					</div>
				</div>

				<hr className="my-4" />

				<div className="d-flex justify-content-between text-body-secondary align-items-center flex-wrap gap-2">
					<div>&copy; {year} {brand}. All rights reserved.</div>
					<div className="d-flex flex-wrap gap-3">
						{user && (
							<Link className="link-body-emphasis text-decoration-none" to="/reports">
								<i className="fas fa-flag me-1"></i>
								{banned ? 'Appeal your ban' : 'Report an issue'}
							</Link>
						)}
						{legal.map((page) => (
							<Link key={page.slug} className="link-body-emphasis text-decoration-none" to={`/${page.slug}`}>
								{page.title}
							</Link>
						))}
					</div>
				</div>
			</div>
		</footer>
	);
}

function Footer() {
	const year = new Date().getFullYear();
	const inAdmin = useLocation().pathname.startsWith('/admin');
	return inAdmin ? <AdminFooter year={year} /> : <SiteFooter year={year} />;
}

export default Footer;
