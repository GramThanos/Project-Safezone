// Confirm an email address from a mailed link (/verify?token=…).
//
// Deliberately works without being signed in: people open mail on whichever
// device is to hand, which is often not the one they signed up on.
import React, { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import usePageTitle from '../hooks/usePageTitle';

function VerifyEmail() {
  usePageTitle('Confirm your email');
  const [params] = useSearchParams();
  const verifyToken = params.get('token') || '';

  const [state, setState] = useState(verifyToken ? 'working' : 'missing');
  const [error, setError] = useState('');
  const { token, refresh } = useAuth();

  // StrictMode mounts effects twice in development; the token is single-use, so
  // a second call would report "already used" on a perfectly good link.
  const attempted = useRef(false);

  useEffect(() => {
    if (!verifyToken || attempted.current) return;
    attempted.current = true;

    (async () => {
      try {
        await api.auth.verifyEmail(verifyToken);
        setState('done');
        if (token) refresh();
      } catch (err) {
        console.error('Verify email error:', err);
        setError(err.message || 'That confirmation link is expired or already used');
        setState('failed');
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [verifyToken]);

  return (
    <section className="py-5" style={{ minHeight: '70vh' }}>
      <div className="container">
        <div className="row justify-content-center">
          <div className="col-md-6 col-lg-5">
            <div className="card">
              <div className="card-body p-4 text-center">
                <h2 className="card-title font-display mb-4">Confirm Address</h2>

                {state === 'working' && (
                  <p className="text-body-secondary">Confirming…</p>
                )}

                {state === 'missing' && (
                  <div className="alert alert-warning mb-0">
                    This link is missing its token. Open the link from your email
                    exactly as it was sent.
                  </div>
                )}

                {state === 'done' && (
                  <>
                    <div className="alert alert-success">Your address is confirmed.</div>
                    <Link to="/" className="btn btn-danger w-100">Continue</Link>
                  </>
                )}

                {state === 'failed' && (
                  <>
                    <div className="alert alert-danger">{error}</div>
                    <p className="text-body-secondary">
                      You can send yourself a fresh link from your profile.
                    </p>
                    <Link to="/profile" className="btn btn-outline-light w-100">
                      Go to profile
                    </Link>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export default VerifyEmail;
