// Where a lazily loaded page appears: a loading state while its chunk is on
// the way, and an error state if it never arrives.
//
// Pages are fetched the first time they are opened (see `page` in App.jsx), so
// every route renders inside one of these. The loading state waits a moment
// before showing, because on a warm cache a page arrives in a few milliseconds
// and a spinner flashing up and away reads as a glitch; it also holds the
// page's height, so the footer does not jump up and back.
import React, { Component, Suspense, useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';

const SHOW_AFTER_MS = 200;

export function PageLoading() {
	const [visible, setVisible] = useState(false);

	useEffect(() => {
		const timer = setTimeout(() => setVisible(true), SHOW_AFTER_MS);
		return () => clearTimeout(timer);
	}, []);

	return (
		<div className="d-flex justify-content-center align-items-start py-5" style={{ minHeight: '50vh' }}>
			{visible && (
				<div role="status" className="d-flex flex-column align-items-center gap-2 text-body-secondary">
					<div className="spinner-border" aria-hidden="true"></div>
					<span className="small">Loading…</span>
				</div>
			)}
		</div>
	);
}

// A page whose chunk could not be loaded - offline, or a deploy the automatic
// reload did not recover from. Without a boundary that error would unmount the
// whole app and leave a blank screen.
class LoadErrorBoundary extends Component {
	constructor(props) {
		super(props);
		this.state = { failed: false, resetKey: props.resetKey };
	}

	static getDerivedStateFromError() {
		return { failed: true };
	}

	// Navigating somewhere else gives that page its own chance to load.
	static getDerivedStateFromProps(props, state) {
		if (props.resetKey !== state.resetKey) return { failed: false, resetKey: props.resetKey };
		return null;
	}

	componentDidCatch(error) {
		console.error('Page failed to load:', error);
	}

	render() {
		if (!this.state.failed) return this.props.children;
		return (
			<div className="container py-5 text-center" style={{ minHeight: '50vh' }}>
				<i className="fas fa-cloud-arrow-down fa-2x text-body-secondary mb-3" aria-hidden="true"></i>
				<h5 className="font-display">This page could not be loaded</h5>
				<p className="text-body-secondary">
					Check your connection. If the site was just updated, reloading picks up the new version.
				</p>
				<button type="button" className="btn btn-outline-secondary" onClick={() => window.location.reload()}>
					<i className="fas fa-rotate-right me-2" aria-hidden="true"></i>Reload
				</button>
			</div>
		);
	}
}

function PageBoundary({ children }) {
	const { pathname } = useLocation();
	return (
		<LoadErrorBoundary resetKey={pathname}>
			<Suspense fallback={<PageLoading />}>{children}</Suspense>
		</LoadErrorBoundary>
	);
}

export default PageBoundary;
