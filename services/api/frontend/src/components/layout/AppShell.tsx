import { type ReactNode, useEffect } from 'react';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { BottomTabBar } from './BottomTabBar';
import { CommandPalette } from './CommandPalette';
import { track } from '@/lib/analytics';

/**
 * Responsive shell.
 *   - md+ : Sidebar (left) · Main · (RightRail mounted by individual pages)
 *   - <md : Main only · BottomTabBar fixed at bottom
 */
export function AppShell({ children }: { children: ReactNode }) {
  // One-time app-load event
  useEffect(() => {
    track('app.loaded', {});
  }, []);

  return (
    <div className="flex h-screen overflow-hidden bg-bg">
      {/* Skip-to-content link — hidden until keyboard-focused */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-accent focus:text-accent-fg focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium"
      >
        Skip to main content
      </a>

      {/* Sidebar — hidden under md */}
      <div className="hidden md:flex">
        <Sidebar />
      </div>

      <div className="flex-1 flex flex-col overflow-hidden">
        <TopBar />
        <main id="main" className="flex-1 flex overflow-hidden" tabIndex={-1}>
          {children}
        </main>
        {/* Bottom tab bar — visible only under md */}
        <BottomTabBar />
      </div>

      {/* Global ⌘K command palette */}
      <CommandPalette />
    </div>
  );
}
