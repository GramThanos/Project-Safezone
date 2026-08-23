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
  // Opt-in: strip 2FA as part of this reset, for someone who lost their
  // authenticator. Nothing is cleared until the new password is submitted.
  const [clearTwoFactor, setClearTwoFactor] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  // A reset on a 2FA account changes the password but still owes a code before
  // it hands back a session; this holds that challenge while it is entered.
  const [mfaToken, setMfaToken] = useState(null);
  const [mfaCode, setMfaCode] = useState('');

  const { adoptToken, completeMfaSignin } = useAuth();
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
      const data = await api.auth.resetPassword(resetToken, password, clearTwoFactor);
      if (data.mfa_required && data.mfa_token) {
        // The password is set, but 2FA still has to clear before there is a
        // session - a reset link only proves email control.
        setMfaToken(data.mfa_token);
        setMfaCode('');
      } else {
        // The reset signs you in, so there is no second step.
        adoptToken(data.token, data.user);
        navigate('/', { replace: true });
      }
    } catch (err) {
      console.error('Reset password error:', err);
      setError(err.message || 'That reset link is expired or already used');
    }
    setLoading(false);
  };

  const handleVerifyMfa = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    const result = await completeMfaSignin(mfaToken, mfaCode.trim());
    if (result.success) {
      navigate('/', { replace: true });
    } else if (result.expired) {
      // The short-lived challenge died. The password was already changed, so
      // point them at a normal sign-in rather than another reset.
      setError('That took too long. Your password was changed — please sign in.');
      navigate('/signin', { replace: true });
    } else {
      setError(result.error);
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

                {mfaToken ? (
                  <form onSubmit={handleVerifyMfa}>
                    <p className="text-body-secondary">
                      Your password is set. Enter the 6-digit code from your
                      authenticator app to finish.
                    </p>
                    <div className="mb-3">
                      <label htmlFor="mfaCode" className="form-label">Authentication code</label>
                      <input
                        type="text"
                        className="form-control"
                        id="mfaCode"
                        value={mfaCode}
                        onChange={(e) => setMfaCode(e.target.value)}
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        pattern="[0-9]*"
                        maxLength="6"
                        autoFocus
                        required
                      />
                    </div>
                    <button type="submit" className="btn btn-danger w-100" disabled={loading}>
                      {loading ? 'Verifying…' : 'Verify'}
                    </button>
                  </form>
                ) : !resetToken ? (
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
                    <div className="form-check mb-3">
                      <input
                        type="checkbox"
                        className="form-check-input"
                        id="clearTwoFactor"
                        checked={clearTwoFactor}
                        onChange={(e) => setClearTwoFactor(e.target.checked)}
                      />
                      <label className="form-check-label" htmlFor="clearTwoFactor">
                        Also turn off two-factor authentication
                      </label>
                      <div className="form-text">
                        Check this only if you lost your authenticator app. It
                        takes effect when you set the new password.
                      </div>
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
