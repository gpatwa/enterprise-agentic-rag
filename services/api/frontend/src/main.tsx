import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { initSentry, SentryErrorBoundary } from './lib/sentry';
import './index.css';

// Initialise Sentry FIRST so React render-phase errors are captured.
// No-op when VITE_SENTRY_DSN is unset.
initSentry();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <SentryErrorBoundary>
      <App />
    </SentryErrorBoundary>
  </React.StrictMode>
);
