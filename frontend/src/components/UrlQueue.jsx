import { useState } from "react";
import { downloadFile } from "../services/authService";

// Progress of a queued list of links: one row per link, processed in order.
const LABELS = {
    queued: "Waiting",
    running: "Running",
    done: "Done",
    failed: "Failed",
    cancelled: "Cancelled",
};

const COLORS = {
    queued: "text-gray-600",
    running: "text-blue-700",
    done: "text-green-700",
    failed: "text-red-700",
    cancelled: "text-gray-600",
};

const UrlQueue = ({ queue, onOpen, onCancel, onRetry, onDismiss }) => {
    const [downloadError, setDownloadError] = useState("");
    const running = queue.status === "processing";
    const finished = queue.items.filter((item) => !["queued", "running"].includes(item.status)).length;
    const failed = queue.items.filter((item) => item.status === "failed").map((item) => item.url);
    const hasResults = queue.items.some((item) => item.status === "done");

    const downloadAll = async () => setDownloadError((await downloadFile(`/queue_download/${queue.queue_id}`, "omnifox_links.xlsx")) || "");

    return (
        <div className="w-full max-w-2xl mx-auto border border-gray-200 rounded-lg p-4">
            <p className="font-semibold text-gray-800 mb-3" aria-live="polite">
                Queued links: {finished} of {queue.items.length} done
            </p>
            <ul className="space-y-2">
                {queue.items.map((item) => (
                    <li key={item.url} className="flex flex-wrap items-center gap-x-3 text-sm">
                        <bdi className="flex-1 truncate text-gray-700" title={item.url}>{item.url}</bdi>
                        <span className={`font-medium ${COLORS[item.status]}`}>
                            {LABELS[item.status]}
                            {item.status === "running" && item.progress ? ` ${item.progress}%` : ""}
                        </span>
                        {item.status === "done" && item.filename && (
                            <button onClick={() => onOpen(item.filename)} className="font-medium text-blue-700 underline underline-offset-2 hover:text-blue-900">
                                View result
                            </button>
                        )}
                        {item.status === "failed" && item.message && <p className="w-full text-xs text-gray-600">{item.message}</p>}
                    </li>
                ))}
            </ul>
            {downloadError && <p className="mt-3 text-sm text-red-700">{downloadError}</p>}
            <div className="mt-4 flex flex-wrap items-center justify-end gap-4">
                {hasResults && (
                    <button onClick={downloadAll} className="text-sm font-medium text-blue-700 underline underline-offset-2 hover:text-blue-900">
                        Download all results
                    </button>
                )}
                {!running && failed.length > 0 && (
                    <button onClick={() => onRetry(failed)} className="text-sm font-medium text-blue-700 underline underline-offset-2 hover:text-blue-900">
                        Retry failed links ({failed.length})
                    </button>
                )}
                {running ? (
                    <button onClick={onCancel} className="bg-red-600 text-white font-semibold py-1.5 px-6 rounded-lg hover:bg-red-700 text-sm">
                        Cancel queue
                    </button>
                ) : (
                    <button onClick={onDismiss} className="text-sm font-medium text-gray-700 underline underline-offset-2 hover:text-gray-900">
                        Close
                    </button>
                )}
            </div>
        </div>
    );
};

export default UrlQueue;
