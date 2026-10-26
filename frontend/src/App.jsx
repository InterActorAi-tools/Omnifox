import { useState, useEffect, lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import Login from './components/Login';
import Register from './components/Register';
import ProtectedRoute from './components/ProtectedRoute';
import Hero from './components/Hero';
import Demo from './components/Demo';
import Info from './components/Info';
import ForgotPassword from './components/ForgotPassword';
import ResetPassword from './components/ResetPassword';
import Navbar from './components/Navbar';
import ErrorBoundary from './components/ErrorBoundary';
import RecoveryCodeNotice from './components/RecoveryCodeNotice';

// Loaded on demand: the dashboard (charts) and profile (QR code) are not
// needed to sign in or run an analysis.
const Dashboard = lazy(() => import('./components/Dashboard'));
const Profile = lazy(() => import('./components/Profile'));

const PageLoading = () => (
  <div role="status" className="min-h-[50vh] flex items-center justify-center text-gray-600">Loading…</div>
);

import { authService, clearAuthStorage } from './services/authService';

import './App.css';

// Get initial state, but we will verify it immediately
const getInitialUser = () => {
  if (authService.isAuthenticated()) {
    try {
      const user = authService.getStoredUser();
      return user || null;
    } catch {
      clearAuthStorage();
      return null;
    }
  }
  return null;
};

// The dashboard renders its own <main>; every other route gets one here.
const AppMain = ({ children }) => {
  const { pathname } = useLocation();
  return pathname === '/dashboard'
    ? <div className="relative z-10">{children}</div>
    : <main id="main-content" tabIndex={-1} className="app focus:outline-none">{children}</main>;
};

const PAGE_TITLES = {
  '/login': 'Sign in',
  '/register': 'Create account',
  '/forgot-password': 'Forgot password',
  '/reset-password': 'Reset password',
  '/app': 'Analyze comments',
  '/profile': 'My profile',
  '/dashboard': 'Dashboard',
};

// Unique page titles (WCAG 2.4.2) for screen-reader users and browser tabs.
const PageTitle = () => {
  const { pathname } = useLocation();
  useEffect(() => {
    const page = PAGE_TITLES[pathname];
    document.title = page ? `${page} – OmniFox` : 'OmniFox';
  }, [pathname]);
  return null;
};

const App = () => {
  const [user, setUser] = useState(getInitialUser());
  const [loading, setLoading] = useState(true); // Start loading to verify session

  const handleLoginSuccess = () => {
    const storedUser = authService.getStoredUser();
    setUser(storedUser);
  };

  useEffect(() => {
    const verifySession = async () => {
      if (authService.isAuthenticated()) {
        try {
          // This call hits the backend. If the session is revoked, 
          // the server returns 401, and authService automatically logs out.
          const userData = await authService.getCurrentUser();
          setUser(userData);
        } catch (error) {
          console.error('Session verification failed:', error);
          // If 401, the interceptor in authService handles the redirect
        }
      }
      setLoading(false);
    };
    
    verifySession();
  }, []);

  // Only consider authenticated if we have a user object
  const isAuth = !!user;

  if (loading) {
    return (
      <main>
        <div className="main">
          <div className="background_main" />
        </div>
        <div className="app">
          <div className="min-h-screen flex items-center justify-center">
            <div role="status" className="text-xl text-gray-600">Verifying session...</div>
          </div>
        </div>
      </main>
    );
  }

  return (
    <BrowserRouter>
      <ErrorBoundary>
        <PageTitle />
        <RecoveryCodeNotice />
        <a href="#main-content" className="skip-link">Skip to main content</a>
        <div>
          <div className="main">
            <div className="background_main" />
          </div>
        
          {/* ✅ Navbar - Hidden on Dashboard route since Dashboard has its own header */}
          <Routes>
            <Route path="/dashboard" element={null} />
            <Route 
              path="*" 
              element={
                isAuth && (
                  <Navbar user={user} />
                )
              } 
            />
          </Routes>
        
          <AppMain>
            <Suspense fallback={<PageLoading />}>
              <Routes>
                <Route 
                  path="/login" 
                  element={isAuth ? <Navigate to="/app" replace /> : <Login onLoginSuccess={handleLoginSuccess} />} 
                />
                <Route 
                  path="/register" 
                  element={isAuth ? <Navigate to="/app" replace /> : <Register onLoginSuccess={handleLoginSuccess} />} 
                />
                <Route 
                  path="/forgot-password" 
                  element={isAuth ? <Navigate to="/app" replace /> : <ForgotPassword />} 
                />
                <Route 
                  path="/reset-password" 
                  element={isAuth ? <Navigate to="/app" replace /> : <ResetPassword />} 
                />

                <Route
                  path="/app"
                  element={
                    <ProtectedRoute>
                      <>
                        <Hero user={user} />
                        <Demo user={user} />
                        <Info user={user} />
                      </>
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
                  path="/dashboard"
                  element={
                    <ProtectedRoute requirePermission="view_dashboard">
                      <Dashboard />
                    </ProtectedRoute>
                  }
                />

                <Route
                  path="/"
                  element={<Navigate to={isAuth ? "/app" : "/login"} replace />}
                />

                <Route
                  path="*"
                  element={<Navigate to={isAuth ? "/app" : "/login"} replace />}
                />
              </Routes>
            </Suspense>
          </AppMain>
        </div>
      </ErrorBoundary>
    </BrowserRouter>
  );
};

export default App;