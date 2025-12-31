// Navbar component
import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

function Navbar() {
  const { user, signout, isModerator } = useAuth();
  const navigate = useNavigate();

  const handleSignout = () => {
    signout();
    navigate('/');
  };

  return (
    <nav className="navbar navbar-expand-lg navbar-dark py-3">
      <div className="container">
        <Link className="navbar-brand text-uppercase" to="/">Project Safezone</Link>
        <button 
          className="navbar-toggler" 
          type="button" 
          data-bs-toggle="collapse" 
          data-bs-target="#navMenu"
          aria-controls="navMenu" 
          aria-expanded="false" 
          aria-label="Toggle navigation"
        >
          <span className="navbar-toggler-icon"></span>
        </button>

        <div className="collapse navbar-collapse" id="navMenu">
          <ul className="navbar-nav ms-auto align-items-lg-center">
            <li className="nav-item">
              <Link className="nav-link" to="/">Home</Link>
            </li>
            <li className="nav-item">
              <Link className="nav-link" to="/servers">Servers</Link>
            </li>
            {user && (
              <>
                <li className="nav-item">
                  <Link className="nav-link" to="/players">My Players</Link>
                </li>
                {isModerator() && (
                  <li className="nav-item">
                    <Link className="nav-link" to="/admin">Admin Panel</Link>
                  </li>
                )}
                <li className="nav-item">
                  <Link className="nav-link" to="/profile">Profile ({user.username})</Link>
                </li>
                <li className="nav-item ms-lg-3">
                  <button className="btn btn-danger btn-sm" onClick={handleSignout}>
                    Sign out
                  </button>
                </li>
              </>
            )}
            {!user && (
              <li className="nav-item ms-lg-3">
                <Link className="btn btn-danger btn-sm" to="/signin">Sign in</Link>
              </li>
            )}
          </ul>
        </div>
      </div>
    </nav>
  );
}

export default Navbar;
