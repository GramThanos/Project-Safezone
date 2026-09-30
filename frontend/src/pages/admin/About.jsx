// Admin › System › About: what this install is, and whether its parts are up.
//
// The landing page of the System section, so the first thing an operator sees
// on arriving is the build they are looking at and the state of what it depends
// on — the two questions worth answering before touching anything else.
import React, { useState, useEffect } from 'react';
import api from '../../services/api';

// Bootstrap contextual colour for a dependency's state.
const dotColour = (value) => {
  if (value === 'connected' || value === 'running' || value === 'healthy') return 'success';
  if (!value || value === 'unknown') return 'secondary';
  return 'danger';
};

const DEPENDENCIES = [
  ['Database', 'database', 'MariaDB — accounts, characters, rewards, the audit log.'],
  ['Cache', 'cache', 'Redis — live server state, the online roster, signup CAPTCHAs.'],
  ['Game server', 'game_server', 'The orchestrator that runs and watches the game processes.']
];

function About() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    api.health()
      .then((data) => { if (!cancelled) setHealth(data); })
      .catch((err) => {
        console.error('Health check error:', err);
        if (!cancelled) setError('Could not reach the API to read its status.');
      });
    return () => { cancelled = true; };
  }, []);

  return (
    <>
      <h4 className="font-display mb-3">About</h4>

      {error && <div className="alert alert-warning" role="alert">{error}</div>}

      <div className="row g-3">
        <div className="col-lg-6">
          <div className="card h-100">
            <div className="card-body">
              <h5 className="card-title font-display">Project Safezone</h5>
              <p className="text-body-secondary">
                A web manager for Project Zomboid dedicated servers: it runs the
                servers, links in-game characters to site accounts, and hands out
                rewards through the game's own console.
              </p>
              <dl className="row mb-0">
                <dt className="col-sm-4 text-body-secondary fw-normal">Version</dt>
                <dd className="col-sm-8 mb-0 font-monospace">{health?.version || '—'}</dd>
              </dl>
            </div>
          </div>
        </div>

        <div className="col-lg-6">
          <div className="card h-100">
            <div className="card-body">
              <h5 className="card-title font-display">Services</h5>
              <ul className="list-unstyled mb-0">
                {DEPENDENCIES.map(([label, key, description]) => (
                  <li key={key} className="mb-3">
                    <div className="d-flex align-items-center gap-2">
                      <i
                        className={`fas fa-circle text-${dotColour(health?.[key])}`}
                        style={{ fontSize: '0.5rem' }}
                      ></i>
                      <span className="fw-bold">{label}</span>
                      <span className="font-monospace text-body-secondary small">
                        {health?.[key] || 'unknown'}
                      </span>
                    </div>
                    <div className="text-body-secondary small ms-3">{description}</div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

export default About;
