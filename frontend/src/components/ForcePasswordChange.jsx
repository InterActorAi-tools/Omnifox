import { useState } from "react";
import { authService, errorMessage } from "../services/authService";

// Accounts made by an admin start with a temporary password that must be replaced.
export default function ForcePasswordChange() {
    const [form, setForm] = useState({ current: "", next: "", confirm: "" });
    const [error, setError] = useState("");
    const [saving, setSaving] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (form.next !== form.confirm) {
            setError("Passwords do not match");
            return;
        }
        setSaving(true);
        setError("");
        try {
            await authService.changePassword(form.current, form.next);
            await authService.getCurrentUser();
            window.location.reload();
        } catch (err) {
            setError(errorMessage(err, "Could not change your password"));
            setSaving(false);
        }
    };

    const field = (key, label, autoComplete) => (
        <div>
            <label htmlFor={key} className="block text-sm font-medium text-gray-700">{label}</label>
            <input
                id={key}
                type="password"
                required
                autoComplete={autoComplete}
                value={form[key]}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                className="mt-1 block w-full px-3 py-3 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500 sm:text-sm"
            />
        </div>
    );

    return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4">
            <form onSubmit={handleSubmit} className="max-w-md w-full bg-white shadow-xl rounded-2xl p-8 space-y-4">
                <h1 className="text-2xl font-extrabold text-gray-900">Choose a new password</h1>
                <p className="text-sm text-gray-600">Your account was set up with a temporary password. Pick your own to continue. It needs at least 8 characters with upper and lower case letters, a number and a special character.</p>
                {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-800">{error}</p>}
                {field("current", "Temporary password", "current-password")}
                {field("next", "New password", "new-password")}
                {field("confirm", "Confirm new password", "new-password")}
                <button type="submit" disabled={saving} className="w-full py-3 rounded-md text-white font-medium bg-[#2E7D38] hover:bg-[#256A2E] disabled:opacity-50">
                    {saving ? "Saving..." : "Save password"}
                </button>
            </form>
        </div>
    );
}
