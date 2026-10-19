import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';

// After a deploy, an open tab may ask for code chunks that no longer exist:
// reload once to pick up the new version instead of showing a broken page.
window.addEventListener('vite:preloadError', () => {
  try {
    if (sessionStorage.getItem('reloadedForNewVersion')) return;
    sessionStorage.setItem('reloadedForNewVersion', '1');
  } catch {
    return; // storage blocked: do not risk a reload loop
  }
  window.location.reload();
});

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)