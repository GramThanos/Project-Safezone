// Section navigation
import React, { useState, useEffect, useRef } from 'react';
import { NavLink, Link, useLocation, useNavigate } from 'react-router-dom';
import useAppMode from '../hooks/useAppMode';
import { goHome, useSectionHistory } from '../hooks/useAppHistory';

const isUnder = (path, base) => path === base || path.startsWith(`${base}/`);

// A link may carry `count`: an unread/outstanding number shown as a badge
// beside its text. Zero and undefined both render nothing, so a caller can pass
// a count straight through without guarding it. A group shows the total of its
// visible links' counts.
const groupCount = (group) => (group.links || [])
	.filter((link) => !link.hidden)
	.reduce((sum, link) => sum + (link.count || 0), 0);

// `logo` puts the site logo before the title, for when the title is the brand.
function SubNav({ title, titleTo, logo, badge, groups }) {
	const location = useLocation();
	const [expanded, setExpanded] = useState(false);
	const appMode = useAppMode();
	const ref = useRef(null);
	const navigate = useNavigate();
	const openSection = useSectionHistory(appMode);

	// In the installed app these links switch section rather than stack pages,
	// so back leaves the section instead of retracing it (see
	// `useSectionHistory`). Outside it they are ordinary links.
	const sectionClick = (to) => (event) => {
		if (!appMode) return;
		event.preventDefault();
		if (location.pathname !== to) openSection(to);
	};

	useEffect(() => {
		setExpanded(false);
	}, [location.pathname]);

	// In the installed app the rows scroll sideways instead of collapsing (see
	// index.css), so bring the current group and page into view.
	useEffect(() => {
		if (!appMode || !ref.current) return;
		ref.current.querySelectorAll('.nav-link.active').forEach((el) => {
			el.scrollIntoView({ block: 'nearest', inline: 'center' });
		});
	}, [appMode, location.pathname]);

	// Drop hidden links, then drop groups left empty by that.
	const visible = groups
		.map((group) => ({ ...group, links: group.links.filter((l) => !l.hidden) }))
		.filter((group) => group.links.length > 0);

	if (visible.length === 0) return null;

	const flat = visible.length === 1;
	const activeGroup = visible.find((group) =>
		group.links.some((link) => isUnder(location.pathname, link.to))
	);

	// The links
	const sectionLinks = flat ? visible[0].links : activeGroup?.links;

	const linkClass = ({ isActive }) => `nav-link${isActive ? ' active' : ''}`;

	return (
		<div className="subnav" ref={ref}>
			<nav
				className="navbar navbar-expand-lg bg-body-tertiary border-bottom py-3"
				aria-label={`${title} sections`}
			>
				<div className="container">
					{title && (
						titleTo ? (
							<Link
								className="navbar-brand d-flex align-items-center gap-2 text-uppercase font-display fw-bold me-2"
								to={titleTo}
								onClick={(event) => {
									// Out of the panel to Home the way the Home tab goes,
									// rather than another page on top of it.
									if (!appMode || titleTo !== '/') return;
									event.preventDefault();
									goHome(navigate);
								}}
							>
								{logo && (
									<img src="/assets/images/safezone-logo.png" alt="" width="32" height="32"/>
								)}
								{title}
							</Link>
						) : (
							<span className="navbar-brand text-uppercase font-display fw-bold fs-6 me-3">
								{title}
							</span>
						)
					)}
					{badge && (
						<span className="badge text-bg-secondary text-uppercase me-3">{badge}</span>
					)}

					<button
						className="navbar-toggler"
						type="button"
						onClick={() => setExpanded(!expanded)}
						aria-expanded={expanded}
						aria-label={`Toggle ${title} navigation`}
					>
						<span className="navbar-toggler-icon"></span>
					</button>

					<div className={`collapse navbar-collapse${expanded ? ' show' : ''}`}>
						<ul className="navbar-nav">
							{flat
								? visible[0].links.map((link) => (
										<li className="nav-item" key={link.to}>
											<NavLink to={link.to} className={linkClass} onClick={sectionClick(link.to)}>
												{link.icon && <i className={`bi bi-${link.icon} me-1`}></i>}
												{link.text}
												{link.count > 0 && (
													<span className="badge text-bg-danger ms-1">{link.count}</span>
												)}
											</NavLink>
										</li>
									))
								: visible.map((group) => (
										<li className="nav-item" key={group.label}>
											{/* To the group's first page */}
											<Link
												to={group.links[0].to}
												onClick={sectionClick(group.links[0].to)}
												className={`nav-link${group === activeGroup ? ' active' : ''}`}
												aria-current={group === activeGroup ? 'page' : undefined}
											>
												{group.icon && <i className={`bi bi-${group.icon} me-1`}></i>}
												{group.label}
												{/* Rolled up from the group's pages: a count on a link
												    inside a collapsed group is invisible until you have
												    already gone looking for it, which defeats the point
												    of having one. */}
												{groupCount(group) > 0 && (
													<span className="badge text-bg-danger ms-1">{groupCount(group)}</span>
												)}
											</Link>
										</li>
									))}
						</ul>
					</div>
				</div>
			</nav>

			{/* The pages of the group being viewed */}
			{!flat && sectionLinks && (
				<nav
					className="navbar navbar-expand py-1 border-bottom"
					aria-label={`${activeGroup.label} pages`}
				>
					<div className="container">
						<ul className="navbar-nav flex-row flex-wrap gap-2 small">
							{sectionLinks.map((link) => (
								<li className="nav-item" key={link.to}>
									<NavLink to={link.to} className={linkClass} onClick={sectionClick(link.to)}>
										{link.icon && <i className={`bi bi-${link.icon} me-1`}></i>}
										{link.text}
										{link.count > 0 && (
											<span className="badge text-bg-danger ms-1">{link.count}</span>
										)}
									</NavLink>
								</li>
							))}
						</ul>
					</div>
				</nav>
			)}
		</div>
	);
}

export default SubNav;
