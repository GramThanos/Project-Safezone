// The installed app's bottom tab bar, in place of the navbar's menu.
//
// Renders only in app mode (see `useAppMode`); the website keeps its navbar.
// Everything that is not a tab of its own - profile, notifications, the admin
// panel, legal pages, signing out - lives on the Me page, so the bar stays at
// a thumb's five.
import React, { useEffect, useRef } from 'react';
import { Link, useLocation, useNavigationType } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { usePlayer } from '../context/PlayerContext';
import useAppMode from '../hooks/useAppMode';
import useAppHistory, { ME_PAGES, isUnder } from '../hooks/useAppHistory';

const under = (...bases) => (path) => bases.some((base) => isUnder(path, base));

function TabBar() {
	const appMode = useAppMode();
	const { user } = useAuth();
	const { boxes } = usePlayer();
	const { pathname } = useLocation();
	const navigationType = useNavigationType();
	const openTab = useAppHistory(appMode);
	const banned = user?.role === 'banned';

	// A new page starts at the top, as a new screen in an app does. History
	// steps (the Android back button) are left to the browser, which puts the
	// page back where it was. Keyed to the path, so a dialog's history entry
	// (same page) does not count as a new page.
	const lastPath = useRef(pathname);
	useEffect(() => {
		if (lastPath.current === pathname) return;
		lastPath.current = pathname;
		if (appMode && navigationType !== 'POP') window.scrollTo(0, 0);
	}, [appMode, pathname, navigationType]);

	if (!appMode) return null;

	const me = { to: '/me', label: user ? 'Me' : 'More', icon: user ? 'fa-user' : 'fa-bars', match: under('/me', '/admin', ...ME_PAGES) };
	const tabs = [
		{ to: '/', label: 'Home', icon: 'fa-house', match: (path) => path === '/' },
		{ to: '/servers', label: 'Servers', icon: 'fa-server', match: under('/servers') },
		...(user && !banned
			? [
					{ to: '/characters', label: 'Characters', icon: 'fa-user-astronaut', match: under('/characters') },
					{ to: '/rewards', label: 'Rewards', icon: 'fa-gift', match: under('/rewards', '/shop'), count: boxes.length }
				]
			: []),
		...(!user
			? [{ to: '/signin', label: 'Sign in', icon: 'fa-right-to-bracket', match: under('/signin', '/signup', '/forgot-password', '/reset-password') }]
			: []),
		me
	];

	return (
		<nav className="app-tabbar bg-body-tertiary border-top" aria-label="App">
			{tabs.map((tab) => {
				const active = tab.match(pathname);
				return (
					<Link
						key={tab.to}
						to={tab.to}
						className={`app-tab${active ? ' active' : ''}`}
						aria-current={active ? 'page' : undefined}
						onClick={(event) => {
							event.preventDefault();
							// Tapping the tab you are on goes back to its top.
							if (pathname === tab.to) window.scrollTo({ top: 0, behavior: 'smooth' });
							else openTab(tab.to);
						}}
					>
						<span className="app-tab-icon position-relative">
							<i className={`fas ${tab.icon}`} aria-hidden="true"></i>
							{tab.count > 0 && (
								<span className="app-badge badge rounded-pill text-bg-warning">{tab.count}</span>
							)}
						</span>
						<span className="app-tab-label">{tab.label}</span>
					</Link>
				);
			})}
		</nav>
	);
}

export default TabBar;
