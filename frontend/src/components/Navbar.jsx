import { Link, useNavigate } from 'react-router-dom';
import { authService, clearAuthStorage } from '../services/authService';
import { wordmark } from '../assets';
import { AiOutlineUser, AiOutlineLogout, AiOutlineDashboard } from 'react-icons/ai';

const Navbar = ({ user }) => {
  const navigate = useNavigate();
  const canViewDashboard = user?.permissions?.includes('view_dashboard');

  const handleLogout = async () => {
    try {
      await authService.logout();
      window.location.href = '/login';
    } catch (error) {
      console.error('Logout error:', error);
      clearAuthStorage();
      window.location.href = '/login';
    }
  };

  // Modern unified button styles - cleaner color scheme
  const buttonBaseStyles = "px-3 sm:px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 flex items-center gap-2";
  const buttonPrimaryStyles = `${buttonBaseStyles} bg-[#2E7D38] text-white hover:bg-[#256A2E] shadow-sm`;
  const buttonSecondaryStyles = `${buttonBaseStyles} border border-gray-300 text-gray-700 hover:bg-gray-50`;

  return (
    <nav aria-label="Main" className="sticky top-0 z-50 w-full flex justify-between items-center px-4 sm:px-6 md:px-8 py-3 bg-white shadow-sm border-b border-gray-200">
      
      {/* Left Side: Logo and Title */}
      <Link to="/app" reloadDocument aria-label="OmniFox home" className="flex items-center gap-2 sm:gap-3 min-w-0 rounded-lg">
        <img src={wordmark} alt="OmniFox" className="h-6 sm:h-8 w-auto object-contain shrink-0"/>
      </Link>
      
      {/* Right Side: User Info and Action Buttons */}
      <div className="flex items-center gap-2 sm:gap-3">
        {/* User Welcome Message */}
        <span className="hidden lg:block text-gray-600 text-sm mr-2">
          Welcome, <span className="font-medium text-gray-800">{user?.name || user?.email}!</span>
        </span>
        
        {/* Admin Dashboard Button - Show if has permission */}
        {canViewDashboard && (
          <button
            onClick={() => navigate('/dashboard')}
            className={buttonPrimaryStyles}
            title="Admin Dashboard"
            aria-label="Admin Dashboard"
          >
            <AiOutlineDashboard size={18} className="shrink-0" aria-hidden="true" />
            <span className="hidden md:inline">Dashboard</span>
          </button>
        )}

        {/* Divider */}
        <div className="hidden sm:block h-6 w-px bg-gray-300 mx-1"></div>

        {/* Profile Button */}
        <button
          onClick={() => navigate('/profile')}
          className={buttonSecondaryStyles}
          title="Profile"
          aria-label="Profile"
        >
          <AiOutlineUser size={18} className="shrink-0" aria-hidden="true" />
          <span className="hidden md:inline">Profile</span>
        </button>
        
        {/* Logout Button */}
        <button
          onClick={handleLogout}
          className={buttonSecondaryStyles}
          title="Logout"
          aria-label="Logout"
        >
          <AiOutlineLogout size={18} className="shrink-0" aria-hidden="true" />
          <span className="hidden md:inline">Logout</span>
        </button>
      </div>
    </nav>
  );
};

export default Navbar;