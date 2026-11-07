import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { authConfigFromEnv, isMsalSilentFrame } from './api/auth';

// MSAL's hidden sign-in frame loads this page with the response in its hash; it must not run the app or it would consume that hash.
if (!(authConfigFromEnv(import.meta.env) && isMsalSilentFrame())) {
  createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
}
