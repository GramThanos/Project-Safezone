// Site content: the brand name, the home page wording, the footer links.
//
// Fetched once and shared, because three separate components need it and three
// separate requests for the same never-changing document would be silly. The
// defaults below are what renders while the request is in flight, so the page
// never flashes an empty brand or a blank headline — they match the backend's
// own defaults.
import React, { createContext, useContext, useState, useEffect } from 'react';
import api from '../services/api';

const DEFAULTS = {
  brand_name: 'Project Safezone',
  hero_title: 'Time to fight zombies',
  hero_subtitle: 'Join our Project Zomboid dedicated servers and survive the '
    + 'apocalypse with your friends. Create your character, explore the world, '
    + 'and fight for survival in this multiplayer experience.',
  social: {},
  resources: [],
  legal: []
};

const SiteContext = createContext(DEFAULTS);

export const useSite = () => useContext(SiteContext);

export const SiteProvider = ({ children }) => {
  const [site, setSite] = useState(DEFAULTS);

  useEffect(() => {
    let cancelled = false;
    api.site.get()
      .then((data) => {
        if (cancelled) return;
        // Merge rather than replace: a key the API omits keeps its default
        // instead of blanking the page.
        setSite({ ...DEFAULTS, ...data, social: data.social || {} });
      })
      // The site has to render with or without this; the defaults stand in.
      .catch((err) => console.error('Load site content error:', err));
    return () => { cancelled = true; };
  }, []);

  // The tab is part of the branding too.
  useEffect(() => {
    if (site.brand_name) document.title = site.brand_name;
  }, [site.brand_name]);

  return <SiteContext.Provider value={site}>{children}</SiteContext.Provider>;
};

export default SiteContext;
