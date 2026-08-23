// Profile: the account's own settings — password, address, sessions, and the
// two things a person is entitled to do with their own data (take it, or close
// the account).
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import usePageTitle from '../hooks/usePageTitle';
import ConfirmDialog from '../components/ConfirmDialog';
import TwoFactorSettings from '../components/TwoFactorSettings';

function Profile() {
  usePageTitle('Profile');
  // Which destructive action is awaiting confirmation: 'logout-all',
  // 'close', or null. The browser's own dialog cannot say what is about
  // to be lost, and on a phone it reads like a scam popup.
  const [confirming, setConfirming] = useState(null);
  const { user, token, adoptToken, refresh, signout } = useAuth();
  const navigate = useNavigate();

  const [form, setForm] = useState({ current: '', next: '', confirm: '' });
  const [emailForm, setEmailForm] = useState({ password: '', email: '' });
  const [closeForm, setCloseForm] = useState({ password: '', confirming: false });
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');

  const mustChange = !!user?.must_change_password;

  const getRoleBadge = (role) => {
    const roleMap = {
      admin: 'danger',
      moderator: 'warning',
      player: 'info',
      banned: 'secondary'
    };
    return roleMap[role] || 'secondary';
  };

  const reset = () => {
    setMsg('');
    setError('');
  };

  const handleChangePassword = async (e) => {
    e.preventDefault();
    reset();
    if (!form.current || !form.next) {
      setError('Enter your current and new password');
      return;
    }
    if (form.next.length < 8) {
      setError('New password must be at least 8 characters');
      return;
    }
    if (form.next !== form.confirm) {
      setError('New password and confirmation do not match');
      return;
    }
    try {
      const data = await api.auth.changePassword(token, form.current, form.next);
      // The change invalidated this browser's token too; take the fresh one so
      // the page keeps working.
      adoptToken(data.token, data.user);
      setForm({ current: '', next: '', confirm: '' });
      setMsg(data.message || 'Password updated.');
    } catch (err) {
      console.error('Change password error:', err);
      setError(err.message || 'Failed to change password');
    }
  };

  const handleResendVerification = async () => {
    reset();
    try {
      const data = await api.auth.requestVerification(token);
      setMsg(data.message || 'Confirmation sent.');
    } catch (err) {
      console.error('Resend verification error:', err);
      setError(err.message || 'Could not send that email');
    }
  };

  const handleChangeEmail = async (e) => {
    e.preventDefault();
    reset();
    try {
      const data = await api.auth.changeEmail(token, emailForm.password, emailForm.email.trim());
      setEmailForm({ password: '', email: '' });
      setMsg(data.message || 'Address changed.');
      refresh();
    } catch (err) {
      console.error('Change email error:', err);
      setError(err.message || 'Could not change that address');
    }
  };

  const handleLogoutEverywhere = async () => {
    setConfirming(null);
    reset();
    try {
      await api.auth.logoutEverywhere(token);
      signout();
      navigate('/signin', { replace: true });
    } catch (err) {
      console.error('Logout everywhere error:', err);
      setError(err.message || 'Could not sign out everywhere');
    }
  };

  const handleExport = async () => {
    reset();
    try {
      const data = await api.auth.exportAccount(token);
      // Hand it over as a file rather than dumping JSON on screen.
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `safezone-${user?.username || 'account'}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export error:', err);
      setError(err.message || 'Could not export your data');
    }
  };

  const handleCloseAccount = async (e) => {
    if (e?.preventDefault) e.preventDefault();
    // The password field is the first gate; the dialog is the second, and it
    // is where the consequences are spelled out.
    if (confirming !== 'close') {
      setConfirming('close');
      return;
    }
    setConfirming(null);
    reset();
    try {
      await api.auth.deleteAccount(token, closeForm.password);
      signout();
      navigate('/', { replace: true });
    } catch (err) {
      console.error('Close account error:', err);
      setError(err.message || 'Could not close the account');
    }
  };

  return (
    <>
    <section className="py-5" style={{ minHeight: '50vh' }}>
      <div className="container">
        <div className="row justify-content-center">
          <div className="col-md-8 col-lg-6">

            {mustChange && (
              <div className="alert alert-warning">
                <strong>Set a new password to continue.</strong> This account is
                still using its default password, so everything else is locked
                until it is changed.
              </div>
            )}

            {msg && <div className="alert alert-success">{msg}</div>}
            {error && <div className="alert alert-danger">{error}</div>}

            <div className="card mb-4">
              <div className="card-body p-4">
                <h2 className="card-title font-display text-center mb-4">User Profile</h2>

                <div className="mb-3">
                  <label className="text-body-secondary">Username</label>
                  <div className="h5">{user?.username}</div>
                </div>

                <div className="mb-3">
                  <label className="text-body-secondary">Email</label>
                  <div className="h5 d-flex align-items-center gap-2">
                    {user?.email}
                    {user?.email_verified ? (
                      <span className="badge text-bg-success">confirmed</span>
                    ) : (
                      <span className="badge text-bg-warning">unconfirmed</span>
                    )}
                  </div>
                  {!user?.email_verified && (
                    <button className="btn btn-sm btn-outline-light mt-2" onClick={handleResendVerification}>
                      Send confirmation email
                    </button>
                  )}
                </div>

                <div className="mb-3">
                  <label className="text-body-secondary">Role</label>
                  <div>
                    <span className={`badge text-bg-${getRoleBadge(user?.role)}`}>
                      {user?.role?.toUpperCase()}
                    </span>
                  </div>
                </div>

                <div className="mb-0">
                  <label className="text-body-secondary">Member Since</label>
                  <div>{user?.created_at ? new Date(user.created_at).toLocaleDateString() : 'N/A'}</div>
                </div>
              </div>
            </div>

            <div className="card mb-4">
              <div className="card-body p-4">
                <h5 className="card-title font-display mb-3">Change Password</h5>
                <form onSubmit={handleChangePassword}>
                  <div className="mb-3">
                    <label className="form-label text-body-secondary">Current password</label>
                    <input
                      type="password"
                      className="form-control"
                      value={form.current}
                      onChange={(e) => setForm({ ...form, current: e.target.value })}
                    />
                  </div>
                  <div className="mb-3">
                    <label className="form-label text-body-secondary">New password</label>
                    <input
                      type="password"
                      className="form-control"
                      value={form.next}
                      onChange={(e) => setForm({ ...form, next: e.target.value })}
                    />
                  </div>
                  <div className="mb-3">
                    <label className="form-label text-body-secondary">Confirm new password</label>
                    <input
                      type="password"
                      className="form-control"
                      value={form.confirm}
                      onChange={(e) => setForm({ ...form, confirm: e.target.value })}
                    />
                  </div>
                  <button type="submit" className="btn btn-danger w-100">Update Password</button>
                  <div className="form-text mt-2">
                    Changing your password signs out every other device.
                  </div>
                </form>
              </div>
            </div>

            {!mustChange && (
              <>
                <div className="card mb-4">
                  <div className="card-body p-4">
                    <h5 className="card-title font-display mb-3">Change Email</h5>
                    <form onSubmit={handleChangeEmail}>
                      <div className="mb-3">
                        <label className="form-label text-body-secondary">New address</label>
                        <input
                          type="email"
                          className="form-control"
                          value={emailForm.email}
                          onChange={(e) => setEmailForm({ ...emailForm, email: e.target.value })}
                          required
                        />
                      </div>
                      <div className="mb-3">
                        <label className="form-label text-body-secondary">Your password</label>
                        <input
                          type="password"
                          className="form-control"
                          value={emailForm.password}
                          onChange={(e) => setEmailForm({ ...emailForm, password: e.target.value })}
                          required
                        />
                      </div>
                      <button type="submit" className="btn btn-outline-light w-100">
                        Change address
                      </button>
                      <div className="form-text mt-2">
                        You will need to confirm the new address before it counts.
                      </div>
                    </form>
                  </div>
                </div>

                <TwoFactorSettings />

                <div className="card mb-4">
                  <div className="card-body p-4">
                    <h5 className="card-title font-display mb-3">Sessions &amp; Data</h5>
                    <div className="d-grid gap-2">
                      <button className="btn btn-outline-light" onClick={() => setConfirming('logout-all')}>
                        Sign out everywhere
                      </button>
                      <button className="btn btn-outline-light" onClick={handleExport}>
                        Download my data
                      </button>
                    </div>
                    <div className="form-text mt-2">
                      Signing out everywhere ends every session, including this one.
                    </div>
                  </div>
                </div>

                <div className="card border-danger">
                  <div className="card-body p-4">
                    <h5 className="card-title font-display mb-3 text-danger">Close Account</h5>
                    <p className="text-body-secondary">
                      Deletes your account, characters, loot and inventory. Your
                      in-game names are released for anyone to claim. This cannot
                      be undone.
                    </p>
                    {closeForm.confirming ? (
                      <form onSubmit={handleCloseAccount}>
                        <div className="mb-3">
                          <label className="form-label text-body-secondary">
                            Confirm with your password
                          </label>
                          <input
                            type="password"
                            className="form-control"
                            value={closeForm.password}
                            onChange={(e) => setCloseForm({ ...closeForm, password: e.target.value })}
                            required
                          />
                        </div>
                        <div className="d-flex gap-2">
                          <button type="submit" className="btn btn-danger">
                            Close my account
                          </button>
                          <button
                            type="button"
                            className="btn btn-outline-light"
                            onClick={() => setCloseForm({ password: '', confirming: false })}
                          >
                            Cancel
                          </button>
                        </div>
                      </form>
                    ) : (
                      <button
                        className="btn btn-outline-danger"
                        onClick={() => setCloseForm({ password: '', confirming: true })}
                      >
                        Close my account…
                      </button>
                    )}
                  </div>
                </div>
              </>
            )}

          </div>
        </div>
      </div>
    </section>

      {confirming === 'logout-all' && (
        <ConfirmDialog
          title="Sign out everywhere?"
          confirmLabel="Sign out everywhere"
          onCancel={() => setConfirming(null)}
          onConfirm={handleLogoutEverywhere}
        >
          <p className="mb-0">
            Every device signed in to this account is signed out, including this
            one. Nothing else changes — your characters, crates and rewards stay
            exactly as they are.
          </p>
        </ConfirmDialog>
      )}

      {confirming === 'close' && (
        <ConfirmDialog
          title="Close your account?"
          confirmLabel="Close my account"
          onCancel={() => setConfirming(null)}
          onConfirm={handleCloseAccount}
        >
          <p>This cannot be undone. When it is done:</p>
          <ul>
            <li>Your characters are unlinked, and their in-game names become claimable by anyone.</li>
            <li>Crates and anything in your inventory are gone.</li>
            <li>You will be signed out of every device.</li>
          </ul>
          <p className="mb-0 text-body-secondary">
            If you only want to step away, signing out is enough — nothing expires
            because you did not visit.
          </p>
        </ConfirmDialog>
      )}
    </>
  );
}

export default Profile;
