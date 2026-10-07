import React, { lazy } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { SiteProvider } from './context/SiteContext';
import { ToastProvider } from './context/ToastContext';
import { PlayerProvider } from './context/PlayerContext';
import { DialogProvider } from './context/DialogContext';
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import TabBar from './components/TabBar';
import WelcomeBack from './components/WelcomeBack';
import ProtectedRoute from './components/ProtectedRoute';
import PageBoundary from './components/PageBoundary';

// Every page is its own chunk, fetched the first time it is opened, so the
// first load carries only the frame and the page being opened - and a player
// never downloads the admin panel at all.
//
// A deploy replaces the chunks. An app left open since before one asks for
// files that no longer exist, so a failed load reloads the page once, which
// fetches the new index.html and the chunks it names. Once only: if the
// reload fails too, the error is real and is shown rather than looped on.
const RELOAD_KEY = 'safezone.chunk-reload';

const page = (load) => lazy(() => load().then(
	(module) => {
		try { sessionStorage.removeItem(RELOAD_KEY); } catch (e) { /* storage blocked */ }
		return module;
	},
	(error) => {
		let reloaded = true;
		try { reloaded = sessionStorage.getItem(RELOAD_KEY) === '1'; } catch (e) { /* storage blocked */ }
		if (reloaded) throw error;
		try { sessionStorage.setItem(RELOAD_KEY, '1'); } catch (e) { /* storage blocked */ }
		window.location.reload();
		return new Promise(() => {});
	}
));

const Home = page(() => import('./pages/Home'));
const SignIn = page(() => import('./pages/SignIn'));
const ForgotPassword = page(() => import('./pages/ForgotPassword'));
const ResetPassword = page(() => import('./pages/ResetPassword'));
const VerifyEmail = page(() => import('./pages/VerifyEmail'));
const Servers = page(() => import('./pages/Servers'));
const LegalPage = page(() => import('./pages/LegalPage'));
const Characters = page(() => import('./pages/Characters'));
const Rewards = page(() => import('./pages/Rewards'));
const Shop = page(() => import('./pages/Shop'));
const Profile = page(() => import('./pages/Profile'));
const Notifications = page(() => import('./pages/Notifications'));
const Reports = page(() => import('./pages/Reports'));
const Me = page(() => import('./pages/Me'));
const AdminLayout = page(() => import('./pages/admin/AdminLayout'));
const AdminServers = page(() => import('./pages/admin/Servers'));
const AdminServerDetail = page(() => import('./pages/admin/ServerDetail'));
const AdminServerLogs = page(() => import('./pages/admin/ServerLogs'));
const AdminInstallations = page(() => import('./pages/admin/Installations'));
const AdminTasks = page(() => import('./pages/admin/Tasks'));
const AdminUsers = page(() => import('./pages/admin/Users'));
const AdminUserManage = page(() => import('./pages/admin/UserManage'));
const AdminClaims = page(() => import('./pages/admin/Claims'));
const AdminRewards = page(() => import('./pages/admin/Rewards'));
const AdminBoxes = page(() => import('./pages/admin/Boxes'));
const AdminShop = page(() => import('./pages/admin/Shop'));
const AdminEvents = page(() => import('./pages/admin/Events'));
const AdminStaffFeed = page(() => import('./pages/admin/StaffFeed'));
const AdminGive = page(() => import('./pages/admin/Give'));
const AdminAbout = page(() => import('./pages/admin/About'));
const AdminBranding = page(() => import('./pages/admin/Branding'));
const AdminLegalPages = page(() => import('./pages/admin/LegalPages'));
const AdminAudit = page(() => import('./pages/admin/Audit'));
const AdminSettings = page(() => import('./pages/admin/Settings'));
const AdminJobs = page(() => import('./pages/admin/Jobs'));
const AdminReports = page(() => import('./pages/admin/Reports'));
const AdminInvitations = page(() => import('./pages/admin/Invitations'));
const AdminAlerts = page(() => import('./pages/admin/Alerts'));


function App() {
	return (
		<AuthProvider>
			<SiteProvider>
				<ToastProvider>
				<DialogProvider>
				<PlayerProvider>
				<Router>
					<div className="app-shell">
						<Navbar />
						<main style={{ flex: 1 }}>
							<WelcomeBack />
							<PageBoundary>
							<Routes>
								<Route path="/" element={<Home />} />
								<Route path="/signin" element={<SignIn />} />
								<Route path="/signup" element={<SignIn />} />
								<Route path="/forgot-password" element={<ForgotPassword />} />
								<Route path="/reset-password" element={<ResetPassword />} />
								<Route path="/verify" element={<VerifyEmail />} />
								<Route path="/servers" element={<Servers />} />
								<Route path="/me" element={<Me />} />
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
									path="/shop"
									element={
										<ProtectedRoute>
											<Shop />
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
									<Route path="shop" element={<AdminShop />} />
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
							</PageBoundary>
						</main>
						<Footer />
						<TabBar />
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
