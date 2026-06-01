import {
  Home,
  MessageSquare,
  Bookmark,
  LayoutDashboard,
  Database,
  Brain,
  Bot,
  LifeBuoy,
  Settings,
  ChevronsUpDown,
  type LucideIcon,
} from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { cn } from '@/lib/utils';

interface NavItem {
  icon: LucideIcon;
  label: string;
  to: string;
  badge?: string;
}

const primaryNav: NavItem[] = [
  { icon: Home, label: 'Home', to: '/' },
  { icon: MessageSquare, label: 'Threads', to: '/threads', badge: '12' },
  { icon: Bookmark, label: 'Saved', to: '/saved', badge: '5' },
  { icon: LayoutDashboard, label: 'Dashboards', to: '/dashboards' },
];

const workspaceNav: NavItem[] = [
  { icon: Database, label: 'Sources', to: '/sources' },
  { icon: LifeBuoy, label: 'Resolution', to: '/support' },
  { icon: Brain, label: 'Knowledge', to: '/knowledge' },
  { icon: Bot, label: 'Agents', to: '/agents', badge: 'Beta' },
];

export function Sidebar() {
  return (
    <aside className="w-[244px] flex-shrink-0 glass-strong border-r flex flex-col">
      {/* Tenant switcher */}
      <div className="px-3 py-3 border-b">
        <button className="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md hover:bg-white/5 transition">
          <span className="w-7 h-7 rounded-md bg-accent-grad flex items-center justify-center text-xs font-bold text-white shadow-lg shadow-accent/20">
            A
          </span>
          <div className="flex-1 text-left min-w-0">
            <div className="text-sm font-medium truncate">Acme Corp</div>
            <div className="text-xs text-fg-muted truncate">Enterprise · us-east-1</div>
          </div>
          <ChevronsUpDown className="w-3.5 h-3.5 text-fg-muted" />
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-auto">
        {primaryNav.map((item) => (
          <SidebarLink key={item.to} {...item} />
        ))}

        <div className="mt-5 mb-2 px-2.5 text-xs uppercase tracking-wider text-fg-muted font-medium">
          Workspace
        </div>
        {workspaceNav.map((item) => (
          <SidebarLink key={item.to} {...item} />
        ))}
      </nav>

      {/* User */}
      <div className="px-3 py-3 border-t">
        <button className="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md hover:bg-white/5 transition">
          <span className="w-7 h-7 rounded-full bg-gradient-to-br from-orange-400 to-pink-500 flex items-center justify-center text-xs font-medium text-white">
            G
          </span>
          <div className="flex-1 text-left min-w-0">
            <div className="text-sm font-medium truncate">Gopal</div>
            <div className="text-xs text-fg-muted truncate">admin · acme-prod</div>
          </div>
          <Settings className="w-4 h-4 text-fg-muted" />
        </button>
      </div>
    </aside>
  );
}

function SidebarLink({ icon: Icon, label, to, badge }: NavItem) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-sm transition',
          isActive
            ? 'bg-white/5 text-fg font-medium'
            : 'text-fg-secondary hover:bg-white/5 hover:text-fg'
        )
      }
    >
      <Icon className="w-4 h-4" />
      <span className="flex-1">{label}</span>
      {badge && (
        <span
          className={cn(
            'text-xs',
            badge === 'Beta'
              ? 'px-1.5 py-0.5 rounded bg-accent/15 text-accent border border-accent/25'
              : 'text-fg-muted'
          )}
        >
          {badge}
        </span>
      )}
    </NavLink>
  );
}
