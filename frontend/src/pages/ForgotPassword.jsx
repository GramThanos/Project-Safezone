// Request a password reset link.
//
// The response is deliberately the same whether or not the address has an
// account, so this page cannot be used to find out who is registered. The copy
// below reflects that rather than promising an email that may not come.
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';
import usePageTitle from '../hooks/usePageTitle';

function ForgotPassword() {
  usePageTitle('Reset your password');
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await api.auth.forgotPassword(email.trim());
      setSent(true);
    } catch (err) {
      console.error('Forgot password error:', err);
      setError('Something went wrong. Try again in a moment.');
    }
    setLoading(false);
  };

  return (
    <section className="py-5" style={{ minHeight: '70vh' }}>
      <div className="container">
        <div className="row justify-content-center">
          <div className="col-md-6 col-lg-5">
            <div className="card">
              <div className="card-body p-4">
                <h2 className="card-title font-display text-center mb-4">Reset Password</h2>

                {error && <div className="alert alert-danger" role="alert">{error}</div>}

                {sent ? (
                  <>
                    <div className="alert alert-success">
                      If that address has an account, a reset link is on its way.
                      The link works once and expires in an hour.
                    </div>
                    <Link to="/signin" className="btn btn-outline-light w-100">
                      Back to sign in
                    </Link>
                  </>
                ) : (
                  <form onSubmit={handleSubmit}>
                    <p className="text-body-secondary">
                      Enter the address you signed up with and we will send you a
                      link to choose a new password.
                    </p>
                    <div className="mb-3">
                      <label htmlFor="email" className="form-label">Email</label>
                      <input
                        type="email"
                        className="form-control"
                        id="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                      />
                    </div>
                    <button type="submit" className="btn btn-danger w-100" disabled={loading}>
                      {loading ? 'Sending…' : 'Send reset link'}
                    </button>
                    <div className="text-center mt-3">
                      <Link to="/signin" className="text-body-secondary">Back to sign in</Link>
                    </div>
                  </form>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export default ForgotPassword;
