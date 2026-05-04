import * as React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bookmark,
  Brain,
  Database,
  Home,
  LayoutDashboard,
  MessageSquare,
  Sparkles,
  type LucideIcon,
} from 'lucide-react';
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from '@/components/ui/command';
import { useThreads, useSavedQuestions } from '@/lib/queries';

interface NavItem {
  id: string;
  label: string;
  icon: LucideIcon;
  to: string;
  shortcut?: string;
}

const NAV: NavItem[] = [
  { id: 'home', label: 'Home', icon: Home, to: '/' },
  { id: 'threads', label: 'Threads', icon: MessageSquare, to: '/threads' },
  { id: 'saved', label: 'Saved questions', icon: Bookmark, to: '/saved' },
  { id: 'dashboards', label: 'Dashboards', icon: LayoutDashboard, to: '/dashboards' },
  { id: 'sources', label: 'Sources', icon: Database, to: '/sources' },
  { id: 'knowledge', label: 'Knowledge', icon: Brain, to: '/knowledge' },
];

const SOLUTIONS: NavItem[] = [
  { id: 'sol-finance', label: 'Compass for Finance', icon: Sparkles, to: '/solutions/finance' },
  { id: 'sol-revops', label: 'Compass for RevOps', icon: Sparkles, to: '/solutions/revops' },
  { id: 'sol-data', label: 'Compass for Data Teams', icon: Sparkles, to: '/solutions/data' },
  { id: 'sol-eng', label: 'Compass for Engineering', icon: Sparkles, to: '/solutions/engineering' },
  { id: 'sol-sec', label: 'Compass for Security', icon: Sparkles, to: '/solutions/security' },
];

export function CommandPalette() {
  const [open, setOpen] = React.useState(false);
  const navigate = useNavigate();

  // Lazy-load threads + saved when palette opens (React Query caches anyway)
  const { data: threadsData } = useThreads({ limit: 20 });
  const { data: savedData } = useSavedQuestions({});

  // ⌘K / Ctrl+K
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const go = (to: string) => {
    setOpen(false);
    navigate(to);
  };

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Search threads, questions, sources, pages…" />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>

        <CommandGroup heading="Go to">
          {NAV.map((n) => (
            <CommandItem key={n.id} onSelect={() => go(n.to)} value={`go ${n.label}`}>
              <n.icon className="text-fg-muted" />
              <span>{n.label}</span>
              {n.id === 'home' && <CommandShortcut>⌘H</CommandShortcut>}
            </CommandItem>
          ))}
        </CommandGroup>

        {threadsData && threadsData.threads.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading={`Threads · ${threadsData.threads.length}`}>
              {threadsData.threads.slice(0, 8).map((t) => (
                <CommandItem
                  key={t.id}
                  onSelect={() => go(`/threads/${t.id}`)}
                  value={`thread ${t.title}`}
                >
                  <MessageSquare className="text-fg-muted" />
                  <span className="truncate flex-1">{t.title}</span>
                  <span className="text-xs text-fg-muted ml-2">
                    {t.message_count} msg
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}

        {savedData && savedData.saved_questions.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading={`Saved · ${savedData.saved_questions.length}`}>
              {savedData.saved_questions.slice(0, 8).map((q) => (
                <CommandItem
                  key={q.id}
                  onSelect={() => go(`/saved`)}
                  value={`saved ${q.title}`}
                >
                  <Bookmark className={q.pinned ? 'text-accent' : 'text-fg-muted'} />
                  <span className="truncate flex-1">{q.title}</span>
                  {q.pinned && (
                    <span className="text-xs text-accent ml-2">pinned</span>
                  )}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}

        <CommandSeparator />
        <CommandGroup heading="Solutions">
          {SOLUTIONS.map((s) => (
            <CommandItem key={s.id} onSelect={() => go(s.to)} value={`solution ${s.label}`}>
              <s.icon className="text-fg-muted" />
              <span>{s.label}</span>
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
