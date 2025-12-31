// Profile page
import React from 'react';
import { useAuth } from '../context/AuthContext';

function Profile() {
  const { user } = useAuth();

  const getRoleBadge = (role) => {
    const roleMap = {
      'admin': 'danger',
      'moderator': 'warning',
      'player': 'info',
      'banned': 'secondary'
    };
    return roleMap[role] || 'secondary';
  };

  return (
    <section className="py-5" style={{ minHeight: '50vh' }}>
      <div className="container">
        <div className="row justify-content-center">
          <div className="col-md-8 col-lg-6">
            <div className="character-card">
              <h2 className="character-title text-center mb-4">User Profile</h2>

              <div className="mb-3">
                <label className="small-muted">Username</label>
                <div className="h5">{user?.username}</div>
              </div>

              <div className="mb-3">
                <label className="small-muted">Email</label>
                <div className="h5">{user?.email}</div>
              </div>

              <div className="mb-3">
                <label className="small-muted">Role</label>
                <div>
                  <span className={`badge bg-${getRoleBadge(user?.role)}`}>
                    {user?.role?.toUpperCase()}
                  </span>
                </div>
              </div>

              <div className="mb-3">
                <label className="small-muted">Member Since</label>
                <div>{user?.created_at ? new Date(user.created_at).toLocaleDateString() : 'N/A'}</div>
              </div>

              <hr className="my-4" style={{ borderColor: 'rgba(255,255,255,0.1)' }} />

              <div className="text-center">
                <p className="small-muted mb-0">
                  Need to update your profile? Contact an administrator.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export default Profile;
