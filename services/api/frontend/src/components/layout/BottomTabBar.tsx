import { Home, MessageSquare, Bookmark, MoreHorizontal } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { cn } from '@/lib/utils';

const tabs = [
  { icon: Home, label: 'Home', to: '/' },
  { icon: MessageSquare, label: 'Threads', to: '/threads' },
  { icon: Bookmark, label: 'Saved', to: '/saved' },
  { icon: MoreHorizontal, label: 'More', to: '/sources' },
] as const;

export function BottomTabBar() {
  return (
    <nav
      className="md:hidden flex-shrink-0 glass-strong border-t flex h-16 pb-safe"
      aria-label="Primary navigation"
    >
      {tabs.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.to === '/'}
          className={({ isActive }) =>
            cn(
              'flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] uppercase tracking-wider transition',
              isActive ? 'text-accent' : 'text-fg-muted'
            )
          }
        >
          <t.icon className="w-5 h-5" />
          <span>{t.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
