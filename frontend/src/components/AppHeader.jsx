// The installed app's top bar, in place of the site navbar.
//
// Navigation moves to the bottom `TabBar`, so this carries only the page title,
// the notification bell, and a back button below the tab roots - an app opened
// from an iPhone's home screen has no browser back button or gesture at all.
import React from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useSite } from '../context/SiteContext';
import { usePlayer } from '../context/PlayerContext';
import { useCurrentPageTitle } from '../hooks/usePageTitle';
import { TAB_ROOTS, ME_PAGES } from '../hooks/useAppHistory';

function AppHeader() {
	const { user } = useAuth();
	const { brand_name: brand } = useSite();
	const { unread } = usePlayer();
	const title = useCurrentPageTitle();
	const { pathname } = useLocation();
	const navigate = useNavigate();

	const atRoot = TAB_ROOTS.includes(pathname);

	// Back through the app's own history when there is some; a page opened
	// straight from a link has none, so it goes up to its tab instead of out.
	const back = () => {
		if ((window.history.state?.idx ?? 0) > 0) navigate(-1);
		else navigate(ME_PAGES.includes(pathname) ? '/me' : '/', { replace: true });
	};

	return (
		<header className="app-header bg-body-tertiary border-bottom sticky-top">
			<div className="d-flex align-items-center gap-2 px-3">
				{atRoot ? (
					<Link to="/" className="d-flex align-items-center" aria-label="Home">
						<img className="app-header-logo" src="/assets/images/safezone-logo.png" alt="" width="32" height="32"/>
					</Link>
				) : (
					<button type="button" className="btn btn-link app-header-button" onClick={back} aria-label="Back">
						<i className="fas fa-chevron-left" aria-hidden="true"></i>
					</button>
				)}
				<span className="app-header-title font-display text-uppercase fw-bold text-truncate flex-grow-1">
					{title || brand}
				</span>
				{user && (
					<Link
						to="/notifications"
						className="btn btn-link app-header-button position-relative"
						aria-label={unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'}
					>
						<i className="fas fa-bell" aria-hidden="true"></i>
						{unread > 0 && (
							<span className="app-badge badge rounded-pill text-bg-danger">
								{unread > 99 ? '99+' : unread}
							</span>
						)}
					</Link>
				)}
			</div>
		</header>
	);
}

export default AppHeader;
