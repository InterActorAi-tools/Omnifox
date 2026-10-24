import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { authService, errorMessage } from '../services/authService';
import { QRCodeCanvas } from 'qrcode.react';
import { AiOutlineEye, AiOutlineEyeInvisible } from 'react-icons/ai';
import AccountSecurity from './AccountSecurity';
import YourData from './YourData';

export default function Profile() {
  const navigate = useNavigate();
  const [user, setUser] = useState(authService.getStoredUser());

  // State for password change
  const [passwordData, setPasswordData] = useState({ current_password: '', new_password: '' });
  const [passwordMessage, setPasswordMessage] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);

  // State for 2FA
  const [qrCode, setQrCode] = useState('');
  // H9: the TOTP secret (`secret`) is the actual credential the user is
  // setting up - if it leaks via XSS during this window, the attacker
  // can generate valid TOTP codes indefinitely. Keep it hidden by
  // default, never auto-render it to the DOM, and clear it as soon
  // as setup completes (handleConfirm2FA + unmount cleanup below).
  const [secret, setSecret] = useState('');
  const [showManualKey, setShowManualKey] = useState(false);
  const [confirmCode, setConfirmCode] = useState('');
  const [backupCodes, setBackupCodes] = useState([]);
  const [disablePassword, setDisablePassword] = useState('');
  const [twoFaError, setTwoFaError] = useState('');
  const [showDisablePassword, setShowDisablePassword] = useState(false);
  
  const is2FAEnabled = user?.two_factor_enabled;
  const isGoogleUser = user?.auth_provider === 'google';

  const handleChangePassword = async (e) => {
    e.preventDefault();
    setPasswordMessage('');
    setPasswordError('');
    
    try {
      const data = await authService.changePassword(passwordData.current_password, passwordData.new_password);
      setPasswordMessage(data.message);
      setPasswordData({ current_password: '', new_password: '' }); 
    } catch (err) {
      setPasswordError(errorMessage(err, 'An error occurred.'));
    }
  };

  const handleEnable2FA = async () => {
    setTwoFaError('');
    setQrCode('');
    setBackupCodes([]);
    // Start each enable flow with the manual key collapsed (H9).
    setShowManualKey(false);
    try {
      const data = await authService.enable2FA();
      setQrCode(data.qr_code_uri);
      setSecret(data.secret);
    } catch (err) {
      setTwoFaError(errorMessage(err, 'Failed to start 2FA setup.'));
    }
  };

  const handleConfirm2FA = async (e) => {
    e.preventDefault();
    setTwoFaError('');
    try {
      const data = await authService.confirm2FA(confirmCode);
      setBackupCodes(data.backup_codes);
      setQrCode('');
      setConfirmCode('');
      // H9: drop the TOTP secret from JS state the moment setup completes.
      // After confirm, the secret lives on the server only - the user has
      // their authenticator app entry, so the browser has no further need
      // for it. Same for the manual-key toggle so a remount doesn't expose
      // any stale state.
      setSecret('');
      setShowManualKey(false);

      setUser(await authService.getCurrentUser());
    } catch (err) {
      setTwoFaError(errorMessage(err, 'Invalid code. Please try again.'));
    }
  };

  const handleDisable2FA = async (e) => {
    e.preventDefault();
    setTwoFaError('');
    try {
      await authService.disable2FA(disablePassword);
      setBackupCodes([]);
      setDisablePassword('');
      await authService.getCurrentUser();
      window.location.reload(); 
    } catch (err) {
      setTwoFaError(errorMessage(err, 'Failed to disable 2FA. Check your password.'));
    }
  };

  useEffect(() => {
    authService.getCurrentUser()
      .then(userData => setUser(userData))
      .catch(() => {});
  }, []);

  // H9: if the user navigates away during 2FA setup (qrCode set but
  // confirm not submitted), drop the secret from memory on unmount so
  // it doesn't persist in any retained component state.
  useEffect(() => {
    return () => {
      setSecret('');
      setShowManualKey(false);
    };
  }, []);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">My Profile</h1>
              <p className="text-gray-600 mt-1">Manage your account settings, {user?.name}</p>
            </div>
            <button
              onClick={() => navigate('/app')}
              className="px-4 py-2 bg-[#2E7D38] text-white rounded-lg hover:bg-[#256A2E]"
            >
              Back to App
            </button>
          </div>
        </div>
      </header>

      {/* Page Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          
          {/* Column 1: Profile Info */}
          <div className="bg-white overflow-hidden shadow rounded-lg md:col-span-1">
            <div className="px-4 py-5 sm:p-6">
              <h2 className="text-lg font-medium text-gray-900 mb-4">Account Information</h2>
              <dl className="space-y-3">
                <div>
                  <dt className="text-sm font-medium text-gray-500">Email</dt>
                  <dd className="mt-1 text-sm text-gray-900">{user?.email}</dd>
                </div>
                <div>
                  <dt className="text-sm font-medium text-gray-500">Name</dt>
                  <dd className="mt-1 text-sm text-gray-900">{user?.name}</dd>
                </div>
                <div>
                  <dt className="text-sm font-medium text-gray-500">Sign-in Method</dt>
                  <dd className="mt-1">
                    {isGoogleUser ? (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                          <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                          <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                          <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                          <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                        </svg>
                        Google
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-gray-100 text-gray-800 rounded-full text-sm">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                        </svg>
                        Email/Password
                      </span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-sm font-medium text-gray-500">Roles</dt>
                  <dd className="mt-1 flex gap-2 flex-wrap">
                    {user?.roles?.map(role => (
                      <span key={role} className="px-3 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                        {role}
                      </span>
                    ))}
                  </dd>
                </div>
              </dl>
            </div>
          </div>

          {/* Column 2: Change Password */}
          <div className="bg-white overflow-hidden shadow rounded-lg md:col-span-2">
            <div className="px-4 py-5 sm:p-6">
              <h2 className="text-lg font-medium text-gray-900 mb-4">Change Password</h2>
              
              {/* Google OAuth Information Banner */}
              {isGoogleUser ? (
                <div className="p-4 bg-blue-50 border-l-4 border-blue-400 rounded-r-lg">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0">
                      <svg className="h-6 w-6 text-blue-600" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                      </svg>
                    </div>
                    <div className="flex-1">
                      <h4 className="text-sm font-semibold text-blue-900 mb-1">
                        🔐 Signed in with Google
                      </h4>
                      <p className="text-sm text-blue-800 leading-relaxed">
                        You&apos;re using Google authentication to sign in. Password changes must be managed through your Google account settings.
                      </p>
                      <a 
                        href="https://myaccount.google.com/security" 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 mt-3 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                        </svg>
                        Manage Google Account Security
                      </a>
                    </div>
                  </div>
                </div>
              ) : (
                <form onSubmit={handleChangePassword} className="space-y-4">
                  {passwordError && <p role="alert" className="text-sm text-red-700">{passwordError}</p>}
                  {passwordMessage && <p role="status" className="text-sm text-green-700">{passwordMessage}</p>}
                  
                  <div>
                    <label htmlFor="current-password" className="block text-sm font-medium text-gray-700">
                      Current Password
                    </label>
                    <div className="relative mt-1">
                      <input
                        id="current-password"
                        type={showCurrentPassword ? 'text' : 'password'}
                        autoComplete="current-password"
                        required
                        className="block w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-green-500 focus:border-green-500"
                        value={passwordData.current_password}
                        onChange={(e) => setPasswordData({...passwordData, current_password: e.target.value})}
                      />
                      <button
                        type="button"
                        onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                        aria-label={showCurrentPassword ? "Hide password" : "Show password"}
                        className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-500 hover:text-gray-700"
                      >
                        {showCurrentPassword ? <AiOutlineEyeInvisible size={20} aria-hidden="true" /> : <AiOutlineEye size={20} aria-hidden="true" />}
                      </button>
                    </div>
                  </div>
                  <div>
                    <label htmlFor="new-password" className="block text-sm font-medium text-gray-700">
                      New Password
                    </label>
                    <div className="relative mt-1">
                      <input
                        id="new-password"
                        type={showNewPassword ? 'text' : 'password'}
                        autoComplete="new-password"
                        required
                        className="block w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-green-500 focus:border-green-500"
                        value={passwordData.new_password}
                        onChange={(e) => setPasswordData({...passwordData, new_password: e.target.value})}
                      />
                      <button
                        type="button"
                        onClick={() => setShowNewPassword(!showNewPassword)}
                        aria-label={showNewPassword ? "Hide password" : "Show password"}
                        className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-500 hover:text-gray-700"
                      >
                        {showNewPassword ? <AiOutlineEyeInvisible size={20} aria-hidden="true" /> : <AiOutlineEye size={20} aria-hidden="true" />}
                      </button>
                    </div>
                    <p className="mt-1 text-xs text-gray-500">
                      Must be 8+ chars with uppercase, lowercase, number, and special character.
                    </p>
                  </div>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-[#2E7D38] text-white rounded-lg hover:bg-[#256A2E]"
                  >
                    Update Password
                  </button>
                </form>
              )}
            </div>
          </div>

         {/* --- 2FA CARD --- */}
         <div className="bg-white overflow-hidden shadow rounded-lg md:col-span-3">
            <div className="px-4 py-5 sm:p-6">
              <h2 className="text-lg font-medium text-gray-900 mb-4">
                Two-Factor Authentication (2FA)
              </h2>
              
              {twoFaError && <p role="alert" className="text-sm text-red-700 mb-4">{twoFaError}</p>}

              {is2FAEnabled ? (
                // --- UI FOR DISABLING 2FA ---
                <form onSubmit={handleDisable2FA} className="space-y-4">
                  <p className="text-sm text-green-700">2FA is currently enabled.</p>
                  <div>
                    <label htmlFor="disable-2fa-password" className="block text-sm font-medium text-gray-700">
                      {isGoogleUser ? 'Enter a current 2FA code to Disable' : 'Enter Password to Disable'}
                    </label>
                    <div className="relative mt-1">
                      <input
                        id="disable-2fa-password"
                        type={showDisablePassword ? 'text' : 'password'}
                        autoComplete="current-password"
                        required
                        placeholder={isGoogleUser ? 'Code from your authenticator app' : 'Your current password'}
                        className="block w-full max-w-xs px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-green-500 focus:border-green-500"
                        value={disablePassword}
                        onChange={(e) => setDisablePassword(e.target.value)}
                      />
                      <button
                        type="button"
                        onClick={() => setShowDisablePassword(!showDisablePassword)}
                        aria-label={showDisablePassword ? "Hide password" : "Show password"}
                        className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-500 hover:text-gray-700"
                      >
                        {showDisablePassword ? <AiOutlineEyeInvisible size={20} aria-hidden="true" /> : <AiOutlineEye size={20} aria-hidden="true" />}
                      </button>
                    </div>
                  </div>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
                  >
                    Disable 2FA
                  </button>
                </form>
              ) : qrCode ? (
                // --- UI FOR CONFIRMING 2FA (WITH MANUAL KEY) ---
                <div>
                  <p className="text-sm text-gray-700 mb-4">
                    Scan this QR code with your authenticator app (like Google Authenticator or Authy), then enter the 6-digit code to confirm.
                  </p>
                  <div className="flex flex-col md:flex-row gap-6">
                    
                    <div className="p-4 bg-white border rounded-lg inline-block">
                      <QRCodeCanvas value={qrCode} size={200} role="img" aria-label="QR code for your authenticator app" />
                    </div>
                    
                    <div className="flex-1">
                      <form onSubmit={handleConfirm2FA} className="space-y-4">
                        <div>
                          <label htmlFor="confirm-2fa-code" className="block text-sm font-medium text-gray-700">
                            Verification Code
                          </label>
                          <input
                            id="confirm-2fa-code"
                            autoComplete="one-time-code"
                            type="text"
                            required
                            inputMode="numeric"
                            pattern="[0-9]{6}"
                            maxLength="6"
                            placeholder="123456"
                            className="mt-1 block w-full max-w-xs px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-green-500 focus:border-green-500"
                            value={confirmCode}
                            onChange={(e) => setConfirmCode(e.target.value)}
                          />
                        </div>
                        <button
                          type="submit"
                          className="px-4 py-2 bg-green-700 text-white rounded-lg hover:bg-green-800"
                        >
                          Confirm & Enable
                        </button>
                      </form>

                      {/*
                        H9: the manual key (raw base32 TOTP secret) is
                        hidden by default. An XSS payload during setup
                        could otherwise scrape it from the DOM and
                        generate valid TOTP codes indefinitely. Users
                        who genuinely cannot scan the QR can opt in.
                      */}
                      <div className="mt-6">
                        <button
                          type="button"
                          onClick={() => setShowManualKey(!showManualKey)}
                          className="text-sm font-medium text-gray-700 underline hover:text-gray-900"
                        >
                          {showManualKey ? 'Hide manual key' : "Can't scan? Show manual key"}
                        </button>
                        {showManualKey && (
                          <div className="mt-2">
                            <p className="text-xs text-gray-500 mb-2">
                              Enter this secret key into your authenticator app. Treat it like a password.
                            </p>
                            <div className="bg-gray-100 p-3 rounded-md font-mono text-sm text-gray-800 break-all">
                              {secret}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ) : backupCodes.length > 0 ? (
                // --- UI FOR SHOWING BACKUP CODES ---
                <div>
                  <h3 className="font-semibold text-green-700">2FA Enabled Successfully!</h3>
                  <p className="text-sm text-gray-700 my-4">
                    <strong>IMPORTANT:</strong> Store these backup codes in a safe place. You will NOT be able to see them again.
                  </p>
                  <div className="bg-gray-100 p-4 rounded-md font-mono grid grid-cols-2 gap-2 mb-6">
                    {backupCodes.map(code => (
                      <span key={code}>{code}</span>
                    ))}
                  </div>
                  <button
                    onClick={() => window.location.reload()}
                    className="w-full md:w-auto px-6 py-2 bg-gray-800 text-white rounded-lg hover:bg-gray-900"
                  >
                    I have saved these codes
                  </button>
                </div>
              ) : (
                // --- UI FOR ENABLING 2FA ---
                <button
                  onClick={handleEnable2FA}
                  className="px-4 py-2 bg-[#2E7D38] text-white rounded-lg hover:bg-[#256A2E]"
                >
                  Enable 2FA
                </button>
              )}
            </div>
          </div>

          <AccountSecurity />
          {user?.email && <YourData email={user.email} />}
        </div>
      </div>
    </div>
  );
}