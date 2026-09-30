import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { SiteProvider } from './context/SiteContext';
import { ToastProvider } from './context/ToastContext';
import { PlayerProvider } from './context/PlayerContext';
import { DialogProvider } from './context/DialogContext';
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import WelcomeBack from './components/WelcomeBack';
import ProtectedRoute from './components/ProtectedRoute';
import Home from './pages/Home';
import SignIn from './pages/SignIn';
import ForgotPassword from './pages/ForgotPassword';
import ResetPassword from './pages/ResetPassword';
import VerifyEmail from './pages/VerifyEmail';
import Servers from './pages/Servers';
import LegalPage from './pages/LegalPage';
import Characters from './pages/Characters';
import Rewards from './pages/Rewards';
import Profile from './pages/Profile';
import Notifications from './pages/Notifications';
import Reports from './pages/Reports';
import AdminLayout from './pages/admin/AdminLayout';
import AdminServers from './pages/admin/Servers';
import AdminServerDetail from './pages/admin/ServerDetail';
import AdminServerLogs from './pages/admin/ServerLogs';
import AdminInstallations from './pages/admin/Installations';
import AdminTasks from './pages/admin/Tasks';
import AdminUsers from './pages/admin/Users';
import AdminUserManage from './pages/admin/UserManage';
import AdminClaims from './pages/admin/Claims';
import AdminRewards from './pages/admin/Rewards';
import AdminBoxes from './pages/admin/Boxes';
import AdminEvents from './pages/admin/Events';
import AdminStaffFeed from './pages/admin/StaffFeed';
import AdminGive from './pages/admin/Give';
import AdminAbout from './pages/admin/About';
import AdminBranding from './pages/admin/Branding';
import AdminLegalPages from './pages/admin/LegalPages';
import AdminAudit from './pages/admin/Audit';
import AdminSettings from './pages/admin/Settings';
import AdminJobs from './pages/admin/Jobs';
import AdminReports from './pages/admin/Reports';
import AdminInvitations from './pages/admin/Invitations';
import AdminAlerts from './pages/admin/Alerts';

function App() {
	return (
		<AuthProvider>
			<SiteProvider>
				<ToastProvider>
				<DialogProvider>
				<PlayerProvider>
				<Router>
					<div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
						<Navbar />
						<main style={{ flex: 1 }}>
							<WelcomeBack />
							<Routes>
								<Route path="/" element={<Home />} />
								<Route path="/signin" element={<SignIn />} />
								<Route path="/signup" element={<SignIn />} />
								<Route path="/forgot-password" element={<ForgotPassword />} />
								<Route path="/reset-password" element={<ResetPassword />} />
								<Route path="/verify" element={<VerifyEmail />} />
								<Route path="/servers" element={<Servers />} />
								{/* One component, three documents. */}
								<Route path="/rules" element={<LegalPage slug="rules" />} />
								<Route path="/terms" element={<LegalPage slug="terms" />} />
								<Route path="/privacy" element={<LegalPage slug="privacy" />} />
								<Route path="/cookies" element={<LegalPage slug="cookies" />} />
								<Route
									path="/characters"
									element={
										<ProtectedRoute>
											<Characters />
										</ProtectedRoute>
									}
								/>
								<Route
									path="/rewards"
									element={
										<ProtectedRoute>
											<Rewards />
										</ProtectedRoute>
									}
								/>
								<Route
									path="/profile"
									element={
										<ProtectedRoute>
											<Profile />
										</ProtectedRoute>
									}
								/>
								<Route
									path="/notifications"
									element={
										<ProtectedRoute>
											<Notifications />
										</ProtectedRoute>
									}
								/>
								<Route
									path="/reports"
									element={
										<ProtectedRoute>
											<Reports />
										</ProtectedRoute>
									}
								/>
								<Route
									path="/admin"
									element={
										<ProtectedRoute>
											<AdminLayout />
										</ProtectedRoute>
									}
								>
									<Route index element={<Navigate to="servers" replace />} />
									<Route path="servers" element={<AdminServers />} />
									<Route path="servers/:serverId" element={<AdminServerDetail />} />
									<Route path="servers/:serverId/logs" element={<AdminServerLogs />} />
									<Route path="installations" element={<AdminInstallations />} />
									<Route path="tasks" element={<AdminTasks />} />
									<Route path="users" element={<AdminUsers />} />
									<Route path="users/:userId" element={<AdminUserManage />} />
									<Route path="claims" element={<AdminClaims />} />
									<Route path="rewards" element={<AdminRewards />} />
									<Route path="boxes" element={<AdminBoxes />} />
									<Route path="events" element={<AdminEvents />} />
									<Route path="staff-feed" element={<AdminStaffFeed />} />
									<Route path="give" element={<AdminGive />} />
									<Route path="branding" element={<AdminBranding />} />
									<Route path="legal" element={<AdminLegalPages />} />
									<Route path="about" element={<AdminAbout />} />
									<Route path="audit" element={<AdminAudit />} />
									<Route path="invitations" element={<AdminInvitations />} />
									<Route path="reports" element={<AdminReports />} />
									<Route path="jobs" element={<AdminJobs />} />
									<Route path="alerts" element={<AdminAlerts />} />
									<Route path="settings" element={<AdminSettings />} />
								</Route>
							</Routes>
						</main>
						<Footer />
					</div>
				</Router>
				</PlayerProvider>
				</DialogProvider>
				</ToastProvider>
			</SiteProvider>
		</AuthProvider>
	);
}

export default App;
