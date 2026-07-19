// Shared helpers for the admin pages.

// Bootstrap contextual colour for a user role.
export const getRoleBadge = (role) => {
  const roleMap = {
    admin: 'danger',
    moderator: 'warning',
    player: 'info',
    banned: 'secondary'
  };
  return roleMap[role] || 'secondary';
};

// Bootstrap contextual colour for a server / task / claim status.
export const getStatusBadge = (status) => {
  const statusMap = {
    running: 'success',
    sleeping: 'warning',
    stopped: 'secondary',
    pending: 'warning',
    processing: 'info',
    completed: 'success',
    approved: 'success',
    rejected: 'secondary'
  };
  return statusMap[status?.toLowerCase()] || 'secondary';
};

// A centered Bootstrap spinner used while a page loads its data.
export function Spinner() {
  return (
    <div className="text-center py-5">
      <div className="spinner-border text-light" role="status">
        <span className="visually-hidden">Loading...</span>
      </div>
    </div>
  );
}
