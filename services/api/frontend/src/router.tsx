import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { HomePage } from '@/pages/Home';
import { ThreadsPage } from '@/pages/Threads';
import { ThreadDetailPage } from '@/pages/ThreadDetail';
import { SavedPage } from '@/pages/Saved';
import { SolutionsPage } from '@/pages/Solutions';
import { SourcesPage } from '@/pages/Sources';
import { KnowledgePage } from '@/pages/Knowledge';
import { StubPage } from '@/pages/StubPage';
import {
  LayoutDashboard,
  Bot,
} from 'lucide-react';

/** Root layout — same AppShell for every authenticated route. */
function RootLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}

export const router = createBrowserRouter([
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
        <StubPage
          icon={LayoutDashboard}
          title="Dashboards"
          description="Multi-question panels assembled from saved questions. Auto-refreshing, shareable, embeddable."
          ship="W3"
        />
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
        <StubPage
          icon={Bot}
          title="Skills marketplace"
          description="Pre-configured Skills for Finance, RevOps, Engineering, Security. Install, customize, and build your own."
          ship="Q3"
        />
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
