// Admin section layout: the admin navbar, plus the routed sub-page.
//
// The panel deliberately looks unlike the player site. Same app, different job:
// the site is a dark game-themed page you browse, the panel is a light
// workbench you operate, and the change of skin is the reminder that what you
// click here affects everybody. Two consequences:
//
//   - It is the *only* navbar here. The site's own bar hides itself in this
//     section (see `Navbar`), and the brand below leads back out to the site.
//   - The light theme is set on <html>, not on a wrapper, so the whole page
//     changes - footer, scrollbars and any Bootstrap layer that renders
//     outside this tree included.
import React, { useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useSite } from '../../context/SiteContext';
import SubNav from '../../components/SubNav';
import api from '../../services/api';

// `adminOnly` links are hidden from moderators. `icon` is a Bootstrap Icons
// name; the first link of a group is where its label leads, so About sits at
// the top of System deliberately.
const NAV_GROUPS = [
  {
    label: 'Servers',
    icon: 'hdd-stack',
    links: [
      { to: '/admin/servers', text: 'Servers', icon: 'hdd-network' },
      { to: '/admin/installations', text: 'Installations', icon: 'box-seam' },
      { to: '/admin/tasks', text: 'Tasks', icon: 'list-check' }
    ]
  },
  {
    label: 'Users',
    icon: 'people',
    links: [
      { to: '/admin/users', text: 'Users', icon: 'person-gear', adminOnly: true },
      { to: '/admin/claims', text: 'Character Links', icon: 'person-badge' },
      { to: '/admin/invitations', text: 'Invitations', icon: 'envelope-paper' },
      { to: '/admin/reports', text: 'Reports & Appeals', icon: 'flag' }
    ]
  },
  {
    label: 'Rewards',
    icon: 'gift',
    links: [
      { to: '/admin/rewards', text: 'Rewards', icon: 'gift' },
      { to: '/admin/boxes', text: 'Loot Boxes', icon: 'box2' },
      { to: '/admin/events', text: 'Events', icon: 'calendar-event' },
      { to: '/admin/give', text: 'Give Item', icon: 'send' }
    ]
  },
  {
    label: 'Site',
    icon: 'palette',
    links: [
      { to: '/admin/branding', text: 'Branding', icon: 'palette', adminOnly: true },
      { to: '/admin/legal', text: 'Pages', icon: 'file-earmark-text', adminOnly: true }
    ]
  },
  {
    label: 'System',
    icon: 'gear',
    links: [
      { to: '/admin/about', text: 'About', icon: 'info-circle' },
      // Moderator-visible: this is where the notifications moderators used to
      // get in the player bell now live.
      { to: '/admin/staff-feed', text: 'Staff Feed', icon: 'activity', badgeKey: 'staffFeed' },
      { to: '/admin/audit', text: 'Audit Log', icon: 'journal-text' },
      { to: '/admin/jobs', text: 'Scheduled Jobs', icon: 'clock-history', adminOnly: true },
      { to: '/admin/alerts', text: 'Alerts', icon: 'megaphone', adminOnly: true },
      { to: '/admin/settings', text: 'Settings', icon: 'sliders', adminOnly: true }
    ]
  }
];

function AdminLayout() {
  const { isAdmin, isModerator, token } = useAuth();
  const { brand_name: brand } = useSite();

  // Light while the panel is mounted, and whatever it was before on the way
  // out - restored from the attribute rather than hardcoded back to dark, so
  // this keeps working if the site ever gains a theme switch.
  const staff = isModerator();

  // The staff feed's unread count, for the nav badge. Polled rather than
  // pushed, like every other count in this app - the alternative is a websocket
  // layer for a number. Cheap: one indexed count against a timestamp.
  const [staffUnread, setStaffUnread] = useState(0);
  useEffect(() => {
    if (!staff || !token) return undefined;
    let cancelled = false;
    const poll = async () => {
      try {
        const data = await api.admin.staffFeed.unreadCount(token);
        if (!cancelled) setStaffUnread(data.unread || 0);
      } catch (err) {
        // A badge is not worth an error banner over the whole panel.
        console.error('Staff feed unread count error:', err);
      }
    };
    poll();
    const timer = setInterval(poll, 60000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [staff, token]);

  useEffect(() => {
    // Only where the panel actually renders: somebody who lands here without
    // access sees the site's own navbar over the refusal, and a light page
    // under a dark bar would just look broken.
    if (!staff) return undefined;
    const root = document.documentElement;
    const previous = root.getAttribute('data-bs-theme');
    root.setAttribute('data-bs-theme', 'light');
    return () => {
      if (previous) root.setAttribute('data-bs-theme', previous);
      else root.removeAttribute('data-bs-theme');
    };
  }, [staff]);

  if (!staff) {
    return (
      <section className="py-5" style={{ minHeight: '50vh' }}>
        <div className="container text-center">
          <h2>Access Denied</h2>
          <p className="text-body-secondary">
            You do not have permission to access the admin panel.
          </p>
        </div>
      </section>
    );
  }

  // SubNav knows nothing about roles or counts; the section decides both.
  const groups = NAV_GROUPS.map((group) => ({
    ...group,
    links: group.links.map((link) => ({
      ...link,
      hidden: link.adminOnly && !isAdmin(),
      count: link.badgeKey === 'staffFeed' ? staffUnread : undefined
    }))
  }));

  return (
    <>
      {/* The brand is the way out: this is the only navbar in the section. */}
      <SubNav title={brand} titleTo="/" logo badge="Admin" groups={groups} />

      <section className="py-4" style={{ minHeight: '50vh' }}>
        <div className="container">
          <Outlet />
        </div>
      </section>
    </>
  );
}

export default AdminLayout;
