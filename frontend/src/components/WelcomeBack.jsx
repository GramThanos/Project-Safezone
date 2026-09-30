// What happened since last login
import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { usePlayer } from '../context/PlayerContext';

const SEEN_KEY = 'safezone.welcome.seen';

function WelcomeBack() {
	const { user } = useAuth();
	const { boxes, unread, streak, loading } = usePlayer();
	const { pathname } = useLocation();
	const [dismissed, setDismissed] = useState(false);

	useEffect(() => {
		if (!user) return;
		if (sessionStorage.getItem(SEEN_KEY) === String(user.id ?? user.username)) {
			setDismissed(true);
		}
	}, [user]);

	const close = () => {
		setDismissed(true);
		try {
			sessionStorage.setItem(SEEN_KEY, String(user?.id ?? user?.username));
		} catch {
			// pass
		}
	};

	if (!user || dismissed || loading) return null;
	// Staff at work in the admin panel are not there to collect crates.
	if (pathname === '/admin' || pathname.startsWith('/admin/')) return null;

	const crates = boxes.length;
	const streakLive = streak?.enabled && !streak?.earned && streak?.remaining > 0;
	const streakReachable = streakLive && streak.remaining <= streak.days_left + 1;

	// Nothing waiting
	if (!crates && !unread && !streakReachable) return null;

	return (
		<div className="container my-4">
			<div className="d-flex flex-wrap gap-3 align-items-center justify-content-between">
				<div>
					<h5 className="font-display mb-2">
						Welcome back, {user.username}
					</h5>
					<ul className="list-unstyled mb-0 d-flex flex-column gap-1">
						{crates > 0 && (
							<li>
								<i className="fas fa-box-open text-warning me-2"></i>
								{crates === 1 ? 'A crate is waiting to be opened' : `${crates} crates are waiting`}
							</li>
						)}
						{unread > 0 && (
							<li>
								<i className="fas fa-bell text-info me-2"></i>
								{unread === 1 ? 'One unread notification' : `${unread} unread notifications`}
							</li>
						)}
						{streakReachable && (
							<li>
								<i className="fas fa-fire text-danger me-2"></i>
								{streak.remaining === 1
									? 'One more daily crate this week earns the bonus'
									: `${streak.remaining} more daily crates this week earn the bonus`}
							</li>
						)}
					</ul>
				</div>
				<div className="d-flex gap-2">
					{crates > 0 && (
						<Link className="btn btn-danger" to="/rewards" onClick={close}>
							Open {crates === 1 ? 'it' : 'them'}
						</Link>
					)}
					{crates === 0 && unread > 0 && (
						<Link className="btn btn-danger" to="/notifications" onClick={close}>
							Read
						</Link>
					)}
					<button className="btn btn-outline-secondary" onClick={close}>
						Dismiss
					</button>
				</div>
			</div>
		</div>
	);
}

export default WelcomeBack;
