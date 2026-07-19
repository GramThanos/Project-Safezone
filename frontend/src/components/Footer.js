// Footer component
import React from 'react';

function Footer() {
  const currentYear = new Date().getFullYear();

  return (
    <footer className="bg-body-tertiary border-top mt-5 py-5">
      <div className="container">
        <div className="row gy-4">
          <div className="col-md-3">
            <h5 className="font-display">PROJECT SAFEZONE</h5>
            <p className="text-body-secondary">
              A Project Zomboid dedicated server web manager with a modern interface for managing servers, players, and tasks.
            </p>
          </div>

          <div className="col-md-3">
            <h6>Features</h6>
            <ul className="list-unstyled text-body-secondary">
              <li>Server Management</li>
              <li>Player Profiles</li>
              <li>Admin Panel</li>
              <li>Real-time Status</li>
            </ul>
          </div>

          <div className="col-md-3">
            <h6>Resources</h6>
            <ul className="list-unstyled text-body-secondary">
              <li>Documentation</li>
              <li>Support</li>
              <li>Community</li>
              <li>API</li>
            </ul>
          </div>

          <div className="col-md-3">
            <h6>Follow</h6>
            <div className="d-flex gap-2">
              <a className="btn btn-outline-secondary btn-sm" href="#"><i className="fab fa-discord"></i></a>
              <a className="btn btn-outline-secondary btn-sm" href="#"><i className="fab fa-twitter"></i></a>
              <a className="btn btn-outline-secondary btn-sm" href="#"><i className="fab fa-youtube"></i></a>
            </div>
          </div>
        </div>

        <hr className="my-4" />

        <div className="d-flex justify-content-between text-body-secondary align-items-center flex-wrap">
          <div>&copy; {currentYear} Project Safezone. All rights reserved.</div>
          <div>Terms • Privacy • Cookies</div>
        </div>
      </div>
    </footer>
  );
}

export default Footer;
