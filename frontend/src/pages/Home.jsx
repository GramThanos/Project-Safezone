// Home - used to advertise the website's own features to players
import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useSite } from '../context/SiteContext';
import { usePlayer } from '../context/PlayerContext';
import api from '../services/api';
import usePageTitle from '../hooks/usePageTitle';

const PERKS = [
	{
		icon: 'fa-box-open',
		title: 'A crate every day',
		desc: 'Show up and one is waiting. Collect enough in a week and a bonus crate follows.'
	},
	{
		icon: 'fa-user-check',
		title: 'Your character, linked',
		desc: 'Claim your in-game survivor while you are online. That link is what lets us hand you things.'
	},
	{
		icon: 'fa-truck-fast',
		title: 'Delivered in game',
		desc: 'Whatever you win is sent straight to your character while you play. No forum posts, no waiting on staff.'
	}
];

function Home() {
	usePageTitle(null);
	const { user } = useAuth();
	const { hero_title: heroTitle, hero_subtitle: heroSubtitle } = useSite();
	const { boxes } = usePlayer();
	const [servers, setServers] = useState([]);

	useEffect(() => {
		let cancelled = false;
		api.servers.getStatus()
			.then((data) => { if (!cancelled) setServers(data.servers || []); })
			.catch((err) => console.error('Connection error:', err));
		return () => { cancelled = true; };
	}, []);

	const online = servers.reduce((sum, s) => sum + (s.online_count || 0), 0);
	const running = servers.filter((s) => (s.state || s.default_state) === 'running');

	return (
		<>
			{/* HERO */}
			<div className="card text-bg-dark border-0 rounded-0">
				<img
					src="/assets/images/safezone-banner-8.png"
					className="card-img hero-img object-fit-cover rounded-0"
					alt="Survivors defending the safezone"
				/>
				<div className="card-img-overlay d-flex flex-column justify-content-center align-items-center text-center">
					<div className="container" style={{ maxWidth: '820px', textShadow: '0 0 8px black' }}>
						<h1 className="display-4 fw-bold text-uppercase font-display">{heroTitle}</h1>
						<p className="lead">{heroSubtitle}</p>
						<div className="d-flex justify-content-center gap-3 mt-4 flex-wrap">
							<Link className="btn btn-danger btn-lg" to={user ? '/rewards' : '/signin'}>
								{user
									? (boxes.length ? `Open ${boxes.length} crate${boxes.length === 1 ? '' : 's'}` : 'My rewards')
									: 'Join the servers'}
							</Link>
							<Link className="btn btn-outline-light btn-lg" to="/servers">View Servers</Link>
						</div>
					</div>
				</div>
			</div>

			{/* LIVE SERVERS */}
			{servers.length > 0 && (
				<section className="py-5">
					<div className="container">
						<div className="d-flex justify-content-between align-items-baseline mb-3">
							<h3 className="text-uppercase font-display mb-0">Servers</h3>
						</div>
						<div className="row g-3">
							{servers.slice(0, 3).map((server) => (
								<div className="col-md-4" key={server.id}>
									<div className="card h-100">
										<div className="card-body">
											<div className="d-flex justify-content-between align-items-start">
												<h5 className="card-title font-display mb-1">{server.name}</h5>
												<span className={`badge text-bg-${
													(server.state || server.default_state) === 'running' ? 'success' : 'secondary'
												}`}>
													{server.state || server.default_state}
												</span>
											</div>
											<div className="d-flex align-items-baseline gap-2">
												<span className="font-display fs-4 lh-1">
													{typeof server.online_count === 'number' ? server.online_count : '—'}
												</span>
												<span className="text-body-secondary small">survivors online</span>
											</div>
											{server.description && (
												<p className="card-text text-body-secondary small mt-2 mb-0">
													{server.description}
												</p>
											)}
										</div>
									</div>
								</div>
							))}
						</div>
					</div>
				</section>
			)}

			{/* WHAT YOU GET */}
			<section className="py-5 border-top">
				<div className="container">
					<h3 className="text-uppercase font-display mb-4">What you get</h3>
					<div className="row g-4">
						{PERKS.map((perk) => (
							<div key={perk.title} className="col-md-4">
								<div className="card h-100">
									<div className="card-body">
										<i className={`fas ${perk.icon} fa-2x text-danger mb-3`}></i>
										<h5 className="card-title font-display">{perk.title}</h5>
										<p className="card-text text-body-secondary mb-0">{perk.desc}</p>
									</div>
								</div>
							</div>
						))}
					</div>
				</div>
			</section>

			{/* HOW TO JOIN */}
			<section className="py-5 border-top">
				<div className="container">
					<h3 className="text-uppercase font-display mb-4">Joining takes a minute</h3>
					<div className="row g-4">
						<div className="col-md-4">
							<div className="font-display fs-1 text-danger lh-1">1</div>
							<h6 className="font-display">Make an account</h6>
							<p className="text-body-secondary mb-0">
								It is what holds your crates and your rewards between sessions.
							</p>
						</div>
						<div className="col-md-4">
							<div className="font-display fs-1 text-danger lh-1">2</div>
							<h6 className="font-display">Connect in game</h6>
							<p className="text-body-secondary mb-0">
								Server addresses are on the <Link to="/servers">servers page</Link> once
								you are signed in, with the steps for adding one in Project Zomboid.
							</p>
						</div>
						<div className="col-md-4">
							<div className="font-display fs-1 text-danger lh-1">3</div>
							<h6 className="font-display">Claim your survivor</h6>
							<p className="text-body-secondary mb-0">
								While you are online, <Link to="/characters">claim the character</Link> you
								are playing. Rewards start arriving after that.
							</p>
						</div>
					</div>
				</div>
			</section>

			{/* CALL TO ACTION — signed-out only */}
			{!user && (
				<section className="pt-5 border-top">
					<div className="container text-center">
						<h3 className="text-uppercase font-display mb-3">Join the Safezone</h3>
						<p className="text-body-secondary mb-4">
							Create an account today and start your survival journey
						</p>
						<Link className="btn btn-danger btn-lg" to="/signin">Sign Up Now</Link>
					</div>
				</section>
			)}
		</>
	);
}

export default Home;
