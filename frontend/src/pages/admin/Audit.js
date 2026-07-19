// Admin › Audit Log: recent administrative actions.
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Spinner } from './helpers';

function Audit() {
  const { token } = useAuth();
  const [auditEntries, setAuditEntries] = useState([]);
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
      const data = await api.admin.audit.getAll(token);
      if (data.entries) setAuditEntries(data.entries);
    } catch (err) {
      console.error('Load audit error:', err);
      setError('Failed to load audit log');
    }
    setLoading(false);
  };

  return (
    <>
      <h4 className="font-display mb-3">Audit Log</h4>
      {error && <div className="alert alert-danger" role="alert">{error}</div>}

      {loading ? <Spinner /> : (
        <div className="table-responsive">
          <table className="table table-dark table-striped align-middle">
            <thead>
              <tr>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Target</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {auditEntries.length === 0 ? (
                <tr>
                  <td colSpan="5" className="text-center">No audit entries</td>
                </tr>
              ) : (
                auditEntries.map((e) => (
                  <tr key={e.id}>
                    <td>{e.created_at ? new Date(e.created_at).toLocaleString() : 'N/A'}</td>
                    <td>{e.actor_user_id ? `#${e.actor_user_id}` : 'system'}</td>
                    <td><span className="badge text-bg-info">{e.action}</span></td>
                    <td>{e.target || '—'}</td>
                    <td className="text-body-secondary">{e.detail}</td>
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

export default Audit;
