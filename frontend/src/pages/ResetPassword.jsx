// Set a new password from a mailed link (/reset-password?token=…).
import React, { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import usePageTitle from '../hooks/usePageTitle';

function ResetPassword() {
  usePageTitle('Choose a new password');
  const [params] = useSearchParams();
  const resetToken = params.get('token') || '';

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const { adoptToken } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (password !== confirm) {
      setError('Those passwords do not match');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }

    setLoading(true);
    try {
      const data = await api.auth.resetPassword(resetToken, password);
      // The reset signs you in, so there is no second step.
      adoptToken(data.token, data.user);
      navigate('/', { replace: true });
    } catch (err) {
      console.error('Reset password error:', err);
      setError(err.message || 'That reset link is expired or already used');
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
                <h2 className="card-title font-display text-center mb-4">Choose a Password</h2>

                {error && <div className="alert alert-danger" role="alert">{error}</div>}

                {!resetToken ? (
                  <>
                    <div className="alert alert-warning">
                      This link is missing its token. Open the link from your email
                      exactly as it was sent.
                    </div>
                    <Link to="/forgot-password" className="btn btn-outline-light w-100">
                      Request a new link
                    </Link>
                  </>
                ) : (
                  <form onSubmit={handleSubmit}>
                    <div className="mb-3">
                      <label htmlFor="password" className="form-label">New password</label>
                      <input
                        type="password"
                        className="form-control"
                        id="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        minLength="8"
                        required
                      />
                      <div className="form-text">At least 8 characters.</div>
                    </div>
                    <div className="mb-3">
                      <label htmlFor="confirm" className="form-label">Repeat it</label>
                      <input
                        type="password"
                        className="form-control"
                        id="confirm"
                        value={confirm}
                        onChange={(e) => setConfirm(e.target.value)}
                        required
                      />
                    </div>
                    <button type="submit" className="btn btn-danger w-100" disabled={loading}>
                      {loading ? 'Saving…' : 'Set password'}
                    </button>
                    <p className="form-text mt-3 mb-0">
                      Setting a new password signs out every other device.
                    </p>
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

export default ResetPassword;
