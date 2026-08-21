// The site navbar
import React, { useState, useEffect } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useSite } from '../context/SiteContext';
import { usePlayer } from '../context/PlayerContext';

function Navbar() {
	const { user, signout, isModerator } = useAuth();
	const { brand_name: brand } = useSite();
	const { unread, boxes, onlineCharacters } = usePlayer();
	const banned = user?.role === 'banned';
	const navigate = useNavigate();
	const location = useLocation();
	const inAdmin = location.pathname.startsWith('/admin');
	const [expanded, setExpanded] = useState(false);

	useEffect(() => {
		setExpanded(false);
	}, [location.pathname]);

	const handleSignout = () => {
		signout();
		navigate('/');
	};

	if (inAdmin && isModerator()) return null;

	return (
		<nav className="navbar navbar-expand-lg bg-body-tertiary border-bottom py-3">
			<div className="container">
				<Link className="navbar-brand text-uppercase font-display fw-bold" to="/">{brand}</Link>
				<button
					className="navbar-toggler"
					type="button"
					onClick={() => setExpanded(!expanded)}
					aria-controls="navMenu"
					aria-expanded={expanded}
					aria-label="Toggle navigation"
				>
					<span className="navbar-toggler-icon"></span>
				</button>

				<div className={`collapse navbar-collapse${expanded ? ' show' : ''}`} id="navMenu">
					<ul className="navbar-nav ms-auto align-items-lg-center">
						<li className="nav-item">
							<Link className="nav-link" to="/">
								<i className="fas fa-house me-1" aria-hidden="true"></i>Home
							</Link>
						</li>
						<li className="nav-item">
							<Link className="nav-link" to="/servers">
								<i className="fas fa-server me-1" aria-hidden="true"></i>Servers
							</Link>
						</li>
						{user && (
							<>
								{!banned && (
									<>
										<li className="nav-item">
											<Link className="nav-link" to="/characters">
												<i className="fas fa-user-astronaut me-1" aria-hidden="true"></i>
												Characters
											</Link>
										</li>
										<li className="nav-item">
											<Link className="nav-link position-relative" to="/rewards">
												<i className="fas fa-gift me-1" aria-hidden="true"></i>
												Rewards
												{boxes.length > 0 && (
													<span
														className="badge rounded-pill text-bg-warning ms-1"
														title={`${boxes.length} crate${boxes.length === 1 ? '' : 's'} waiting`}
													>
														{boxes.length}
													</span>
												)}
											</Link>
										</li>
									</>
								)}
								{/* Notifications */}
								<li className="nav-item">
									<Link className="nav-link position-relative" to="/notifications">
										<i className="fas fa-bell me-1" aria-hidden="true"></i>
										Notifications
										{unread > 0 && (
											<span className="badge rounded-pill text-bg-danger ms-1">
												{unread > 99 ? '99+' : unread}
											</span>
										)}
									</Link>
								</li>
								{/* Account menu */}
								<li className="nav-item dropdown ms-lg-2">
									<button
										className="nav-link dropdown-toggle btn btn-link"
										type="button"
										data-bs-toggle="dropdown"
										aria-expanded="false"
									>
										{onlineCharacters.length > 0 && (
											<i
												className="fas fa-circle text-success me-1"
												style={{ fontSize: '.5rem', verticalAlign: 'middle' }}
												title={`Online in game as ${onlineCharacters.map((c) => c.in_game_username).join(', ')}`}
											></i>
										)}
										{user.username}
									</button>
									<ul className="dropdown-menu dropdown-menu-end">
										{!banned && (
											<li>
												<Link className="dropdown-item" to="/profile">
													<i className="fas fa-id-card me-2" aria-hidden="true"></i>Profile
												</Link>
											</li>
										)}
										{/* Panel for Moderators & Admins */}
										{isModerator() && !banned && (
											<li>
												<Link className="dropdown-item" to="/admin">
													<i className="fas fa-screwdriver-wrench me-2" aria-hidden="true"></i>
													Admin panel
												</Link>
											</li>
										)}
										{!banned && <li><hr className="dropdown-divider" /></li>}
										<li>
											<button className="dropdown-item" onClick={handleSignout}>
												<i className="fas fa-right-from-bracket me-2" aria-hidden="true"></i>
												Sign out
											</button>
										</li>
									</ul>
								</li>
							</>
						)}
						{!user && (
							<li className="nav-item ms-lg-3">
								<Link className="btn btn-danger btn-sm" to="/signin">
									<i className="fas fa-right-to-bracket me-1" aria-hidden="true"></i>Sign in
								</Link>
							</li>
						)}
					</ul>
				</div>
			</div>
		</nav>
	);
}

export default Navbar;
