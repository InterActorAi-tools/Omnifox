import { useState, useEffect } from 'react';
import { FaHistory } from 'react-icons/fa';
import { HistoryModal } from './HistoryComponent';
import { authService, RESULTS_CHANGED } from '../services/authService';

const Info = ({ user }) => {
  const [showHistoryModal, setShowHistoryModal] = useState(false);
  const [resultCount, setResultCount] = useState(null);

  // Count the user's results now and whenever one is added or deleted.
  useEffect(() => {
    if (!user?.email) return;
    // History used to live in this browser; it is on the server now.
    localStorage.removeItem(`omnicat_history_${user.email}`);
    const refresh = () => authService.listResults().then((r) => setResultCount(r.length)).catch(() => {});
    refresh();
    window.addEventListener(RESULTS_CHANGED, refresh);
    return () => window.removeEventListener(RESULTS_CHANGED, refresh);
  }, [user]);

  if (!user?.email) return null;

  return (
    <>
      <div className="flex flex-col items-center mt-5">
        <div className="flex gap-4 m-6">
          <button
            onClick={() => setShowHistoryModal(true)}
            className="bg-white text-gray-700 font-semibold py-1.5 px-12 rounded-lg hover:bg-gray-50 flex items-center justify-center gap-2 border border-gray-300"
          >
            <FaHistory aria-hidden="true" />
            View History{resultCount !== null && ` (${resultCount})`}
          </button>
        </div>
      </div>

      <HistoryModal
        isOpen={showHistoryModal}
        onClose={() => setShowHistoryModal(false)}
        user={user}
      />
    </>
  );
};

export default Info;
