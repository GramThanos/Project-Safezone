// App mode: the site installed to a phone's home screen.
//
// Both have to hold - opened from the home screen (`display-mode: standalone`,
// or `navigator.standalone` on older iOS) *and* a touch screen with a phone's
// viewport - so a desktop install and a tablet keep the website layout. The
// `max-height` arm is a phone held sideways, which is wider than the cut-off.
//
// The decision lives here and nowhere else: this sets `<html data-app="phone">`,
// src/index.css keys off that attribute, and React reads it through `useAppMode`,
// which listens for the `appmodechange` event this fires. It is a file rather
// than an inline script because the page's CSP admits no inline script, and it
// loads in <head> so the first paint is already the right layout.
//
// `?app=1` forces app mode for the tab (for a desktop browser's device
// toolbar, which can fake a phone but not an install); `?app=0` clears it.
(function () {
	var KEY = 'safezone.app';
	var INSTALLED = '(display-mode: standalone)';
	var PHONE = '(pointer: coarse) and (max-width: 767.98px), (pointer: coarse) and (max-height: 500px)';

	var root = document.documentElement;
	var viewport = document.querySelector('meta[name="viewport"]');
	var baseViewport = viewport ? viewport.getAttribute('content') : '';

	function forced() {
		try {
			return sessionStorage.getItem(KEY) === '1';
		} catch (e) {
			return false;
		}
	}

	try {
		var params = new URLSearchParams(location.search);
		var param = params.get('app');
		if (param === '1') sessionStorage.setItem(KEY, '1');
		if (param === '0') sessionStorage.removeItem(KEY);
		if (param !== null) {
			params.delete('app');
			var query = params.toString();
			history.replaceState(history.state, '', location.pathname + (query ? '?' + query : '') + location.hash);
		}
	} catch (e) {
		// Storage blocked: no override, detection still works.
	}

	function update() {
		var installed = window.matchMedia(INSTALLED).matches || navigator.standalone === true;
		var on = forced() || (installed && window.matchMedia(PHONE).matches);
		if (on === (root.getAttribute('data-app') === 'phone')) return;

		if (on) root.setAttribute('data-app', 'phone');
		else root.removeAttribute('data-app');
		// Edge to edge only in the app, where the header and tab bar pad
		// themselves clear of the notch; the website keeps the browser's margins.
		if (viewport) viewport.setAttribute('content', on ? baseViewport + ', viewport-fit=cover' : baseViewport);
		window.dispatchEvent(new Event('appmodechange'));
	}

	update();
	[INSTALLED, PHONE].forEach(function (query) {
		var mq = window.matchMedia(query);
		if (mq.addEventListener) mq.addEventListener('change', update);
		else mq.addListener(update);
	});
})();
