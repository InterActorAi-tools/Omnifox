import { useEffect, useState } from "react";
import { AiOutlineDesktop } from "react-icons/ai";
import { authService } from "../services/authService";
import Modal from "./Modal";
import { describeDevice } from "../utils/device";

const formatAction = (action) => (action || "").replaceAll("_", " ");

// Profile cards for every user: active sessions (with revoke / sign out
// everywhere) and the user's own recent account activity.
export default function AccountSecurity() {
    const [sessions, setSessions] = useState([]);
    const [activity, setActivity] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [confirmSignOut, setConfirmSignOut] = useState(false);

    useEffect(() => {
        Promise.all([authService.getSessions(), authService.getActivity(20)])
            .then(([sessionData, activityData]) => {
                setSessions(sessionData);
                setActivity(activityData);
            })
            .catch(() => setError("Could not load your sessions and activity. Please reload the page."))
            .finally(() => setLoading(false));
    }, []);

    const revoke = async (sessionId) => {
        setError("");
        try {
            await authService.deleteSession(sessionId);
            setSessions((current) => current.filter((s) => s.id !== sessionId));
        } catch {
            setError("Could not sign out that device. Please try again.");
        }
    };

    const signOutEverywhere = async () => {
        try {
            await authService.logoutAllDevices();
        } finally {
            window.location.href = "/login";
        }
    };

    return (
        <>
            <section aria-labelledby="sessions-heading" className="bg-white overflow-hidden shadow rounded-lg md:col-span-3">
                <div className="px-4 py-5 sm:p-6">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
                        <div>
                            <h2 id="sessions-heading" className="text-lg font-medium text-gray-900">Signed-in devices</h2>
                            <p className="text-sm text-gray-600">Sign out any device you don&apos;t recognise.</p>
                        </div>
                        {sessions.length > 0 && (
                            <button
                                onClick={() => setConfirmSignOut(true)}
                                className="px-4 py-2 border border-red-300 text-red-700 rounded-lg text-sm font-medium hover:bg-red-50">
                                Sign out everywhere
                            </button>
                        )}
                    </div>
                    {error && <p role="alert" className="mb-3 text-sm text-red-700">{error}</p>}
                    {loading ? (
                        <p role="status" className="text-sm text-gray-600">Loading…</p>
                    ) : sessions.length === 0 ? (
                        <p className="text-sm text-gray-600">No active sessions.</p>
                    ) : (
                        <ul className="divide-y divide-gray-100">
                            {sessions.map((session) => (
                                <li key={session.id} className="py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                                    <div className="flex items-start gap-3 min-w-0">
                                        <AiOutlineDesktop aria-hidden="true" size={20} className="text-gray-500 shrink-0 mt-0.5" />
                                        <div className="min-w-0">
                                            <p className="text-sm font-medium text-gray-900 truncate" title={session.device_name}>{describeDevice(session.device_name)}</p>
                                            <p className="text-xs text-gray-600">
                                                IP {session.ip_address || "unknown"} · last used {new Date(session.last_used).toLocaleString()}
                                            </p>
                                        </div>
                                    </div>
                                    <button
                                        onClick={() => revoke(session.id)}
                                        aria-label={`Sign out ${describeDevice(session.device_name)}, last used ${new Date(session.last_used).toLocaleString()}`}
                                        className="w-full sm:w-auto px-4 py-2 text-sm border border-gray-300 text-gray-700 rounded-lg hover:border-red-300 hover:text-red-700 hover:bg-red-50">
                                        Sign out
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            </section>

            <section aria-labelledby="activity-heading" className="bg-white overflow-hidden shadow rounded-lg md:col-span-3">
                <div className="px-4 py-5 sm:p-6">
                    <h2 id="activity-heading" className="text-lg font-medium text-gray-900">Recent account activity</h2>
                    <p className="text-sm text-gray-600 mb-4">Your last 20 sign-ins, uploads and account changes.</p>
                    {loading ? (
                        <p role="status" className="text-sm text-gray-600">Loading…</p>
                    ) : activity.length === 0 ? (
                        <p className="text-sm text-gray-600">No activity yet.</p>
                    ) : (
                        <ul className="divide-y divide-gray-100">
                            {activity.map((log) => (
                                <li key={log.id} className="py-2 flex justify-between gap-4 text-sm">
                                    <span className="text-gray-900 capitalize">{formatAction(log.action)}</span>
                                    <time dateTime={log.created_at} className="text-gray-600 shrink-0">
                                        {new Date(log.created_at).toLocaleString()}
                                    </time>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            </section>

            {confirmSignOut && (
                <Modal title="Sign out everywhere?" onClose={() => setConfirmSignOut(false)}>
                    <p className="text-sm text-gray-600 mb-6">
                        You will be signed out on all devices, including this one, and need to sign in again.
                    </p>
                    <div className="flex gap-3">
                        <button
                            onClick={() => setConfirmSignOut(false)}
                            className="flex-1 py-2 bg-gray-100 text-gray-800 rounded-lg font-medium hover:bg-gray-200">
                            Cancel
                        </button>
                        <button onClick={signOutEverywhere} className="flex-1 py-2 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700">
                            Sign out everywhere
                        </button>
                    </div>
                </Modal>
            )}
        </>
    );
}
