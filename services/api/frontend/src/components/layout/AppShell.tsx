import { type ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { BottomTabBar } from './BottomTabBar';
import { CommandPalette } from './CommandPalette';

/**
 * Responsive shell.
 *   - md+ : Sidebar (left) · Main · (RightRail mounted by individual pages)
 *   - <md : Main only · BottomTabBar fixed at bottom
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden bg-bg">
      {/* Sidebar — hidden under md */}
      <div className="hidden md:flex">
        <Sidebar />
      </div>

      <div className="flex-1 flex flex-col overflow-hidden">
        <TopBar />
        <main className="flex-1 flex overflow-hidden">{children}</main>
        {/* Bottom tab bar — visible only under md */}
        <BottomTabBar />
      </div>

      {/* Global ⌘K command palette */}
      <CommandPalette />
    </div>
  );
}
