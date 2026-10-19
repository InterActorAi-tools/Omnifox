import { Navigate } from 'react-router-dom';
import { authService } from '../services/authService';

export default function ProtectedRoute({ children, requirePermission = null }) {
  // No cached user means no session: redirect without side effects.
  // The server still checks the cookie on every API call.
  const user = authService.getStoredUser();
  if (!user) {
    return <Navigate to="/login" replace />;
  }

  // If specific permission required, check it
  if (requirePermission) {
    if (!user.permissions?.includes(requirePermission)) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50">
          <div className="text-center">
            <h1 className="text-2xl font-bold text-gray-900 mb-2">Access Denied</h1>
            <p className="text-gray-600 mb-4">
              You don&apos;t have permission to access this page.
            </p>
            <p className="text-sm text-gray-500">
              Required permission: <code className="bg-gray-100 px-2 py-1 rounded">{requirePermission}</code>
            </p>
            {/* Add a link back to the app */}
            <a href="/app" className="text-indigo-600 hover:text-indigo-500">
              Back to App
            </a>
          </div>
        </div>
      );
    }
  }

  return children;
}