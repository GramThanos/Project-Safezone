// Admin › Claims: approve/reject in-game character claim requests.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { getStatusBadge, Spinner } from './helpers';

function Claims() {
  const { token } = useAuth();
  const [claims, setClaims] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api.admin.claims.getAll(token);
      if (data.claims) setClaims(data.claims);
    } catch (err) {
      console.error('Load claims error:', err);
      setError('Failed to load claims');
    }
    setLoading(false);
  };

  const handleClaimReview = async (claimId, action) => {
    setError('');
    try {
      if (action === 'approve') {
        await api.admin.claims.approve(token, claimId);
      } else {
        await api.admin.claims.reject(token, claimId);
      }
      loadData();
    } catch (err) {
      console.error('Claim review error:', err);
      setError(err.message || `Failed to ${action} claim`);
    }
  };

  return (
    <>
      <h4 className="font-display mb-3">Claims</h4>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}

      {loading ? <Spinner /> : (
        <div className="table-responsive">
          <table className="table table-dark table-striped align-middle">
            <thead>
              <tr>
                <th>ID</th>
                <th>Account</th>
                <th>In-game username</th>
                <th>Server</th>
                <th>Status</th>
                <th>Requested</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {claims.length === 0 ? (
                <tr>
                  <td colSpan="7" className="text-center">No claim requests</td>
                </tr>
              ) : (
                claims.map((claim) => (
                  <tr key={claim.id}>
                    <td>{claim.id}</td>
                    <td>#{claim.user_id}</td>
                    <td>{claim.in_game_username}</td>
                    <td>#{claim.server_id}</td>
                    <td>
                      <span className={`badge text-bg-${getStatusBadge(claim.status)}`}>
                        {claim.status}
                      </span>
                    </td>
                    <td>{claim.created_at ? new Date(claim.created_at).toLocaleString() : 'N/A'}</td>
                    <td>
                      {claim.status === 'pending' ? (
                        <div className="btn-group btn-group-sm" role="group">
                          <button className="btn btn-success" onClick={() => handleClaimReview(claim.id, 'approve')}>
                            <i className="fas fa-check"></i> Approve
                          </button>
                          <button className="btn btn-outline-danger" onClick={() => handleClaimReview(claim.id, 'reject')}>
                            <i className="fas fa-times"></i> Reject
                          </button>
                        </div>
                      ) : (
                        <span className="text-body-secondary">—</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default Claims;
