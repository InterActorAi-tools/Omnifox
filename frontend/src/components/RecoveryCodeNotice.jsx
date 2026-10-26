import { useEffect, useState } from "react";
import Modal from "./Modal";
import { RECOVERY_CODE_KEY } from "../services/authService";

const storedCode = () => {
    try {
        return sessionStorage.getItem(RECOVERY_CODE_KEY);
    } catch {
        return null;
    }
};

// Shows the private-project recovery code once, right after it is created.
export default function RecoveryCodeNotice() {
    const [code, setCode] = useState(storedCode);
    const [copied, setCopied] = useState(false);

    useEffect(() => {
        const onCode = (e) => setCode(e.detail);
        window.addEventListener("recovery-code", onCode);
        return () => window.removeEventListener("recovery-code", onCode);
    }, []);

    if (!code) return null;

    const close = () => {
        try {
            sessionStorage.removeItem(RECOVERY_CODE_KEY);
        } catch { /* nothing stored */ }
        setCode(null);
    };

    const copy = async () => {
        try {
            await navigator.clipboard.writeText(code);
            setCopied(true);
        } catch { /* the code stays on screen to copy by hand */ }
    };

    return (
        <Modal title="Save your recovery code" onClose={close}>
            <p className="text-sm text-gray-700 mb-3">
                Private projects are locked with your password. If you ever reset your password, this code is the only way to open them again. It is shown only once.
            </p>
            <p className="font-mono text-lg text-center bg-gray-100 rounded-lg p-3 mb-4 select-all break-all">{code}</p>
            <div className="flex flex-col sm:flex-row gap-3">
                <button
                    type="button"
                    onClick={copy}
                    className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50">
                    {copied ? "Copied" : "Copy"}
                </button>
                <button
                    type="button"
                    onClick={close}
                    className="flex-1 px-4 py-2 bg-green-700 text-white rounded-lg hover:bg-green-800">
                    I have saved it
                </button>
            </div>
        </Modal>
    );
}
