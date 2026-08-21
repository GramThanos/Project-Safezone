// Protected route component
import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

function ProtectedRoute({ children }) {
	const { user, loading } = useAuth();
	const location = useLocation();

	if (loading) {
		return (
			<div className="container text-center py-5">
				<div className="spinner-border text-light" role="status">
					<span className="visually-hidden">Loading...</span>
				</div>
			</div>
		);
	}

	if (!user) {
		return <Navigate to="/signin" state={{ from: location }} replace />;
	}

	// A banned account can only reach notifications and reports.
	const bannedAllowed = ['/reports', '/notifications'];
	if (user.role === 'banned' && !bannedAllowed.includes(location.pathname)) {
		return <Navigate to="/reports" replace />;
	}

	// If account need to change password
	if (user.must_change_password && location.pathname !== '/profile') {
		return <Navigate to="/profile" replace />;
	}

	return children;
}

export default ProtectedRoute;
