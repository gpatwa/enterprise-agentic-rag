import { type ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

/**
 * Three-pane shell: Sidebar · Main · (RightRail mounted by individual pages).
 * Mobile: Sidebar collapses to bottom tab bar (W3).
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden bg-bg">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden">
        <TopBar />
        <div className="flex-1 flex overflow-hidden">{children}</div>
      </main>
    </div>
  );
}
