// Terms / Privacy / Cookies. One component, three routes — the pages differ
// only in which document they load.
import React, { useState, useEffect } from 'react';
import api from '../services/api';
import Markdown from '../components/Markdown';
import usePageTitle from '../hooks/usePageTitle';

// The slug comes from the route element rather than a path param: three fixed
// pages, not a wildcard that would swallow every unknown URL on the site.
function LegalPage({ slug }) {
  const [page, setPage] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  usePageTitle(page?.title);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    api.site.page(slug)
      .then((data) => { if (!cancelled) setPage(data); })
      .catch((err) => {
        console.error('Load page error:', err);
        if (!cancelled) setError(err.message || 'Could not load this page');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [slug]);

  return (
    <section className="py-5" style={{ minHeight: '50vh' }}>
      <div className="container" style={{ maxWidth: '48rem' }}>
        <h2 className="text-uppercase font-display mb-4">
          {page?.title || 'Loading…'}
        </h2>

        {error && <div className="alert alert-danger">{error}</div>}

        {!loading && !error && !page?.markdown && (
          // Said plainly rather than dressed up: a blank policy page that
          // pretends to be a policy is worse than one that admits it is empty.
          <p className="text-body-secondary">
            This page has not been written yet.
          </p>
        )}

        {page?.markdown && <Markdown>{page.markdown}</Markdown>}
      </div>
    </section>
  );
}

export default LegalPage;
