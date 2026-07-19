// Admin section layout: grouped sidebar navigation + routed sub-page outlet.
import React from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

// Nav groups. `adminOnly` links are hidden from moderators.
const NAV_GROUPS = [
  {
    label: 'Servers',
    links: [
      { to: '/admin/servers', text: 'Servers' },
      { to: '/admin/tasks', text: 'Tasks' }
    ]
  },
  {
    label: 'Users',
    links: [
      { to: '/admin/users', text: 'Users', adminOnly: true },
      { to: '/admin/claims', text: 'Claims' }
    ]
  },
  {
    label: 'Rewards',
    links: [
      { to: '/admin/rewards', text: 'Rewards' },
      { to: '/admin/boxes', text: 'Loot Boxes' },
      { to: '/admin/give', text: 'Give Item' }
    ]
  },
  {
    label: 'System',
    links: [
      { to: '/admin/audit', text: 'Audit Log' }
    ]
  }
];

function AdminLayout() {
  const { isAdmin, isModerator } = useAuth();

  if (!isModerator()) {
    return (
      <section className="py-5" style={{ minHeight: '50vh' }}>
        <div className="container text-center">
          <h2>Access Denied</h2>
          <p className="text-body-secondary">You do not have permission to access the admin panel.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="py-5" style={{ minHeight: '50vh' }}>
      <div className="container">
        <h2 className="mb-4 text-uppercase font-display">Admin Panel</h2>

        <div className="row g-4">
          {/* Grouped sidebar navigation */}
          <div className="col-lg-3">
            <nav className="nav nav-pills flex-column">
              {NAV_GROUPS.map((group) => {
                const links = group.links.filter((l) => !l.adminOnly || isAdmin());
                if (links.length === 0) return null;
                return (
                  <React.Fragment key={group.label}>
                    <span className="text-body-secondary text-uppercase small fw-bold mt-3 mb-1 px-3">
                      {group.label}
                    </span>
                    {links.map((link) => (
                      <NavLink key={link.to} to={link.to} className="nav-link">
                        {link.text}
                      </NavLink>
                    ))}
                  </React.Fragment>
                );
              })}
            </nav>
          </div>

          {/* Active sub-page */}
          <div className="col-lg-9">
            <Outlet />
          </div>
        </div>
      </div>
    </section>
  );
}

export default AdminLayout;
