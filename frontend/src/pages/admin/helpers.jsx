// Shared helpers for the admin pages.

// Where an admin actually looks these things up. The action catalog is derived
// from the command list, and item ids come from the item list.
export const WIKI_COMMANDS = 'https://pzwiki.net/wiki/Admin_commands';
export const WIKI_ITEMS = 'https://pzwiki.net/wiki/PZwiki:Item_list';

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
    rejected: 'secondary',
    revoked: 'danger',
    failed: 'danger',
    active: 'success',
    expired: 'secondary',
    used: 'info'
  };
  return statusMap[status?.toLowerCase()] || 'secondary';
};

// A reward's icon at a given size, or the gift glyph the player's page falls
// back to when it has none.
export function RewardIcon({ reward, size = 24 }) {
  if (reward?.icon) {
    return (
      <img
        src={reward.icon}
        alt=""
        style={{ width: size, height: size, objectFit: 'contain' }}
      />
    );
  }
  return <i className="fas fa-gift text-body-secondary" style={{ fontSize: size * 0.75 }}></i>;
}

// A centered Bootstrap spinner used while a page loads its data.
export function Spinner() {
  return (
    <div className="text-center py-5">
      <div className="spinner-border text-secondary" role="status">
        <span className="visually-hidden">Loading...</span>
      </div>
    </div>
  );
}
