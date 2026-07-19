import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import ProtectedRoute from './components/ProtectedRoute';
import Home from './pages/Home';
import SignIn from './pages/SignIn';
import Servers from './pages/Servers';
import Players from './pages/Players';
import Rewards from './pages/Rewards';
import Profile from './pages/Profile';
import AdminLayout from './pages/admin/AdminLayout';
import AdminServers from './pages/admin/Servers';
import AdminTasks from './pages/admin/Tasks';
import AdminUsers from './pages/admin/Users';
import AdminClaims from './pages/admin/Claims';
import AdminRewards from './pages/admin/Rewards';
import AdminBoxes from './pages/admin/Boxes';
import AdminGive from './pages/admin/Give';
import AdminAudit from './pages/admin/Audit';

function App() {
  return (
    <AuthProvider>
      <Router>
        <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
          <Navbar />
          <main style={{ flex: 1 }}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/signin" element={<SignIn />} />
              <Route path="/servers" element={<Servers />} />
              <Route 
                path="/players" 
                element={
                  <ProtectedRoute>
                    <Players />
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
                path="/admin"
                element={
                  <ProtectedRoute>
                    <AdminLayout />
                  </ProtectedRoute>
                }
              >
                <Route index element={<Navigate to="servers" replace />} />
                <Route path="servers" element={<AdminServers />} />
                <Route path="tasks" element={<AdminTasks />} />
                <Route path="users" element={<AdminUsers />} />
                <Route path="claims" element={<AdminClaims />} />
                <Route path="rewards" element={<AdminRewards />} />
                <Route path="boxes" element={<AdminBoxes />} />
                <Route path="give" element={<AdminGive />} />
                <Route path="audit" element={<AdminAudit />} />
              </Route>
            </Routes>
          </main>
          <Footer />
        </div>
      </Router>
    </AuthProvider>
  );
}

export default App;
