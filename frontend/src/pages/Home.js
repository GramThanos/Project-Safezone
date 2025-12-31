// Home page
import React from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

function Home() {
  const { user } = useAuth();

  return (
    <>
      {/* HERO */}
      <section className="hero">
        <div className="hero-bg" role="img" aria-label="Hero background"></div>
        <div className="hero-inner container">
          <h1>TIME TO FIGHT ZOMBIES</h1>
          <p className="lead">
            Join our Project Zomboid dedicated servers and survive the apocalypse with your friends. 
            Create your character, explore the world, and fight for survival in this multiplayer experience.
          </p>

          <div className="d-flex justify-content-center gap-3 mt-4">
            {user ? (
              <>
                <Link className="btn btn-accent btn-lg" to="/players">My Players</Link>
                <Link className="btn btn-outline-light btn-lg" to="/servers">View Servers</Link>
              </>
            ) : (
              <>
                <Link className="btn btn-accent btn-lg" to="/signin">Sign In</Link>
                <Link className="btn btn-outline-light btn-lg" to="/servers">View Servers</Link>
              </>
            )}
          </div>
        </div>
      </section>

      {/* FEATURES */}
      <section className="py-5">
        <div className="container">
          <div className="row g-4">
            <div className="col-md-4">
              <div className="character-card">
                <div>
                  <div className="avatar" style={{ backgroundImage: "url('./assets/images/safezone-banner-1.png')" }}>
                    <div className="ribbon">NEW</div>
                  </div>
                  <div className="character-title">Manage Your Characters</div>
                  <div className="character-desc">
                    Create and manage multiple game characters. Customize your players and track their progress 
                    across different servers.
                  </div>
                </div>
                <div className="mt-3 d-flex gap-2">
                  <Link className="btn btn-light btn-sm" to={user ? "/players" : "/signin"}>
                    Get Started
                  </Link>
                </div>
              </div>
            </div>

            <div className="col-md-4">
              <div className="character-card">
                <div>
                  <div className="avatar" style={{ backgroundImage: "url('./assets/images/safezone-banner-2.png')" }}>
                    <div className="ribbon">LIVE</div>
                  </div>
                  <div className="character-title">Real-Time Server Status</div>
                  <div className="character-desc">
                    Monitor server status, active players, and game progress in real-time. 
                    See which servers are online and join the action.
                  </div>
                </div>
                <div className="mt-3 d-flex gap-2">
                  <Link className="btn btn-light btn-sm" to="/servers">View Servers</Link>
                </div>
              </div>
            </div>

            <div className="col-md-4">
              <div className="character-card">
                <div>
                  <div className="avatar" style={{ backgroundImage: "url('./assets/images/safezone-banner-3.png')" }}>
                    <div className="ribbon">ADMIN</div>
                  </div>
                  <div className="character-title">Admin Panel</div>
                  <div className="character-desc">
                    Moderators and admins can manage servers, tasks, and users through an intuitive 
                    admin panel with full control.
                  </div>
                </div>
                <div className="mt-3 d-flex gap-2">
                  {user && (user.role === 'admin' || user.role === 'moderator') ? (
                    <Link className="btn btn-light btn-sm" to="/admin">Admin Panel</Link>
                  ) : (
                    <button className="btn btn-outline-light btn-sm" disabled>Requires Access</button>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CALL TO ACTION */}
      <section className="py-5" style={{ borderTop: '1px solid rgba(255,255,255,0.02)' }}>
        <div className="container text-center">
          <h3 style={{ fontFamily: "'Oswald', sans-serif", letterSpacing: '0.6px', marginBottom: '1rem' }}>
            JOIN THE SAFEZONE
          </h3>
          <p className="small-muted mb-4">
            Create an account today and start your survival journey
          </p>
          {!user && (
            <Link className="btn btn-accent btn-lg" to="/signin">Sign Up Now</Link>
          )}
        </div>
      </section>
    </>
  );
}

export default Home;
