// The back button, for the installed app.
//
// A browser's back walks every page visited, tab switches included. An app's
// goes *up*: out of an open dialog, back through the pages opened within the
// current tab, from that tab to Home, and from Home out of the app. So in app
// mode the history is kept in that shape:
//
//   [ Home, tab, page, page, ... ]
//
// - Switching tabs returns to the tab slot and replaces it, rather than piling
//   another entry on top, so back from any tab is Home.
// - Opening the app on some other page (a link, a shortcut) slides Home - and
//   that page's tab - in underneath it first.
// - An open dialog gets an entry of its own, so back closes the dialog rather
//   than leaving the page behind it.
//
// Positions are React Router's own index of the entry, `history.state.idx`.
import { useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import { useLocation, useNavigate, useNavigationType } from 'react-router-dom';

// The pages a tab opens: these get the logo in the header, every other page a
// back button.
export const TAB_ROOTS = ['/', '/servers', '/characters', '/rewards', '/me', '/signin'];

// Pages reached from Me, which keep the Me tab lit and go back up to it.
export const ME_PAGES = ['/profile', '/notifications', '/reports', '/leaderboard','/rules', '/terms', '/privacy', '/cookies'];

export const isUnder = (path, base) => path === base || path.startsWith(`${base}/`);

// Pages reached from a tab other than Me, which keep that tab lit.
const TAB_PAGES = { '/shop': '/rewards' };

// The tab a page belongs to, or null for one that stands alone (sign-up,
// password reset, email verification).
const tabOf = (path) => {
  if (TAB_ROOTS.includes(path)) return path;
  if (TAB_PAGES[path]) return TAB_PAGES[path];
  if (ME_PAGES.includes(path) || isUnder(path, '/admin')) return '/me';
  return null;
};

const entryIndex = () => window.history.state?.idx ?? 0;
const onDialogEntry = () => Boolean(window.history.state?.usr?.appDialog);
const openDialogs = () => document.querySelectorAll('.modal.show');

export default function useAppHistory(appMode) {
  const location = useLocation();
  const navigationType = useNavigationType();
  const navigate = useNavigate();

  // The observer and timers below outlive a render; they read these.
  const latest = useRef({ location, navigate });
  latest.current = { location, navigate };

  const seeded = useRef(false);
  const pendingTab = useRef(null);
  const handledPop = useRef(null);

  // An entry for the open dialog: the same page, marked.
  const pushDialogEntry = useCallback(() => {
    const { location: { pathname, search, hash, state }, navigate: go } = latest.current;
    const base = state && typeof state === 'object' ? state : {};
    go({ pathname, search, hash }, { state: { ...base, appDialog: true } });
  }, []);

  // Opened on a page other than Home: put Home, and the page's tab, beneath it.
  useEffect(() => {
    if (!appMode || seeded.current) return;
    seeded.current = true;
    const { location: { pathname, search, hash, state }, navigate: go } = latest.current;
    if (entryIndex() !== 0 || pathname === '/') return;

    const tab = tabOf(pathname);
    go('/', { replace: true });
    if (tab && tab !== '/' && tab !== pathname) go(tab);
    go({ pathname, search, hash }, { state });
  }, [appMode]);

  // Switch to a tab without stacking it on the one being left.
  const openTab = useCallback((to) => {
    const { navigate: go } = latest.current;
    const idx = entryIndex();
    if (to === '/') {
      if (idx > 0) go(-idx);
      else go('/', { replace: true });
    } else if (idx === 0) {
      go(to);
    } else if (idx === 1) {
      go(to, { replace: true });
    } else {
      // Back down to the tab slot first; the layout effect below swaps it.
      pendingTab.current = to;
      go(-(idx - 1));
    }
  }, []);

  // Arrived back at the tab slot on the way to another tab: replace it. A
  // layout effect, so the page passed through on the way is never painted.
  useLayoutEffect(() => {
    const to = pendingTab.current;
    if (!to) return;
    pendingTab.current = null;
    latest.current.navigate(to, { replace: true });
  }, [location.key]);

  // Follow dialogs opening and closing: one opening pushes its entry, and one
  // closed by its own buttons takes that entry back off.
  useEffect(() => {
    if (!appMode) return undefined;
    let open = openDialogs().length > 0;
    const observer = new MutationObserver(() => {
      const now = openDialogs().length > 0;
      if (now === open) return;
      open = now;
      if (now && !onDialogEntry()) pushDialogEntry();
      if (!now && onDialogEntry()) latest.current.navigate(-1);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [appMode, pushDialogEntry]);

  // Back pressed.
  useEffect(() => {
    if (!appMode || navigationType !== 'POP') return undefined;
    // Once per press, though React may run this effect twice for it.
    if (handledPop.current === location.key) return undefined;
    handledPop.current = location.key;
    const dialogs = openDialogs();

    // Left a dialog's entry with the dialog still up: close it instead.
    if (dialogs.length > 0 && !onDialogEntry()) {
      const dialog = dialogs[dialogs.length - 1];
      // Most dialogs close on Escape; the rest have a close button.
      dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
      setTimeout(() => {
        if (dialog.isConnected && dialog.matches('.modal.show')) {
          dialog.querySelector('.btn-close, [data-bs-dismiss="modal"]')?.click();
        }
        // One stacked under it, or one that will not close (mid-operation),
        // needs an entry again for the next press.
        setTimeout(() => {
          if (openDialogs().length > 0 && !onDialogEntry()) pushDialogEntry();
        }, 50);
      }, 50);
      return undefined;
    }

    // Landed on the entry of a dialog that is gone (it closed by navigating
    // away): nothing to see there, carry on back.
    if (dialogs.length === 0 && onDialogEntry()) latest.current.navigate(-1);
    return undefined;
  }, [appMode, navigationType, location.key, pushDialogEntry]);

  return openTab;
}

// Straight back to Home, as its tab does: the bottom of the history, rather
// than another entry on top. For links to Home outside the tab bar.
export const goHome = (navigate) => {
  const idx = entryIndex();
  if (idx > 0) navigate(-idx);
  else navigate('/', { replace: true });
};

// Section navigation inside one page of the app - the admin panel - kept in
// the same shape as the tabs: the panel holds one slot in the history, which
// switching section replaces, and only the pages opened *within* a section
// (a server's detail, its logs) stack on top of it. So back goes from a detail
// page to its list, and from any section out of the panel to where it was
// opened from, instead of through every section visited.
//
// The slot is wherever the panel was entered: recorded when the component
// using this mounts, which is once per visit, since the panel's layout stays
// mounted across its own pages. Returns `openSection(to)`; outside app mode it
// is a plain navigation.
export function useSectionHistory(appMode) {
  const location = useLocation();
  const navigate = useNavigate();
  const latest = useRef(navigate);
  latest.current = navigate;

  const slot = useRef(null);
  const pending = useRef(null);

  useEffect(() => {
    if (slot.current === null) slot.current = entryIndex();
  }, []);

  // Back at the slot on the way to another section: swap it in, before paint.
  useLayoutEffect(() => {
    const to = pending.current;
    if (!to) return;
    pending.current = null;
    latest.current(to, { replace: true });
  }, [location.key]);

  return useCallback((to) => {
    const go = latest.current;
    if (!appMode) {
      go(to);
      return;
    }
    const idx = entryIndex();
    const base = slot.current ?? idx;
    if (idx === base) {
      go(to, { replace: true });
    } else if (idx > base) {
      pending.current = to;
      go(-(idx - base));
    } else {
      // Somehow below the slot (history edited elsewhere): start over here.
      go(to);
      slot.current = idx + 1;
    }
  }, [appMode]);
}
