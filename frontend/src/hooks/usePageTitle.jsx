// Per-route browser titles.
//
// Every tab used to read the brand name and nothing else, which made four open
// tabs indistinguishable, browser history useless, and a shared link preview
// identical whatever it pointed at.
//
// The bare title is also published for the installed app's header
// (`AppHeader`), which has no browser tab to show it in.
import { useEffect, useState } from 'react';
import { useSite } from '../context/SiteContext';

let current = null;
const listeners = new Set();

const publish = (title) => {
  current = title;
  listeners.forEach((listener) => listener(title));
};

export default function usePageTitle(title) {
  const { brand_name: brand } = useSite();

  useEffect(() => {
    const name = brand || 'Project Safezone';
    document.title = title ? `${title} · ${name}` : name;
    publish(title || null);
    // Back to the plain brand on the way out, so a page that sets no title of
    // its own never inherits the last one's.
    return () => {
      document.title = name;
      publish(null);
    };
  }, [title, brand]);
}

// The current page's title without the brand, or null for none.
export function useCurrentPageTitle() {
  const [title, setTitle] = useState(current);

  useEffect(() => {
    listeners.add(setTitle);
    setTitle(current);
    return () => listeners.delete(setTitle);
  }, []);

  return title;
}
