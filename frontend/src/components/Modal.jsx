import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import PropTypes from "prop-types";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// Accessible dialog wrapper: role="dialog", Escape closes, focus moves into
// the dialog on open, Tab stays inside it, and focus returns to the
// element that opened it on close. Rendered into <body> so no parent
// stacking context (e.g. the sticky navbar) can sit above the overlay.
export default function Modal({ title, onClose, children, className = "max-w-md", titleClassName = "text-lg font-bold text-gray-900 mb-4" }) {
    const dialogRef = useRef(null);
    const onCloseRef = useRef(onClose);
    onCloseRef.current = onClose;
    const titleId = useId();

    useEffect(() => {
        const opener = document.activeElement;
        const dialog = dialogRef.current;
        (dialog.querySelector("[autofocus]") || dialog.querySelector(FOCUSABLE) || dialog).focus();

        const onKeyDown = (e) => {
            if (e.key === "Escape") {
                e.stopPropagation();
                onCloseRef.current();
                return;
            }
            if (e.key !== "Tab") return;
            const items = [...dialog.querySelectorAll(FOCUSABLE)];
            if (items.length === 0) return;
            const first = items[0];
            const last = items[items.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        };
        dialog.addEventListener("keydown", onKeyDown);
        return () => {
            dialog.removeEventListener("keydown", onKeyDown);
            opener?.focus?.();
        };
    }, []);

    return createPortal(
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div
                ref={dialogRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                tabIndex={-1}
                className={`relative bg-white rounded-2xl shadow-2xl w-full max-h-[90vh] overflow-y-auto p-4 sm:p-6 border border-gray-100 focus:outline-none ${className}`}>
                <h2 id={titleId} className={titleClassName}>{title}</h2>
                {children}
            </div>
        </div>,
        document.body
    );
}

Modal.propTypes = {
    title: PropTypes.node.isRequired,
    onClose: PropTypes.func.isRequired,
    children: PropTypes.node,
    className: PropTypes.string,
    titleClassName: PropTypes.string,
};
