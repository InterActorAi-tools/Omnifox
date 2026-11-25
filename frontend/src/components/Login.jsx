import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { authService, errorMessage } from '../services/authService';
import { AiOutlineEye, AiOutlineEyeInvisible } from 'react-icons/ai';
import { wordmark } from '../assets';

// Google sign-in shows only when a client ID is configured (off for now: accounts are made by admins).
const GOOGLE_CLIENT_ID = window.APP_CONFIG?.GOOGLE_CLIENT_ID;
const EMAIL_ENABLED = window.APP_CONFIG?.EMAIL_ENABLED;

export default function Login({ onLoginSuccess }) {
  const navigate = useNavigate();
  const [formData, setFormData] = useState({
    email: '',
    password: '',
  });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const [show2FA, setShow2FA] = useState(false);
  const [twoFACode, setTwoFACode] = useState('');
  const [emailFor2FA, setEmailFor2FA] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  // Load Google Sign-In script
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    document.body.appendChild(script);

    script.onload = () => {
      if (window.google) {
        // M1: source the Google client ID exclusively from runtime config.
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: handleGoogleLogin,
        });

        window.google.accounts.id.renderButton(
          document.getElementById('googleSignInButton'),
          {
            theme: 'outline',
            size: 'large',
            width: 350,
            text: 'signin_with',
          }
        );
      }
    };

    return () => {
      document.body.removeChild(script);
    };
  }, [show2FA]);

  const handleGoogleLogin = async (response) => {
    try {
      const result = await authService.googleLogin(response.credential);
      if (result.requires_2fa) {
        setEmailFor2FA(result.user.email);
        setShow2FA(true);
        return;
      }
      onLoginSuccess();
      navigate('/app');
    } catch (err) {
      setError(errorMessage(err, 'Google login failed'));
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const response = await authService.login(formData.email, formData.password);
      
      if (response.requires_2fa) {
        setEmailFor2FA(formData.email);
        setShow2FA(true);
        setLoading(false);
      } else {
        onLoginSuccess();
        navigate('/app');
      }
    } catch (err) {
      setError(errorMessage(err, 'Login failed. Please check your credentials.'));
      setLoading(false); 
    }
  };

  const handle2FASubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await authService.verify2FA(emailFor2FA, twoFACode);
      onLoginSuccess();
      navigate('/app');
    } catch (err) {
      setError(errorMessage(err, 'Invalid 2FA code.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center py-12 px-4">
      <div className="max-w-md w-full bg-white shadow-xl rounded-2xl p-8 sm:p-10 space-y-6">

        {/* 2FA Form */}
        {show2FA ? (
          <>
            <div>
              <img src={wordmark} alt="OmniFox" className="h-12 w-auto mx-auto"/>
              <h1 className="mt-4 text-center text-2xl sm:text-3xl font-extrabold text-gray-900">
                Check Your Authenticator
              </h1>
              <p className="mt-2 text-center text-sm text-gray-600">
                Enter the 6-digit code from your 2FA app.
              </p>
            </div>
            <form className="mt-6 space-y-6" onSubmit={handle2FASubmit}>
              {error && (
                <div role="alert" className="rounded-md bg-red-50 p-4">
                  <p className="text-sm text-red-800">{error}</p>
                </div>
              )}
              <div>
                <label htmlFor="2fa-code" className="sr-only">2FA Code</label>
                <input
                  id="2fa-code"
                  autoFocus
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  type="text"
                  required
                  className="appearance-none relative block w-full px-3 py-3 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 sm:text-sm"
                  placeholder="123456"
                  value={twoFACode}
                  onChange={(e) => setTwoFACode(e.target.value)}
                />
              </div>
              <div>
                <button
                  type="submit"
                  disabled={loading}
                  className="group relative w-full flex justify-center py-3 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-[#2E7D38] hover:bg-[#256A2E] disabled:opacity-50"
                >
                  {loading ? 'Verifying...' : 'Verify & Sign In'}
                </button>
              </div>
            </form>
          </>
        ) : (
          /* Original Login Form */
          <>
            <div>
              <img src={wordmark} alt="OmniFox" className="h-12 w-auto mx-auto"/>
              <h1 className="mt-4 text-center text-2xl sm:text-3xl font-extrabold text-gray-900">
                Sign in to OMNIFOX
              </h1>
              <p className="mt-2 text-center text-sm text-gray-600">
                New here?{' '}
                <Link to="/register" className="font-medium text-green-700 hover:text-green-800">
                  Request to join
                </Link>
              </p>
            </div>

            <form className="mt-6 space-y-6" onSubmit={handleSubmit}>
              {error && (
                <div role="alert" className="rounded-md bg-red-50 p-4">
                  <p className="text-sm text-red-800">{error}</p>
                </div>
              )}

              {GOOGLE_CLIENT_ID && (
                <>
                  {/* Google Sign-In Button */}
                  <div className="w-full">
                    <div id="googleSignInButton" className="flex justify-center w-full"></div>
                  </div>

                  {/* Divider */}
                  <div className="relative">
                    <div className="absolute inset-0 flex items-center">
                      <div className="w-full border-t border-gray-300"></div>
                    </div>
                    <div className="relative flex justify-center text-sm">
                      <span className="px-2 bg-white text-gray-500">Or continue with email</span>
                    </div>
                  </div>
                </>
              )}

              {/* Email/Password Form */}
              <div className="rounded-md space-y-4">
                <div>
                  <label htmlFor="email" className="sr-only">Email</label>
                  <input
                    id="email"
                    autoComplete="email"
                    type="email"
                    required
                    className="appearance-none relative block w-full px-3 py-3 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 sm:text-sm"
                    placeholder="Email address"
                    value={formData.email}
                    onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  />
                </div>
                
                <div>
                  <label htmlFor="password" className="sr-only">Password</label>
                  <div className="relative">
                    <input
                      id="password"
                      autoComplete="current-password"
                      type={showPassword ? 'text' : 'password'}
                      required
                      className="appearance-none relative block w-full px-3 py-3 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 sm:text-sm"
                      placeholder="Password"
                      value={formData.password}
                      onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-500 hover:text-gray-700"
                    >
                      {showPassword ? <AiOutlineEyeInvisible size={20} aria-hidden="true" /> : <AiOutlineEye size={20} aria-hidden="true" />}
                    </button>
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-end">
                <div className="text-sm">
                  {EMAIL_ENABLED ? (
                    <Link to="/forgot-password" className="font-medium text-green-700 hover:text-green-800">
                      Forgot your password?
                    </Link>
                  ) : (
                    <span className="text-gray-600">Forgot your password? Ask an admin for a reset link.</span>
                  )}
                </div>
              </div>

              <div>
                <button
                  type="submit"
                  disabled={loading}
                  className="group relative w-full flex justify-center py-3 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-[#2E7D38] hover:bg-[#256A2E] disabled:opacity-50"
                >
                  {loading ? 'Signing in...' : 'Sign in'}
                </button>
              </div>
            </form>
          </>
        )}
      </div>
    </div>
  );
}