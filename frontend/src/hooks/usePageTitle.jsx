// Per-route browser titles.
//
// Every tab used to read the brand name and nothing else, which made four open
// tabs indistinguishable, browser history useless, and a shared link preview
// identical whatever it pointed at.
import { useEffect } from 'react';
import { useSite } from '../context/SiteContext';

export default function usePageTitle(title) {
  const { brand_name: brand } = useSite();

  useEffect(() => {
    const name = brand || 'Project Safezone';
    document.title = title ? `${title} · ${name}` : name;
    // Back to the plain brand on the way out, so a page that sets no title of
    // its own never inherits the last one's.
    return () => { document.title = name; };
  }, [title, brand]);
}
