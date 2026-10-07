// The service worker: browser notifications, and nothing else.
//
// Deliberately has no `fetch` handler, so it never sits between the page and
// the network - the site loads exactly as it would without it, for players who
// never turn notifications on and for those who do.
//
// Pushes arrive without a payload (see game-server/src/push.py, which only
// signs them), so the words are here. Every push sent today is the daily crate
// reminder; sending anything else means giving pushes a payload first.
const REMINDER = {
	title: 'Your daily crate is waiting',
	body: 'Claim it before the day resets.',
	url: '/rewards'
};

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
	event.waitUntil(self.registration.showNotification(REMINDER.title, {
		body: REMINDER.body,
		icon: '/assets/images/icons/icon-192.png',
		// A newer reminder replaces an older one rather than stacking.
		tag: 'daily-crate',
		data: { url: REMINDER.url }
	}));
});

// Tapping it opens the page it is about: in a window of the site that is
// already open if there is one, otherwise a new one.
self.addEventListener('notificationclick', (event) => {
	event.notification.close();
	const url = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href;
	event.waitUntil((async () => {
		const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
		const open = windows.find((client) => new URL(client.url).origin === self.location.origin);
		if (open) {
			await open.focus();
			try {
				await open.navigate(url);
				return;
			} catch (e) {
				// Not ours to steer (opened before this worker took over).
			}
		}
		await self.clients.openWindow(url);
	})());
});
