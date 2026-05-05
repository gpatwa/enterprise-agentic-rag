import { Search, Bell, HelpCircle, Menu } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ThemeToggle } from './ThemeToggle';
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet';
import { Sidebar } from './Sidebar';

function openPalette() {
  window.dispatchEvent(new CustomEvent('compass:open-palette'));
}

export function TopBar() {
  return (
    <header className="h-14 flex-shrink-0 glass border-b flex items-center px-4 md:px-6 gap-3">
      {/* Mobile-only menu — opens sidebar in a sheet */}
      <Sheet>
        <SheetTrigger asChild>
          <Button variant="ghost" size="icon" aria-label="Menu" className="md:hidden">
            <Menu className="w-5 h-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-[280px] p-0 border-r-0">
          <div className="h-full">
            <Sidebar />
          </div>
        </SheetContent>
      </Sheet>

      {/* Search button — collapses to icon on mobile. Opens ⌘K palette. */}
      <button
        onClick={openPalette}
        className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-md glass hover:border-border-strong transition w-[440px] text-fg-muted text-sm cursor-pointer"
      >
        <Search className="w-4 h-4" />
        <span className="flex-1 text-left">Search threads, questions, sources…</span>
        <span className="font-mono text-xs px-1.5 py-0.5 bg-white/5 rounded border">⌘K</span>
      </button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Search"
        className="md:hidden"
        onClick={openPalette}
      >
        <Search className="w-4 h-4" />
      </Button>

      <div className="flex-1" />
      <ThemeToggle />
      <Button variant="ghost" size="icon" aria-label="Notifications" className="hidden sm:flex">
        <Bell className="w-4 h-4" />
      </Button>
      <Button variant="ghost" size="icon" aria-label="Help" className="hidden sm:flex">
        <HelpCircle className="w-4 h-4" />
      </Button>
    </header>
  );
}
