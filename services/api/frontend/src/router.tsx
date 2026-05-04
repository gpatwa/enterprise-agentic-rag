import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { HomePage } from '@/pages/Home';
import { ThreadsPage } from '@/pages/Threads';
import { ThreadDetailPage } from '@/pages/ThreadDetail';
import { SavedPage } from '@/pages/Saved';
import { SolutionsPage } from '@/pages/Solutions';
import { StubPage } from '@/pages/StubPage';
import {
  LayoutDashboard,
  Database,
  Brain,
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
        <StubPage
          icon={Database}
          title="Sources"
          description="Connect data sources, monitor freshness and ingestion health, and configure sync schedules."
          ship="W2"
        />
      </RootLayout>
    ),
  },
  {
    path: '/knowledge',
    element: (
      <RootLayout>
        <StubPage
          icon={Brain}
          title="Knowledge layers"
          description="Manage glossary, business rules, and code lineage entries. Token-budgeted assembly, role-scoped, version-controlled."
          ship="W2"
        />
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
