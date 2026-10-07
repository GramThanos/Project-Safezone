// The "remind me about my crate" switch for this device.
//
// A card on the profile; `row` renders it as a list item for the app's Me tab.
// Per device rather than per account, because that is what a browser
// subscription is: turning it on here says nothing about the player's laptop.
import React from 'react';
import usePush from '../hooks/usePush';

const BLOCKED = {
	install: 'On iPhone and iPad, add this site to your Home Screen first (Share, then Add to Home Screen), and turn reminders on from there.',
	unsupported: 'This browser cannot show notifications from websites.',
	unavailable: 'Notifications are unavailable right now.',
	denied: "Notifications are blocked for this site. Allow them in your browser's site settings, then come back here."
};

function NotificationSettings({ row = false }) {
	const { status, reminder, busy, error, enable, disable } = usePush();

	if (status === 'loading') return null;

	const on = status === 'on';
	const blocked = BLOCKED[status];
	const description = blocked || (reminder?.enabled
		? `If today's crate is still unclaimed at ${reminder.time} (${reminder.timezone} time), this device gets a reminder.`
		: 'Crate reminders are not being sent on this site yet.');

	// Off is always allowed; on only when something would actually arrive.
	const toggle = (
		<div className="form-check form-switch m-0">
			<input
				className="form-check-input"
				type="checkbox"
				role="switch"
				id={row ? 'push-switch-row' : 'push-switch'}
				checked={on}
				disabled={Boolean(blocked) || busy || (!on && !reminder?.enabled)}
				onChange={() => (on ? disable() : enable())}
				aria-label="Crate reminders on this device"
			/>
		</div>
	);

	if (row) {
		return (
			<div className="list-group-item d-flex align-items-center py-3 gap-3">
				<i className="fas fa-bell fa-fw text-body-secondary" aria-hidden="true"></i>
				<div className="flex-grow-1" style={{ minWidth: 0 }}>
					<div>Crate reminders</div>
					<div className="small text-body-secondary">{description}</div>
					{error && <div className="small text-danger">{error}</div>}
				</div>
				{!blocked && toggle}
			</div>
		);
	}

	return (
		<div className="card mb-4">
			<div className="card-body p-4">
				<div className="d-flex align-items-center justify-content-between gap-3 mb-2">
					<h5 className="card-title font-display m-0">Crate Reminders</h5>
					{!blocked && toggle}
				</div>
				<p className="text-body-secondary small mb-0">{description}</p>
				{!blocked && (
					<p className="text-body-secondary small mb-0 mt-2">
						Applies to this device and browser only.
					</p>
				)}
				{error && <div className="alert alert-danger small mt-3 mb-0">{error}</div>}
			</div>
		</div>
	);
}

export default NotificationSettings;
