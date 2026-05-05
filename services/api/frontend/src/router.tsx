import { lazy, Suspense, type ReactNode } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { StubPage } from '@/pages/StubPage';
import { LayoutDashboard, Bot } from 'lucide-react';

/**
 * Route-level code splitting.
 * Each page is a separate Vite chunk; only the active route's code is fetched.
 * HomePage and LandingPage stay eager — both are entry surfaces and we want
 * zero Suspense flash for first paint on either.
 */
import { HomePage } from '@/pages/Home';
import { LandingPage } from '@/pages/Landing';
const ThreadsPage = lazy(() =>
  import('@/pages/Threads').then((m) => ({ default: m.ThreadsPage }))
);
const ThreadDetailPage = lazy(() =>
  import('@/pages/ThreadDetail').then((m) => ({ default: m.ThreadDetailPage }))
);
const SavedPage = lazy(() =>
  import('@/pages/Saved').then((m) => ({ default: m.SavedPage }))
);
const SourcesPage = lazy(() =>
  import('@/pages/Sources').then((m) => ({ default: m.SourcesPage }))
);
const KnowledgePage = lazy(() =>
  import('@/pages/Knowledge').then((m) => ({ default: m.KnowledgePage }))
);
const SolutionsPage = lazy(() =>
  import('@/pages/Solutions').then((m) => ({ default: m.SolutionsPage }))
);
const AgentsPage = lazy(() =>
  import('@/pages/Agents').then((m) => ({ default: m.AgentsPage }))
);
const DashboardsPage = lazy(() =>
  import('@/pages/Dashboards').then((m) => ({ default: m.DashboardsPage }))
);

/** Shared layout with Suspense fallback for lazy children. */
function RootLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell>
      <Suspense fallback={<RouteSkeleton />}>{children}</Suspense>
    </AppShell>
  );
}

function RouteSkeleton() {
  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 md:px-8 py-12">
        <div className="space-y-3">
          <div className="h-7 w-1/3 bg-surface-muted rounded animate-pulse" />
          <div className="h-4 w-1/2 bg-surface-muted rounded animate-pulse" />
          <div className="h-32 bg-surface-muted rounded-lg animate-pulse mt-6" />
        </div>
      </div>
    </div>
  );
}

export const router = createBrowserRouter([
  // Public marketing landing — no AppShell, no auth. Mounts its own
  // PublicLayout (header + footer only). SEO entry point.
  {
    path: '/welcome',
    element: <LandingPage />,
  },
  {
    path: '/',
    element: (
      <RootLayout>
        <HomePage />
      </RootLayout>
    ),
  },
  {
    path: '/threads',
    element: (
      <RootLayout>
        <ThreadsPage />
      </RootLayout>
    ),
  },
  {
    path: '/threads/:threadId',
    element: (
      <RootLayout>
        <ThreadDetailPage />
      </RootLayout>
    ),
  },
  {
    path: '/saved',
    element: (
      <RootLayout>
        <SavedPage />
      </RootLayout>
    ),
  },
  {
    path: '/dashboards',
    element: (
      <RootLayout>
        <DashboardsPage />
      </RootLayout>
    ),
  },
  {
    path: '/sources',
    element: (
      <RootLayout>
        <SourcesPage />
      </RootLayout>
    ),
  },
  {
    path: '/knowledge',
    element: (
      <RootLayout>
        <KnowledgePage />
      </RootLayout>
    ),
  },
  {
    path: '/agents',
    element: (
      <RootLayout>
        <AgentsPage />
      </RootLayout>
    ),
  },
  {
    path: '/solutions',
    element: <Navigate to="/solutions/everyone" replace />,
  },
  {
    path: '/solutions/:persona',
    element: (
      <RootLayout>
        <SolutionsPage />
      </RootLayout>
    ),
  },
  // Fallback
  {
    path: '*',
    element: <Navigate to="/" replace />,
  },
]);

// Silence "unused" for icons used only by historical stubs we kept around
void LayoutDashboard;
void Bot;
void StubPage;
