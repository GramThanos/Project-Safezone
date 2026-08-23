// Two-factor authentication controls for the profile.
//
// Off -> a password re-auth begins setup, which returns a QR (and the secret in
// text, for a device that cannot scan). Scanning it and confirming one code
// turns 2FA on. On -> a password plus a current code turns it back off.
//
// The QR is drawn from the otpauth:// URI as an inline SVG, so nothing loads
// cross-origin - the same stance the CAPTCHA takes, and what the strict
// Content-Security-Policy requires.
import React, { useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';

function TwoFactorSettings() {
  const { user, token, refresh } = useAuth();
  const enabled = !!user?.totp_enabled;

  // 'idle' | 'password' (enabling, entering password) | 'confirm' (QR shown,
  // entering the first code) | 'disable' (entering password + code).
  const [stage, setStage] = useState('idle');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [provisioning, setProvisioning] = useState(null); // { secret, otpauth_uri }
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setStage('idle');
    setPassword('');
    setCode('');
    setProvisioning(null);
    setError('');
  };

  const startSetup = async (e) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const data = await api.auth.twofa.setup(token, password);
      setProvisioning(data);
      setPassword('');
      setStage('confirm');
    } catch (err) {
      console.error('2FA setup error:', err);
      setError(err.message || 'Could not start setup');
    }
    setBusy(false);
  };

  const confirmEnable = async (e) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      await api.auth.twofa.enable(token, code.trim());
      await refresh();
      reset();
      setMsg('Two-factor authentication is on.');
    } catch (err) {
      console.error('2FA enable error:', err);
      setError(err.message || 'Could not turn on two-factor authentication');
    }
    setBusy(false);
  };

  const confirmDisable = async (e) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      await api.auth.twofa.disable(token, password, code.trim());
      await refresh();
      reset();
      setMsg('Two-factor authentication is off.');
    } catch (err) {
      console.error('2FA disable error:', err);
      setError(err.message || 'Could not turn off two-factor authentication');
    }
    setBusy(false);
  };

  return (
    <div className="card mb-4">
      <div className="card-body p-4">
        <h5 className="card-title font-display mb-3 d-flex align-items-center gap-2">
          Two-Factor Authentication
          {enabled ? (
            <span className="badge text-bg-success">on</span>
          ) : (
            <span className="badge text-bg-secondary">off</span>
          )}
        </h5>

        {msg && <div className="alert alert-success">{msg}</div>}
        {error && <div className="alert alert-danger">{error}</div>}

        {!enabled && stage === 'idle' && (
          <>
            <p className="text-body-secondary">
              Add a code from an authenticator app (Google Authenticator, Authy,
              1Password and the like) on top of your password when you sign in.
            </p>
            <button
              className="btn btn-outline-light"
              onClick={() => { setMsg(''); setError(''); setStage('password'); }}
            >
              Set up two-factor authentication
            </button>
          </>
        )}

        {!enabled && stage === 'password' && (
          <form onSubmit={startSetup}>
            <p className="text-body-secondary">
              Confirm your password to begin.
            </p>
            <div className="mb-3">
              <label className="form-label text-body-secondary">Your password</label>
              <input
                type="password"
                className="form-control"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoFocus
                required
              />
            </div>
            <div className="d-flex gap-2">
              <button type="submit" className="btn btn-danger" disabled={busy}>
                {busy ? 'Working…' : 'Continue'}
              </button>
              <button type="button" className="btn btn-outline-light" onClick={reset}>
                Cancel
              </button>
            </div>
          </form>
        )}

        {!enabled && stage === 'confirm' && provisioning && (
          <form onSubmit={confirmEnable}>
            <p className="text-body-secondary">
              Scan this with your authenticator app, then enter the 6-digit code
              it shows to switch 2FA on.
            </p>
            <div className="text-center mb-3">
              <span className="d-inline-block bg-white p-3 rounded">
                <QRCodeSVG value={provisioning.otpauth_uri} size={180} />
              </span>
            </div>
            <div className="mb-3">
              <label className="form-label text-body-secondary">
                Can’t scan? Enter this key by hand
              </label>
              <code className="d-block user-select-all text-break">
                {provisioning.secret}
              </code>
            </div>
            <div className="mb-3">
              <label className="form-label text-body-secondary">Authentication code</label>
              <input
                type="text"
                className="form-control"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength="6"
                autoFocus
                required
              />
            </div>
            <div className="d-flex gap-2">
              <button type="submit" className="btn btn-danger" disabled={busy}>
                {busy ? 'Verifying…' : 'Turn on'}
              </button>
              <button type="button" className="btn btn-outline-light" onClick={reset}>
                Cancel
              </button>
            </div>
          </form>
        )}

        {enabled && stage === 'idle' && (
          <>
            <p className="text-body-secondary">
              Your account asks for an authenticator code when you sign in. Lost
              your device? A server admin can turn this off so you can get back
              in.
            </p>
            <button
              className="btn btn-outline-danger"
              onClick={() => { setMsg(''); setError(''); setStage('disable'); }}
            >
              Turn off two-factor authentication
            </button>
          </>
        )}

        {enabled && stage === 'disable' && (
          <form onSubmit={confirmDisable}>
            <p className="text-body-secondary">
              Confirm with your password and a current code to turn 2FA off.
            </p>
            <div className="mb-3">
              <label className="form-label text-body-secondary">Your password</label>
              <input
                type="password"
                className="form-control"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoFocus
                required
              />
            </div>
            <div className="mb-3">
              <label className="form-label text-body-secondary">Authentication code</label>
              <input
                type="text"
                className="form-control"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength="6"
                required
              />
            </div>
            <div className="d-flex gap-2">
              <button type="submit" className="btn btn-danger" disabled={busy}>
                {busy ? 'Working…' : 'Turn off'}
              </button>
              <button type="button" className="btn btn-outline-light" onClick={reset}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export default TwoFactorSettings;
