import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FaHistory, FaDownload, FaTrash, FaFolderOpen } from "react-icons/fa";
import Modal from "./Modal";
import { authService, downloadFile, notifyResultsChanged } from "../services/authService";

const formatDate = (value) => new Date(value).toLocaleDateString("en-GB", {
  year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
});

// Your results from the last 30 days, stored on the server so they are the
// same on every device. Open shows a result (and its chat) again.
export const HistoryModal = ({ isOpen, onClose, user }) => {
  const [results, setResults] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [errors, setErrors] = useState({});
  const navigate = useNavigate();

  useEffect(() => {
    if (!isOpen || !user?.email) return;
    setResults(null);
    setLoadError("");
    authService.listResults()
      .then(setResults)
      .catch(() => setLoadError("Could not load your results. Please try again."));
  }, [isOpen, user]);

  const setError = (filename, message) => setErrors((current) => ({ ...current, [filename]: message }));

  const handleOpen = (item) => {
    navigate(`/app?result=${encodeURIComponent(item.filename)}`);
    onClose();
  };

  const handleDownload = async (item) => {
    setError(item.filename, await downloadFile(`/download/${encodeURIComponent(user.email)}/${encodeURIComponent(item.filename)}`, item.filename));
  };

  const handleDelete = async (item) => {
    try {
      await authService.deleteResult(item.filename);
    } catch (err) {
      if (err.response?.status !== 404) {
        setError(item.filename, "Could not delete this result. Please try again.");
        return;
      }
    }
    setResults((current) => current.filter((r) => r.filename !== item.filename));
    notifyResultsChanged({ deleted: item.filename });
  };

  if (!isOpen) return null;

  return (
    <Modal
      title={`Your results${results ? ` (${results.length})` : ""}`}
      onClose={onClose}
      className="max-w-4xl"
      titleClassName="text-2xl font-bold mb-4 pr-12"
    >
      <button
        onClick={onClose}
        aria-label="Close"
        className="absolute top-4 right-4 p-2 text-gray-500 hover:text-gray-700 text-2xl font-bold leading-none"
      >
        <span aria-hidden="true">×</span>
      </button>

      <p className="text-sm text-gray-600 mb-4 -mt-2">
        Results from the last 30 days, on any device. Open one to see it again and continue its chat.
      </p>

      {loadError && <p role="alert" className="text-sm text-red-700">{loadError}</p>}
      {!results && !loadError && <p role="status" className="text-sm text-gray-600">Loading…</p>}

      {results && results.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          <FaHistory aria-hidden="true" className="mx-auto text-6xl mb-4 text-gray-300" />
          <p className="text-xl">No results yet</p>
          <p className="text-sm mt-2">Your analyses will appear here</p>
        </div>
      )}

      {results && results.length > 0 && (
        <ul className="space-y-4">
          {results.map((item) => (
            <li key={item.filename} className="border rounded-lg p-4 bg-white">
              <div className="flex flex-col md:flex-row md:justify-between md:items-center gap-3">
                <div className="min-w-0">
                  <p dir="auto" className="font-bold text-lg mb-2 break-all">{item.source}</p>
                  <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-gray-700">
                    <div><dt className="inline text-gray-600">Date: </dt><dd className="inline">{formatDate(item.created_at)}</dd></div>
                    <div><dt className="inline text-gray-600">Project: </dt><dd dir="auto" className="inline font-semibold">{item.project || "N/A"}</dd></div>
                    <div><dt className="inline text-gray-600">Comments: </dt><dd className="inline font-semibold">{item.total_comments}</dd></div>
                    <div><dt className="inline text-gray-600">Positive: </dt><dd className="inline font-semibold">{item.sentiment_counts?.positive || 0}</dd></div>
                    <div><dt className="inline text-gray-600">Neutral: </dt><dd className="inline font-semibold">{item.sentiment_counts?.neutral || 0}</dd></div>
                    <div><dt className="inline text-gray-600">Negative: </dt><dd className="inline font-semibold">{item.sentiment_counts?.negative || 0}</dd></div>
                  </dl>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => handleOpen(item)}
                    aria-label={`Open ${item.source}`}
                    className="border border-gray-300 text-gray-800 px-3 py-2 rounded text-sm hover:bg-gray-50 flex items-center gap-1"
                  >
                    <FaFolderOpen aria-hidden="true" />
                    Open
                  </button>
                  <button
                    onClick={() => handleDownload(item)}
                    aria-label={`Download ${item.source}`}
                    className="bg-green-700 text-white px-3 py-2 rounded text-sm hover:bg-green-800 flex items-center gap-1"
                  >
                    <FaDownload aria-hidden="true" />
                    Download
                  </button>
                  <button
                    onClick={() => handleDelete(item)}
                    aria-label={`Delete ${item.source}`}
                    className="bg-red-600 text-white px-3 py-2 rounded text-sm hover:bg-red-700 flex items-center gap-1"
                  >
                    <FaTrash aria-hidden="true" />
                    Delete
                  </button>
                </div>
              </div>
              {errors[item.filename] && <p role="alert" className="mt-3 text-sm text-red-700">{errors[item.filename]}</p>}
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
};
