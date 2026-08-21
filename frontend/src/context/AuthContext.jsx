// Authentication context
import React, { createContext, useState, useContext, useEffect } from 'react';
import api from '../services/api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('token'));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check if user is logged in on mount
    const checkAuth = async () => {
      if (token) {
        try {
          const data = await api.auth.me(token);
          if (data.user) {
            setUser(data.user);
          } else {
            // Invalid token
            localStorage.removeItem('token');
            setToken(null);
          }
        } catch (error) {
          console.error('Auth check error:', error);
          localStorage.removeItem('token');
          setToken(null);
        }
      }
      setLoading(false);
    };

    checkAuth();
  }, [token]);

  const signin = async (username, password) => {
    try {
      const data = await api.auth.signin(username, password);
      if (data.token && data.user) {
        setToken(data.token);
        setUser(data.user);
        localStorage.setItem('token', data.token);
        return { success: true };
      } else {
        return { success: false, error: data.error || 'Sign in failed' };
      }
    } catch (error) {
      console.error('Sign in error:', error);
      return { success: false, error: 'Network error' };
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
