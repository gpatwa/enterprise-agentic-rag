import { Search, Bell, HelpCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function TopBar() {
  return (
    <header className="h-14 flex-shrink-0 glass border-b flex items-center px-6 gap-3">
      <button className="flex items-center gap-2 px-3 py-1.5 rounded-md glass hover:border-border-strong transition w-[440px] text-fg-muted text-sm">
        <Search className="w-4 h-4" />
        <span className="flex-1 text-left">Search threads, questions, sources…</span>
        <span className="font-mono text-xs px-1.5 py-0.5 bg-white/5 rounded border">⌘K</span>
      </button>
      <div className="flex-1" />
      <Button variant="ghost" size="icon" aria-label="Notifications">
        <Bell className="w-4 h-4" />
      </Button>
      <Button variant="ghost" size="icon" aria-label="Help">
        <HelpCircle className="w-4 h-4" />
      </Button>
    </header>
  );
}
