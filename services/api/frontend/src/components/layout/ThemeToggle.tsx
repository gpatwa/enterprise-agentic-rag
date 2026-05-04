import { Monitor, Moon, Sun } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useTheme, type ThemePreference } from '@/lib/theme';
import { cn } from '@/lib/utils';

export function ThemeToggle() {
  const { preference, resolved, setPreference } = useTheme();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label="Toggle theme"
        className="w-9 h-9 rounded-md hover:bg-surface-muted flex items-center justify-center text-fg-secondary hover:text-fg transition"
      >
        {resolved === 'dark' ? (
          <Moon className="w-4 h-4" />
        ) : (
          <Sun className="w-4 h-4" />
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <ThemeOption
          icon={Sun}
          label="Light"
          active={preference === 'light'}
          onClick={() => setPreference('light')}
        />
        <ThemeOption
          icon={Moon}
          label="Dark"
          active={preference === 'dark'}
          onClick={() => setPreference('dark')}
        />
        <ThemeOption
          icon={Monitor}
          label="System"
          active={preference === 'system'}
          onClick={() => setPreference('system')}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ThemeOption({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: typeof Sun;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <DropdownMenuItem
      onClick={onClick}
      className={cn('gap-2', active && 'text-accent')}
    >
      <Icon className="w-3.5 h-3.5" />
      {label}
      {active && <span className="ml-auto text-xs">●</span>}
    </DropdownMenuItem>
  );
}

// Make the prop type explicit so TS picks up the missing `_unused` symbol
export type { ThemePreference };
