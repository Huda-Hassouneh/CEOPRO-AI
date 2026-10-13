import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import { initErrorTracking } from './shared/lib/errorTracking.js';
import './styles/globals.css';
import './styles/apex-theme.css';
import './styles/apex-components.css';
import './styles/apex-motion.css';
import './styles/keel-glass.css';
import './features/system/pages/WelcomePage.css';

// Off unless VITE_SENTRY_DSN is set; never delays the first render.
initErrorTracking();

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
