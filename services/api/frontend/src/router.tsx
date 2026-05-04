import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { HomePage } from '@/pages/Home';
import { StubPage } from '@/pages/StubPage';
import {
  MessageSquare,
  Bookmark,
  LayoutDashboard,
  Database,
  Brain,
  Bot,
  Users,
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
        <StubPage
          icon={MessageSquare}
          title="Threads"
          description="Persistent conversations with full context, evidence, and audit. Pick up where you left off, share with teammates, and pin recurring questions."
          ship="W2"
        />
      </RootLayout>
    ),
  },
  {
    path: '/threads/:threadId',
    element: (
      <RootLayout>
        <StubPage
          icon={MessageSquare}
          title="Thread detail"
          description="Single-thread view with the answer card stack, right-rail sources & reasoning, and follow-up suggestions."
          ship="W3"
        />
      </RootLayout>
    ),
  },
  {
    path: '/saved',
    element: (
      <RootLayout>
        <StubPage
          icon={Bookmark}
          title="Saved questions"
          description="Bookmarked questions you re-run on a schedule. Each saved question keeps its last result, freshness, and a one-click re-run."
          ship="W2"
        />
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
    path: '/solutions/:persona',
    element: (
      <RootLayout>
        <StubPage
          icon={Users}
          title="Solutions"
          description="Persona-specific landing pages: Finance, RevOps, Data, Engineering, Security, Everyone. PERSONA_CONTENT in src/pages/Solutions.tsx is pre-shaped."
          ship="W2"
        />
      </RootLayout>
    ),
  },
  // Fallback
  {
    path: '*',
    element: <Navigate to="/" replace />,
  },
]);
