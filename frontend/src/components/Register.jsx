import { useState, useEffect } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { authService, errorMessage } from '../services/authService';
import { AiOutlineEye, AiOutlineEyeInvisible } from "react-icons/ai";

export default function Register({ onLoginSuccess }) {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams(); // Get URL params
    const token = searchParams.get("token"); // Read token

    const [formData, setFormData] = useState({
        email: "",
        password: "",
        confirmPassword: "",
        name: "",
    });
    const [passwordChecks, setPasswordChecks] = useState({
        minLength: false,
        hasUppercase: false,
        hasLowercase: false,
        hasNumber: false,
        hasSpecial: false,
    });
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);
    const [requestSent, setRequestSent] = useState(false);

    const [showPassword, setShowPassword] = useState(false);
    const [showConfirmPassword, setShowConfirmPassword] = useState(false);

    useEffect(() => {
        // Check password requirements in real-time
        const password = formData.password;
        setPasswordChecks({
            minLength: password.length >= 8,
            hasUppercase: /[A-Z]/.test(password),
            hasLowercase: /[a-z]/.test(password),
            hasNumber: /\d/.test(password),
            hasSpecial: /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?]/.test(password),
        });
    }, [formData.password]);

    useEffect(() => {
        if (token) {
            setLoading(true);
            authService
                .getInviteDetails(token)
                .then((data) => {
                    setFormData((prev) => ({
                        ...prev,
                        email: data.email,
                        name: data.name,
                    }));
                })
                .catch(() => {
                    setError("Invalid or expired invitation link.");
                })
                .finally(() => setLoading(false));
        }
    }, [token]);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError("");
        setLoading(true);

        if (formData.password !== formData.confirmPassword) {
            setError("Passwords do not match");
            setLoading(false);
            return;
        }

        const allChecksPassed = Object.values(passwordChecks).every((check) => check);
        if (!allChecksPassed) {
            setError("Please meet all password requirements");
            setLoading(false);
            return;
        }

        try {
            if (token) {
                await authService.register(formData.email, formData.password, formData.name, token);
                onLoginSuccess();
                navigate("/app");
            } else {
                // No invitation: an admin has to accept the request first
                await authService.requestToJoin(formData.name, formData.email, formData.password);
                setRequestSent(true);
            }
        } catch (err) {
            setError(errorMessage(err, token ? "Registration failed" : "Could not send your request"));
        } finally {
            setLoading(false);
        }
    };

    const CheckIcon = ({ met }) => <span className={`text-sm ${met ? "text-green-700" : "text-gray-400"}`}>{met ? "✓" : "○"}</span>;

    if (requestSent) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
                <div className="max-w-md w-full bg-white shadow-lg rounded-lg p-8 text-center">
                    <h1 className="text-2xl font-bold text-gray-900 mb-4">Request sent</h1>
                    <p className="text-gray-600 mb-6">An admin will review it. You can log in with your email and password once they accept it.</p>
                    <Link to="/login" className="text-[#2E7D38] font-semibold hover:underline">
                        Go to Login
                    </Link>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
            <div className="max-w-md w-full bg-white shadow-xl rounded-2xl p-8 sm:p-10 space-y-6">
                <div>
                    <h1 className="mt-6 text-center text-3xl font-extrabold text-gray-900">{token ? "Create your account" : "Request to join"}</h1>
                    {!token && <p className="mt-2 text-center text-sm text-gray-600">An admin has to accept your request before you can log in.</p>}
                    <p className="mt-2 text-center text-sm text-gray-600">
                        Or{" "}
                        <Link to="/login" className="font-medium text-green-700 hover:text-green-800">
                            sign in to your account
                        </Link>
                    </p>
                </div>

                <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
                    {error && (
                        <div role="alert" className="rounded-md bg-red-50 p-4">
                            <p className="text-sm text-red-800">{error}</p>
                        </div>
                    )}

                    <div className="rounded-md space-y-4">
                        <div>
                            <label htmlFor="name" className="block text-sm font-medium text-gray-700">
                                Full Name
                            </label>
                            <input
                                id="name"
                                autoComplete="name"
                                name="name"
                                type="text"
                                readOnly={!!token}
                                required
                                className={`mt-1 block w-full px-3 py-3 border border-gray-300 rounded-md sm:text-sm ${token ? "bg-gray-100 text-gray-700 cursor-not-allowed" : "focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"}`}
                                value={formData.name}
                                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                            />
                        </div>

                        <div>
                            <label htmlFor="email" className="block text-sm font-medium text-gray-700">
                                Email address
                            </label>
                            <input
                                id="email"
                                autoComplete="email"
                                name="email"
                                type="email"
                                readOnly={!!token}
                                required
                                className={`mt-1 block w-full px-3 py-3 border border-gray-300 rounded-md sm:text-sm ${token ? "bg-gray-100 text-gray-700 cursor-not-allowed" : "focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"}`}
                                value={formData.email}
                                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                            />
                        </div>

                        <div>
                            <label htmlFor="password" className="block text-sm font-medium text-gray-700">
                                Password
                            </label>
                            <div className="relative mt-1">
                                <input
                                    id="password"
                                    autoComplete="new-password"
                                    name="password"
                                    type={showPassword ? "text" : "password"}
                                    required
                                    value={formData.password}
                                    onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                                    className="appearance-none relative block w-full px-3 py-3 border border-gray-300 rounded-md placeholder-gray-500 text-gray-900 focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 sm:text-sm"
                                    placeholder="Password"
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowPassword(!showPassword)}
                                    aria-label={showPassword ? "Hide password" : "Show password"}
                                    className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-500 hover:text-gray-700">
                                    {showPassword ? <AiOutlineEyeInvisible size={20} aria-hidden="true" /> : <AiOutlineEye size={20} aria-hidden="true" />}
                                </button>
                            </div>

                            {formData.password && (
                                <div className="mt-2 p-3 bg-gray-50 rounded-md text-xs space-y-1">
                                    <div className="flex items-center gap-2">
                                        <CheckIcon met={passwordChecks.minLength} />
                                        <span>At least 8 characters</span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <CheckIcon met={passwordChecks.hasUppercase} />
                                        <span>One uppercase letter (A-Z)</span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <CheckIcon met={passwordChecks.hasLowercase} />
                                        <span>One lowercase letter (a-z)</span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <CheckIcon met={passwordChecks.hasNumber} />
                                        <span>One number (0-9)</span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <CheckIcon met={passwordChecks.hasSpecial} />
                                        <span>One special character (!@#$%^&*)</span>
                                    </div>
                                </div>
                            )}
                        </div>

                        <div>
                            <label htmlFor="confirmPassword" className="block text-sm font-medium text-gray-700">
                                Confirm Password
                            </label>
                            <div className="relative mt-1">
                                <input
                                    id="confirmPassword"
                                    autoComplete="new-password"
                                    name="confirmPassword"
                                    type={showConfirmPassword ? "text" : "password"}
                                    required
                                    value={formData.confirmPassword}
                                    onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
                                    className="appearance-none relative block w-full px-3 py-3 border border-gray-300 rounded-md placeholder-gray-500 text-gray-900 focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 sm:text-sm"
                                    placeholder="Confirm password"
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                                    aria-label={showConfirmPassword ? "Hide password" : "Show password"}
                                    className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-500 hover:text-gray-700">
                                    {showConfirmPassword ? <AiOutlineEyeInvisible size={20} aria-hidden="true" /> : <AiOutlineEye size={20} aria-hidden="true" />}
                                </button>
                            </div>
                        </div>
                    </div>

                    <div>
                        <button
                            type="submit"
                            disabled={loading}
                            className="group relative w-full flex justify-center py-3 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-[#2E7D38] hover:bg-[#256A2E] disabled:opacity-50">
                            {loading ? "Sending..." : token ? "Sign up" : "Send request"}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
