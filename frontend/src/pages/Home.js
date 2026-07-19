// Home page
import React from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const FEATURES = [
  {
    img: 'safezone-banner-1.png',
    ribbon: 'NEW',
    ribbonColor: 'danger',
    title: 'Manage Your Characters',
    desc: 'Create and manage multiple game characters. Customize your players and track their progress across different servers.'
  },
  {
    img: 'safezone-banner-2.png',
    ribbon: 'LIVE',
    ribbonColor: 'success',
    title: 'Real-Time Server Status',
    desc: 'Monitor server status, active players, and game progress in real-time. See which servers are online and join the action.'
  },
  {
    img: 'safezone-banner-3.png',
    ribbon: 'ADMIN',
    ribbonColor: 'warning',
    title: 'Admin Panel',
    desc: 'Moderators and admins can manage servers, tasks, and users through an intuitive admin panel with full control.'
  }
];

function Home() {
  const { user } = useAuth();
  const canAdmin = user && (user.role === 'admin' || user.role === 'moderator');

  return (
    <>
      {/* HERO — Bootstrap card with image overlay */}
      <div className="card text-bg-dark border-0 rounded-0">
        <img
          src="/assets/images/safezone-banner-8.png"
          className="card-img hero-img object-fit-cover rounded-0 opacity-50"
          alt="Survivors defending the safezone"
        />
        <div className="card-img-overlay d-flex flex-column justify-content-center align-items-center text-center">
          <div className="container" style={{ maxWidth: '820px' }}>
            <h1 className="display-4 fw-bold text-uppercase font-display">Time to Fight Zombies</h1>
            <p className="lead">
              Join our Project Zomboid dedicated servers and survive the apocalypse with your friends.
              Create your character, explore the world, and fight for survival in this multiplayer experience.
            </p>
            <div className="d-flex justify-content-center gap-3 mt-4">
              <Link className="btn btn-danger btn-lg" to={user ? '/players' : '/signin'}>
                {user ? 'My Players' : 'Sign In'}
              </Link>
              <Link className="btn btn-outline-light btn-lg" to="/servers">View Servers</Link>
            </div>
          </div>
        </div>
      </div>

      {/* FEATURES */}
      <section className="py-5">
        <div className="container">
          <div className="row g-4">
            {FEATURES.map((f) => (
              <div key={f.title} className="col-md-4">
                <div className="card h-100">
                  <div className="position-relative">
                    <img
                      src={`/assets/images/${f.img}`}
                      className="card-img-top card-banner object-fit-cover"
                      alt={f.title}
                    />
                    <span className={`badge text-bg-${f.ribbonColor} position-absolute top-0 end-0 m-2`}>
                      {f.ribbon}
                    </span>
                  </div>
                  <div className="card-body d-flex flex-column">
                    <h5 className="card-title font-display">{f.title}</h5>
                    <p className="card-text text-body-secondary flex-grow-1">{f.desc}</p>
                    {f.ribbon === 'ADMIN' ? (
                      canAdmin ? (
                        <Link className="btn btn-outline-light btn-sm align-self-start" to="/admin">Admin Panel</Link>
                      ) : (
                        <button className="btn btn-outline-secondary btn-sm align-self-start" disabled>Requires Access</button>
                      )
                    ) : (
                      <Link
                        className="btn btn-outline-light btn-sm align-self-start"
                        to={f.ribbon === 'LIVE' ? '/servers' : (user ? '/players' : '/signin')}
                      >
                        {f.ribbon === 'LIVE' ? 'View Servers' : 'Get Started'}
                      </Link>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CALL TO ACTION */}
      <section className="py-5 border-top">
        <div className="container text-center">
          <h3 className="text-uppercase font-display mb-3">Join the Safezone</h3>
          <p className="text-body-secondary mb-4">
            Create an account today and start your survival journey
          </p>
          {!user && (
            <Link className="btn btn-danger btn-lg" to="/signin">Sign Up Now</Link>
          )}
        </div>
      </section>
    </>
  );
}

export default Home;
