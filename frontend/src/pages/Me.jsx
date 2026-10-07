// The installed app's Me tab ("More" when signed out).
//
// Holds what the website keeps in the navbar's account menu and the footer,
// both of which the app hides: account pages, the admin panel, community and
// legal links, and signing out. An ordinary page, so it also works when opened
// in a browser.
import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useSite } from '../context/SiteContext';
import { usePlayer } from '../context/PlayerContext';
import usePageTitle from '../hooks/usePageTitle';
import NotificationSettings from '../components/NotificationSettings';
import Coins from '../components/Coins';

// Icon and label per social network, as in the footer
const SOCIAL = [
	['discord', 'fab fa-discord', 'Discord'],
	['twitter', 'fab fa-x-twitter', 'X'],
	['youtube', 'fab fa-youtube', 'YouTube'],
	['steam', 'fab fa-steam', 'Steam']
];

function Row({ to, href, icon, children, badge }) {
	const content = (
		<>
			<i className={`${icon} fa-fw me-3 text-body-secondary`} aria-hidden="true"></i>
			<span className="flex-grow-1">{children}</span>
			{badge}
			<i className={`fas ${href ? 'fa-arrow-up-right-from-square' : 'fa-chevron-right'} small text-body-secondary ms-2`} aria-hidden="true"></i>
		</>
	);
	const className = 'list-group-item list-group-item-action d-flex align-items-center py-3';
	return href ? (
		<a className={className} href={href} target="_blank" rel="noopener noreferrer">{content}</a>
	) : (
		<Link className={className} to={to}>{content}</Link>
	);
}

function Me() {
	const { user, signout, isModerator } = useAuth();
	const { brand_name: brand, social, resources, legal } = useSite();
	const { unread, onlineCharacters, coins } = usePlayer();
	const navigate = useNavigate();
	const banned = user?.role === 'banned';
	const links = SOCIAL.filter(([key]) => social?.[key]);

	usePageTitle(user ? 'Me' : 'More');

	const handleSignout = () => {
		signout();
		navigate('/');
	};

	return (
		<section className="py-4">
			<div className="container d-flex flex-column gap-4">
				{user ? (
					<div className="d-flex align-items-center gap-3">
						<div className="app-avatar rounded-circle bg-body-tertiary border d-flex align-items-center justify-content-center">
							<i className="fas fa-user" aria-hidden="true"></i>
						</div>
						<div style={{ minWidth: 0 }}>
							<div className="fw-bold text-truncate">{user.username}</div>
							<div className="small text-body-secondary text-truncate">
								{onlineCharacters.length > 0 ? (
									<>
										<i className="fas fa-circle text-success me-1" style={{ fontSize: '.5rem', verticalAlign: 'middle' }} aria-hidden="true"></i>
										Online as {onlineCharacters.map((c) => c.in_game_username).join(', ')}
									</>
								) : <span className="text-capitalize">{user.role}</span>}
							</div>
						</div>
					</div>
				) : (
					<Link className="btn btn-danger btn-lg" to="/signin">
						<i className="fas fa-right-to-bracket me-2" aria-hidden="true"></i>Sign in
					</Link>
				)}

				{user && (
					<div className="list-group">
						{!banned && <Row to="/profile" icon="fas fa-id-card">Profile</Row>}
						{!banned && coins.enabled && (
							<Row to="/shop" icon="fas fa-store" badge={<Coins amount={coins.balance} className="fw-semibold" />}>
								Shop
							</Row>
						)}
						<Row
							to="/notifications"
							icon="fas fa-bell"
							badge={unread > 0 && (
								<span className="badge rounded-pill text-bg-danger">{unread > 99 ? '99+' : unread}</span>
							)}
						>
							Notifications
						</Row>
						<Row to="/reports" icon="fas fa-flag">{banned ? 'Appeal your ban' : 'Report an issue'}</Row>
						{isModerator() && !banned && (
							<Row to="/admin" icon="fas fa-screwdriver-wrench">Admin panel</Row>
						)}
					</div>
				)}

				{user && !banned && (
					<div className="list-group">
						<NotificationSettings row />
					</div>
				)}

				{(links.length > 0 || resources.length > 0) && (
					<div className="list-group">
						{links.map(([key, icon, label]) => (
							<Row key={key} href={social[key]} icon={icon}>{label}</Row>
						))}
						{resources.map((r) => (
							<Row key={r.url} href={r.url} icon="fas fa-book">{r.text}</Row>
						))}
					</div>
				)}

				{legal.length > 0 && (
					<div className="list-group">
						{legal.map((page) => (
							<Row key={page.slug} to={`/${page.slug}`} icon="fas fa-file-lines">{page.title}</Row>
						))}
					</div>
				)}

				{user && (
					<button type="button" className="btn btn-outline-danger py-2" onClick={handleSignout}>
						<i className="fas fa-right-from-bracket me-2" aria-hidden="true"></i>Sign out
					</button>
				)}

				<div className="text-center small text-body-secondary">
					&copy; {new Date().getFullYear()} {brand}
				</div>
			</div>
		</section>
	);
}

export default Me;
