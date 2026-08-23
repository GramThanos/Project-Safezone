// Sign in/Sign up page
import React, { useState, useEffect } from 'react';
import { Link, useNavigate, useLocation, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import usePageTitle from '../hooks/usePageTitle';

function SignIn() {
  usePageTitle('Sign in');
  const [params] = useSearchParams();
  const location = useLocation();
  // An invitation link lands here with the code in the query, and should open
  // straight onto the sign-up form rather than making the person find the toggle.
  const inviteFromLink = params.get('invite') || '';

  const [isSignUp, setIsSignUp] = useState(
    !!inviteFromLink || location.pathname === '/signup'
  );
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [registrationPassword, setRegistrationPassword] = useState('');
  const [inviteCode, setInviteCode] = useState(inviteFromLink);
  const [captcha, setCaptcha] = useState(null);
  const [captchaAnswer, setCaptchaAnswer] = useState('');
  // What the server says signing up currently requires.
  const [gate, setGate] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // When the account has 2FA on, the password step hands back a challenge
  // instead of a session; this holds it while the code is entered.
  const [mfaToken, setMfaToken] = useState(null);
  const [mfaCode, setMfaCode] = useState('');

  const { signin, completeMfaSignin, signup } = useAuth();
  const navigate = useNavigate();

  const from = location.state?.from?.pathname || '/';

  useEffect(() => {
    // Cheap and public; knowing the gate up front avoids a pointless rejection.
    api.auth.registrationStatus()
      .then(setGate)
      .catch((err) => console.error('Registration status error:', err));
  }, []);

  // A challenge is consumed by one attempt, so it is fetched when the sign-up
  // form appears and replaced after every failure.
  const loadCaptcha = () => {
    api.auth.captcha()
      .then((data) => setCaptcha(data.enabled ? data : null))
      .catch((err) => console.error('Captcha error:', err));
  };

  useEffect(() => {
    if (isSignUp && gate?.captcha_required) loadCaptcha();
  }, [isSignUp, gate?.captcha_required]);

  // With an invitation, registration being closed does not apply.
  const usingInvite = !!inviteCode.trim();
  const signupBlocked = gate && !gate.enabled && !(gate.invites_enabled && usingInvite);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    if (isSignUp) {
      const extra = {};
      if (inviteCode.trim()) extra.invite_code = inviteCode.trim();
      if (registrationPassword) extra.registration_password = registrationPassword;
      if (captcha) {
        extra.captcha_id = captcha.id;
        extra.captcha_answer = captchaAnswer;
      }
      const result = await signup(username, email, password, extra);
      if (result.success) {
        navigate(from, { replace: true });
      } else {
        setError(result.error);
        // The old challenge is spent whether or not the answer was right.
        if (captcha) {
          setCaptchaAnswer('');
          loadCaptcha();
        }
      }
    } else {
      const result = await signin(username, password);
      if (result.success) {
        navigate(from, { replace: true });
      } else if (result.mfaRequired) {
        // Password was right; move to the code step.
        setMfaToken(result.mfaToken);
        setMfaCode('');
      } else {
        setError(result.error);
      }
    }

    setLoading(false);
  };

  const handleVerifyMfa = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    const result = await completeMfaSignin(mfaToken, mfaCode.trim());
    if (result.success) {
      navigate(from, { replace: true });
    } else if (result.expired) {
      // The challenge died; send them back to the password step.
      setMfaToken(null);
      setMfaCode('');
      setPassword('');
      setError(result.error);
    } else {
      setError(result.error);
    }
    setLoading(false);
  };

  const cancelMfa = () => {
    setMfaToken(null);
    setMfaCode('');
    setPassword('');
    setError('');
  };

  return (
    <section className="py-5" style={{ minHeight: '70vh' }}>
      <div className="container">
        <div className="row justify-content-center">
          <div className="col-md-6 col-lg-5">
            <div className="card">
              <div className="card-body p-4">
              <h2 className="card-title font-display text-center mb-4">
                {mfaToken ? 'Two-Step Verification' : (isSignUp ? 'Create Account' : 'Sign In')}
              </h2>

              {error && (
                <div className="alert alert-danger" role="alert">
                  {error}
                </div>
              )}

              {mfaToken ? (
                <form onSubmit={handleVerifyMfa}>
                  <p className="text-body-secondary">
                    Enter the 6-digit code from your authenticator app to finish
                    signing in.
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
                  <button
                    type="submit"
                    className="btn btn-danger w-100 mb-3"
                    disabled={loading}
                  >
                    {loading ? 'Verifying…' : 'Verify'}
                  </button>
                  <div className="text-center">
                    <button type="button" className="btn btn-link" onClick={cancelMfa}>
                      Back to sign in
                    </button>
                  </div>
                </form>
              ) : (
              <form onSubmit={handleSubmit}>
                <div className="mb-3">
                  <label htmlFor="username" className="form-label">Username</label>
                  <input
                    type="text"
                    className="form-control"
                    id="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                  />
                </div>

                {isSignUp && (
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
                )}

                <div className="mb-3">
                  <label htmlFor="password" className="form-label">Password</label>
                  <input
                    type="password"
                    className="form-control"
                    id="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </div>

                {isSignUp && gate?.password_required && !usingInvite && (
                  <div className="mb-3">
                    <label htmlFor="registrationPassword" className="form-label">
                      Registration password
                    </label>
                    <input
                      type="password"
                      className="form-control"
                      id="registrationPassword"
                      value={registrationPassword}
                      onChange={(e) => setRegistrationPassword(e.target.value)}
                      required
                    />
                    <div className="form-text">
                      This server asks for a shared password to sign up. Ask an
                      admin if you do not have it.
                    </div>
                  </div>
                )}

                {isSignUp && gate?.invites_enabled && (
                  <div className="mb-3">
                    <label htmlFor="inviteCode" className="form-label">
                      Invitation code {gate.enabled ? '(optional)' : ''}
                    </label>
                    <input
                      type="text"
                      className="form-control"
                      id="inviteCode"
                      value={inviteCode}
                      onChange={(e) => setInviteCode(e.target.value)}
                      required={!gate.enabled}
                    />
                  </div>
                )}

                {isSignUp && captcha && (
                  <div className="mb-3">
                    <label htmlFor="captchaAnswer" className="form-label">
                      Type the code
                    </label>
                    <div className="d-flex align-items-center gap-2 mb-2">
                      <img
                        src={`data:image/svg+xml;utf8,${encodeURIComponent(captcha.image)}`}
                        alt="verification code"
                        style={{ borderRadius: '4px' }}
                      />
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-light"
                        onClick={() => { setCaptchaAnswer(''); loadCaptcha(); }}
                        title="Show a different code"
                      >
                        <i className="fas fa-sync-alt"></i>
                      </button>
                    </div>
                    <input
                      type="text"
                      className="form-control"
                      id="captchaAnswer"
                      value={captchaAnswer}
                      onChange={(e) => setCaptchaAnswer(e.target.value)}
                      autoComplete="off"
                      required
                    />
                  </div>
                )}

                {isSignUp && signupBlocked && (
                  <div className="alert alert-warning">
                    Registration is closed at the moment. You need an invitation
                    link to create an account.
                  </div>
                )}

                <button
                  type="submit"
                  className="btn btn-danger w-100 mb-3"
                  disabled={loading || (isSignUp && signupBlocked)}
                >
                  {loading ? 'Loading...' : (isSignUp ? 'Sign Up' : 'Sign In')}
                </button>
              </form>
              )}

              {!mfaToken && !isSignUp && (
                <div className="text-center">
                  <Link to="/forgot-password" className="text-body-secondary">
                    Forgot your password?
                  </Link>
                </div>
              )}

              {!mfaToken && (
              <div className="text-center">
                <button
                  className="btn btn-link"
                  onClick={() => {
                    setIsSignUp(!isSignUp);
                    setError('');
                  }}
                >
                  {isSignUp ? 'Already have an account? Sign In' : "Don't have an account? Sign Up"}
                </button>
              </div>
              )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export default SignIn;
