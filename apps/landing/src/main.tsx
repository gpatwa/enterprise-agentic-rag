import React from 'react';
import ReactDOM from 'react-dom/client';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';
import { LandingPage } from '@/pages/Landing';
import { SolutionsPage } from '@/pages/Solutions';
import './index.css';

const router = createBrowserRouter([
  { path: '/', element: <Navigate to="/welcome" replace /> },
  { path: '/welcome', element: <LandingPage /> },
  { path: '/solutions', element: <Navigate to="/solutions/everyone" replace /> },
  { path: '/solutions/:persona', element: <SolutionsPage /> },
  { path: '*', element: <Navigate to="/welcome" replace /> },
]);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
