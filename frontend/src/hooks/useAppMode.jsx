// Whether the site is running as the installed app on a phone.
//
// Decided by `public/assets/app-mode.js` before React starts, so this only
// reads the attribute it sets and follows its `appmodechange` event (a phone
// rotating past the cut-off, or the `?app=` override).
import { useEffect, useState } from 'react';

const read = () => document.documentElement.getAttribute('data-app') === 'phone';

export default function useAppMode() {
  const [appMode, setAppMode] = useState(read);

  useEffect(() => {
    const sync = () => setAppMode(read());
    window.addEventListener('appmodechange', sync);
    sync();
    return () => window.removeEventListener('appmodechange', sync);
  }, []);

  return appMode;
}
