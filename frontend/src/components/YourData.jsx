import { useState } from "react";
import { authService, clearAuthStorage, downloadFile } from "../services/authService";
import Modal from "./Modal";

// What this browser keeps for the user (history, task resume state).
const clearLocalData = (email) => {
    localStorage.removeItem(`omnicat_history_${email}`);
    localStorage.removeItem(`omnicat_active_task_${email}`);
    localStorage.removeItem("omnicat_client_id");
};

const ACTIONS = {
    data: {
        title: "Delete all your data?",
        text: "Your files, results, analyses and activity history are erased for good. Your account stays.",
        button: "Delete my data",
    },
    account: {
        title: "Delete your account?",
        text: "Your account and everything linked to it are erased for good. You will be signed out.",
        button: "Delete my account",
    },
};

// GDPR self-service: download or erase everything held about the user.
export default function YourData({ email }) {
    const [confirming, setConfirming] = useState(null);
    const [typedEmail, setTypedEmail] = useState("");
    const [error, setError] = useState("");
    const [status, setStatus] = useState("");
    const [busy, setBusy] = useState(false);

    const download = async () => {
        setError("");
        setBusy(true);
        const failure = await downloadFile("/users/me/export", "omnicat-my-data.zip");
        setBusy(false);
        if (failure) setError("Could not prepare your data. Please try again.");
    };

    const close = () => {
        setConfirming(null);
        setTypedEmail("");
        setError("");
    };

    const confirm = async () => {
        setBusy(true);
        setError("");
        try {
            if (confirming === "account") {
                await authService.deleteMyAccount(typedEmail);
                clearLocalData(email);
                clearAuthStorage();
                window.location.href = "/login";
                return;
            }
            await authService.deleteMyData(typedEmail);
            clearLocalData(email);
            close();
            setStatus("All your data has been deleted.");
        } catch (err) {
            setError(err.response?.data?.detail || "Something went wrong. Please try again.");
        } finally {
            setBusy(false);
        }
    };

    const action = confirming && ACTIONS[confirming];

    return (
        <section aria-labelledby="your-data-heading" className="bg-white overflow-hidden shadow rounded-lg md:col-span-3">
            <div className="px-4 py-5 sm:p-6">
                <h2 id="your-data-heading" className="text-lg font-medium text-gray-900">Your data</h2>
                <p className="text-sm text-gray-600 mt-1 mb-4">
                    Results and files are kept for 30 days and account activity for 365 days. Everything is stored
                    encrypted, and admins cannot see your files, results, devices or IP addresses.
                </p>
                {status && <p role="status" className="mb-3 text-sm text-green-700">{status}</p>}
                {error && !confirming && <p role="alert" className="mb-3 text-sm text-red-700">{error}</p>}
                <div className="flex flex-col sm:flex-row gap-3">
                    <button
                        onClick={download}
                        disabled={busy}
                        className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 disabled:opacity-60">
                        Download my data
                    </button>
                    <button
                        onClick={() => setConfirming("data")}
                        className="px-4 py-2 border border-red-300 text-red-700 rounded-lg text-sm font-medium hover:bg-red-50">
                        Delete all my data
                    </button>
                    <button
                        onClick={() => setConfirming("account")}
                        className="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700">
                        Delete my account
                    </button>
                </div>
            </div>

            {action && (
                <Modal title={action.title} onClose={close}>
                    <p className="text-sm text-gray-600 mb-4">{action.text}</p>
                    <label htmlFor="confirm-email" className="block text-sm font-medium text-gray-700 mb-1">
                        Type your email address to confirm
                    </label>
                    <input
                        id="confirm-email"
                        type="email"
                        autoComplete="off"
                        value={typedEmail}
                        onChange={(e) => setTypedEmail(e.target.value)}
                        aria-describedby={error ? "confirm-error" : undefined}
                        className="w-full mb-3 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500"
                    />
                    {error && <p id="confirm-error" role="alert" className="mb-3 text-sm text-red-700">{error}</p>}
                    <div className="flex gap-3">
                        <button onClick={close} className="flex-1 py-2 bg-gray-100 text-gray-800 rounded-lg font-medium hover:bg-gray-200">
                            Cancel
                        </button>
                        <button
                            onClick={confirm}
                            disabled={busy || typedEmail.trim().toLowerCase() !== email.toLowerCase()}
                            className="flex-1 py-2 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 disabled:opacity-60">
                            {action.button}
                        </button>
                    </div>
                </Modal>
            )}
        </section>
    );
}
