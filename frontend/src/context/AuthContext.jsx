// Authentication context
//
// The session is checked with the server - on opening, on coming back to the
// tab, and every few minutes while it is on screen - and that one call does
// three jobs: it notices a session that ended elsewhere (a password change,
// "sign out everywhere", a deleted account) and signs out here; it brings the
// account up to date (a ban, a new role); and it keeps the session alive.
// Sessions slide - they last from their last use, not from the sign-in - so a
// check hands back a fresh token once the current one is getting old. The
// installed app gets a longer lifetime than the website (`isInstalled` in
// services/api).
import React, { createContext, useState, useContext, useEffect, useRef } from 'react';
import api from '../services/api';
import { rebindPush, releasePush } from '../services/push';

const AuthContext = createContext(null);

// How often the session is checked while the site is on screen, and the least
// time between two checks - opening the app and focusing it should not ask twice.
const CHECK_EVERY_MS = 5 * 60 * 1000;
const CHECK_GAP_MS = 60 * 1000;
// The session this device's push subscription was last bound to.
const PUSH_SESSION_KEY = 'safezone.push.session';

// The token's claims, read without verifying - only for the session id.
const claimsOf = (token) => {
  try {
    return JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
  } catch (err) {
    return null;
  }
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('token'));
  const [loading, setLoading] = useState(true);

  // Read by the check without making it re-run whenever the account changes.
  const userRef = useRef(user);
  userRef.current = user;
  const lastCheck = useRef(0);

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return undefined;
    }
    let cancelled = false;

    const check = async () => {
      // With no account loaded yet this is the check on opening, and always
      // runs; after that, only while on screen and not twice in quick
      // succession - which also covers the re-run a renewed token causes.
      const opening = !userRef.current;
      if (!opening && document.visibilityState !== 'visible') return;
      if (!opening && Date.now() - lastCheck.current < CHECK_GAP_MS) return;
      lastCheck.current = Date.now();

      try {
        const data = await api.auth.refresh(token);
        if (cancelled) return;
        if (data.user) setUser(data.user);
        if (data.token && data.token !== token) {
          localStorage.setItem('token', data.token);
          setToken(data.token);
        }
      } catch (error) {
        console.error('Session check error:', error);
        // Only abandon the session when the server actually rejected the
        // token (401). A transient failure - the backend still warming up on
        // first boot, a network blip - must not discard a token that is still
        // valid: doing so left the just-signed-in user with a live `user` but
        // no token, so their next request went out as `Bearer null` and came
        // back "Token is invalid or expired". This bit the seeded admin on
        // first login, whose very first action is the forced password change.
        if (!cancelled && error.status === 401) {
          localStorage.removeItem('token');
          setToken(null);
          setUser(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    check();
    document.addEventListener('visibilitychange', check);
    const timer = setInterval(check, CHECK_EVERY_MS);
    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', check);
      clearInterval(timer);
    };
  }, [token]);

  // Another tab refreshed the session, or signed out: follow it, rather than
  // carry on with a token that tab has moved past.
  useEffect(() => {
    const onStorage = (event) => {
      if (event.key !== 'token') return;
      setToken(event.newValue);
      if (!event.newValue) setUser(null);
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  // A new session (a sign-in, not a refresh, which keeps the session id) takes
  // over this device's push subscription, which the server only honours for
  // the session it was made in.
  useEffect(() => {
    const sid = token && claimsOf(token)?.sid;
    if (!sid || localStorage.getItem(PUSH_SESSION_KEY) === sid) return;
    rebindPush(token).then((done) => {
      if (done) localStorage.setItem(PUSH_SESSION_KEY, sid);
    });
  }, [token]);

  // Adopt a session from any endpoint that hands one back (sign-in, the second
  // 2FA step, a reset that had no second factor).
  const establishSession = (data) => {
    setToken(data.token);
    setUser(data.user);
    localStorage.setItem('token', data.token);
    return { success: true };
  };

  const signin = async (username, password) => {
    try {
      const data = await api.auth.signin(username, password);
      // With 2FA on, the password step returns a challenge rather than a
      // session. Hand it back so the page can ask for a code; no token is
      // stored until the second step clears.
      if (data.mfa_required && data.mfa_token) {
        return { success: false, mfaRequired: true, mfaToken: data.mfa_token };
      }
      if (data.token && data.user) {
        return establishSession(data);
      }
      return { success: false, error: data.error || 'Sign in failed' };
    } catch (error) {
      console.error('Sign in error:', error);
      return { success: false, error: error.message || 'Network error' };
    }
  };

  // Second step of a 2FA sign-in: the challenge token from `signin` plus a
  // current code, in exchange for a real session.
  const completeMfaSignin = async (mfaToken, code) => {
    try {
      const data = await api.auth.signinVerify2fa(mfaToken, code);
      if (data.token && data.user) {
        return establishSession(data);
      }
      return { success: false, error: data.error || 'Sign in failed' };
    } catch (error) {
      console.error('2FA sign in error:', error);
      return {
        success: false,
        error: error.message || 'Network error',
        // A dead or expired challenge means starting over from the password.
        expired: error.status === 401 && /expired/i.test(error.message || '')
      };
    }
  };

  const signup = async (username, email, password, extra = {}) => {
    try {
      const data = await api.auth.signup(username, email, password, extra);
      if (data.token && data.user) {
        setToken(data.token);
        setUser(data.user);
        localStorage.setItem('token', data.token);
        return { success: true };
      } else {
        return { success: false, error: data.error || 'Sign up failed' };
      }
    } catch (error) {
      console.error('Sign up error:', error);
      return { success: false, error: 'Network error' };
    }
  };

  const signout = () => {
    // Turned off on both sides, so whoever signs in here next starts without
    // somebody else's reminders.
    releasePush(token);
    localStorage.removeItem(PUSH_SESSION_KEY);
    setUser(null);
    setToken(null);
    localStorage.removeItem('token');
  };

  // Changing a password ends every other session, which includes this browser's
  // token. The server hands back a fresh one so the user is not thrown out of
  // the page they are standing on; adopt it here.
  const adoptToken = (newToken, newUser) => {
    if (newToken) {
      setToken(newToken);
      localStorage.setItem('token', newToken);
    }
    if (newUser) setUser(newUser);
  };

  // True while the account is barred from everything but setting a new password.
  const mustChangePassword = () => !!user?.must_change_password;

  // Re-read the account after something server-side changed it (verifying an
  // address, clearing a forced password change).
  const refresh = async () => {
    if (!token) return;
    try {
      const data = await api.auth.me(token);
      if (data.user) setUser(data.user);
    } catch (error) {
      console.error('Account refresh error:', error);
    }
  };

  const isAdmin = () => {
    return user?.role === 'admin';
  };

  const isModerator = () => {
    return user?.role === 'moderator' || user?.role === 'admin';
  };

  const value = {
    user,
    token,
    loading,
    signin,
    completeMfaSignin,
    signup,
    signout,
    adoptToken,
    refresh,
    mustChangePassword,
    isAdmin,
    isModerator
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};
