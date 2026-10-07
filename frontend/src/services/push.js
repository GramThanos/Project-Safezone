// Browser push, outside React: what `usePush` builds on, and what the session
// (`AuthContext`) needs when it starts or ends.
//
// A device's subscription on the server belongs to the sign-in session it was
// made in, and stops when that session ends. The browser keeps its side, so:
//
//   - signing in again re-binds it (`rebindPush`), and reminders resume;
//   - signing out releases both sides (`releasePush`), so the next person to
//     sign in on a shared computer does not inherit them.
import api from './api';

export const pushSupported = () =>
  'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

export const currentSubscription = async () => {
  if (!pushSupported()) return null;
  const registration = await navigator.serviceWorker.getRegistration();
  return registration ? registration.pushManager.getSubscription() : null;
};

// Tie this device's subscription, if it has one, to the session `token` is
// from. True when there was nothing to do or it worked.
export const rebindPush = async (token) => {
  try {
    if (!pushSupported() || Notification.permission !== 'granted') return true;
    const subscription = await currentSubscription();
    if (!subscription) return true;
    await api.push.subscribe(token, subscription.toJSON());
    return true;
  } catch (err) {
    console.error('Push rebind error:', err);
    return false;
  }
};

// Turn this device's notifications off on both sides.
export const releasePush = async (token) => {
  try {
    const subscription = await currentSubscription();
    if (!subscription) return;
    // The server first, while the endpoint still identifies the row; a failure
    // there is harmless, since the next send finds the device gone.
    if (token) await api.push.unsubscribe(token, subscription.endpoint).catch(() => {});
    await subscription.unsubscribe();
  } catch (err) {
    console.error('Push release error:', err);
  }
};
