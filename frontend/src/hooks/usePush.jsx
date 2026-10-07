// Browser notifications for this device: whether they are possible here, and
// turning them on and off.
//
// Works in any browser that supports Web Push, installed or not - except on
// iPhone and iPad, where Apple only allows it for a site added to the Home
// Screen, so that case gets its own status rather than a bare "unsupported".
//
// The service worker (`public/sw.js`) is registered only when somebody turns
// notifications on, and it has no fetch handler, so it changes nothing about
// how the site loads for anyone.
import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import api, { isInstalled } from '../services/api';
import { pushSupported, currentSubscription, releasePush } from '../services/push';

// iPadOS reports itself as a Mac; the touch points give it away.
const appleMobile = () =>
  /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

// The base64url key the server hands out, as the bytes `subscribe` wants.
const toKey = (base64) => {
  const padded = (base64 + '='.repeat((4 - (base64.length % 4)) % 4))
    .replace(/-/g, '+')
    .replace(/_/g, '/');
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
};

// status: 'loading' | 'install' (iPhone/iPad, not on the Home Screen yet) |
// 'unsupported' | 'unavailable' (the server cannot send any) | 'denied'
// (blocked in the browser) | 'off' | 'on'
export default function usePush() {
  const { token } = useAuth();
  const [status, setStatus] = useState('loading');
  const [info, setInfo] = useState(null); // { public_key, reminder: { enabled, time, timezone } }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    const settle = (value) => { if (!cancelled) setStatus(value); };

    (async () => {
      if (appleMobile() && !isInstalled()) return settle('install');
      if (!pushSupported()) return settle('unsupported');
      if (!token) return settle('unavailable');
      try {
        const data = await api.push.key(token);
        if (cancelled) return;
        setInfo(data);
      } catch (err) {
        return settle('unavailable');
      }
      if (Notification.permission === 'denied') return settle('denied');
      try {
        settle((await currentSubscription()) ? 'on' : 'off');
      } catch (err) {
        settle('off');
      }
    })();

    return () => { cancelled = true; };
  }, [token]);

  const enable = useCallback(async () => {
    setError('');
    // Asked before anything else is awaited: Safari only shows the prompt
    // while the tap that called this still counts as one.
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      setStatus(permission === 'denied' ? 'denied' : 'off');
      return;
    }

    setBusy(true);
    try {
      const registration = await navigator.serviceWorker.register('/sw.js');
      await navigator.serviceWorker.ready;
      // One made against another key (the server's was replaced) cannot be
      // reused, and subscribing over it throws.
      const existing = await registration.pushManager.getSubscription();
      if (existing) await existing.unsubscribe();
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: toKey(info.public_key)
      });
      await api.push.subscribe(token, subscription.toJSON());
      setStatus('on');
    } catch (err) {
      setError(err.message || 'Could not turn notifications on.');
    } finally {
      setBusy(false);
    }
  }, [token, info]);

  const disable = useCallback(async () => {
    setError('');
    setBusy(true);
    try {
      await releasePush(token);
      setStatus('off');
    } catch (err) {
      setError(err.message || 'Could not turn notifications off.');
    } finally {
      setBusy(false);
    }
  }, [token]);

  return { status, reminder: info?.reminder, busy, error, enable, disable };
}
